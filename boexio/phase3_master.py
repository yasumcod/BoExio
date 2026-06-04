from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse

from boexio.phase1_poc import (
    PARSER_VERSION,
    SCHEMA_VERSION,
    collect_output_files,
    commit_sha,
    failed_row,
    fetch_url,
    parse_html,
    parse_product,
    read_target_urls,
    relative_output_path,
    sha256_file,
    split_error,
    validate_discovered_product_url,
    validate_input_url,
)
from boexio.phase2_variants import (
    CANDIDATE_COLUMNS,
    ERROR_COLUMNS,
    PHASE2_CSV_COLUMNS,
    VariantCandidate,
    configuration_payload,
    enrich_rows,
    error_rows,
    extract_candidates,
    write_candidates_csv,
    write_errors_csv,
    write_phase2_csv,
)


PHASE3_PARSER_VERSION = "0.3.1"
RETRYABLE_ERROR_CODES = {"HTTP_429", "TIMEOUT_CONNECT", "TIMEOUT_READ", "RATE_LIMITED"}
STOP_ERROR_CODES = {"HTTP_403"}
MAX_FAILURE_RATE = 0.30
ABSOLUTE_FAILURE_TARGET_COUNT = 20
ABSOLUTE_FAILURE_COUNT = 5
MAX_SCHEMA_MISMATCH_COUNT = 3


@dataclass(frozen=True)
class CategoryTarget:
    name: str
    url: str
    slug: str = ""


CATEGORY_SLUG_OVERRIDES = {
    "チェア": "chair",
    "ソファ": "sofa",
    "テーブル": "table",
    "ベッド": "bed",
    "収納": "storage",
    "ランプ": "lamp",
    "ラグ": "rug",
    "アクセサリー": "accessories",
    "アウトドア家具": "outdoor-furniture",
}


@dataclass
class RateLimiter:
    interval_seconds: float
    last_request_at: float = 0.0

    def wait(self) -> None:
        if self.interval_seconds <= 0 or self.last_request_at <= 0:
            return
        elapsed = time.monotonic() - self.last_request_at
        remaining = self.interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def mark(self) -> None:
        self.last_request_at = time.monotonic()


class StopRunError(RuntimeError):
    pass


def infer_category_name(url: str) -> str:
    tail = urlparse(url).path.rstrip("/").split("/")[-1]
    return unquote(tail) if tail else url


def normalize_category_url(url: str) -> str:
    parsed = urlparse(url)
    path = quote(unquote(parsed.path), safe="/")
    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment))


def category_slug(category_name: str, category_url: str) -> str:
    name = unicodedata.normalize("NFKC", category_name).strip()
    if name in CATEGORY_SLUG_OVERRIDES:
        return CATEGORY_SLUG_OVERRIDES[name]

    tail = unquote(urlparse(category_url).path.rstrip("/").split("/")[-1])
    source = unicodedata.normalize("NFKC", tail or name).strip().lower()
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", source.encode("ascii", "ignore").decode("ascii")).strip("-")
    if ascii_slug:
        return ascii_slug[:80]
    digest_source = f"{name}\n{normalize_category_url(category_url)}".encode("utf-8")
    return f"category-{hashlib.sha1(digest_source).hexdigest()[:10]}"


def read_target_categories(path: Path) -> list[CategoryTarget]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".csv":
        rows = csv.DictReader(text.splitlines())
        targets: list[CategoryTarget] = []
        for row in rows:
            enabled = row.get("enabled", "true").strip().lower()
            if enabled in {"0", "false", "no", "n"}:
                continue
            url = normalize_category_url(row.get("category_url", "").strip())
            if not url:
                continue
            name = row.get("category_name", "").strip() or infer_category_name(url)
            slug = row.get("category_slug", "").strip() or category_slug(name, url)
            targets.append(CategoryTarget(name=name, url=url, slug=slug))
        return targets

    return [
        CategoryTarget(
            name=infer_category_name(url),
            url=normalize_category_url(url),
            slug=category_slug(infer_category_name(url), normalize_category_url(url)),
        )
        for url in read_target_urls(path)
    ]


def category_from_args(args: argparse.Namespace) -> CategoryTarget:
    url = normalize_category_url(args.category_url.strip())
    name = args.category_name.strip() or infer_category_name(url)
    slug = args.category_slug.strip() or category_slug(name, url)
    return CategoryTarget(name=name, url=url, slug=slug)


def read_product_urls_file(path: Path) -> list[str]:
    product_urls: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        valid, error_code = validate_discovered_product_url(value)
        if not valid:
            raise ValueError(f"{error_code}: product URL is not allowed: {value}")
        if value in seen:
            continue
        seen.add(value)
        product_urls.append(value)
    return product_urls


def collect_product_urls(category_url: str, html: str) -> list[str]:
    parser = parse_html(html)
    product_urls: list[str] = []
    seen: set[str] = set()
    for href, _label in parser.links:
        product_url = urljoin(category_url, href)
        valid, _ = validate_discovered_product_url(product_url)
        if not valid or product_url in seen:
            continue
        seen.add(product_url)
        product_urls.append(product_url)
    return product_urls


def category_pagination_summary(html: str) -> dict[str, object]:
    page_param_matches = re.findall(r'\\"pageParams\\":\[(.*?)\]', html)
    query_hash_matches = re.findall(r'\\"queryHash\\":\\"([^"]+)\\"', html)
    has_static_next_link = bool(re.search(r'rel=["\']next["\']', html, re.IGNORECASE))
    has_japanese_load_more_text = "もっと見る" in html
    has_generic_load_more_translation = "loadMore" in html or "Load more" in html
    return {
        "page_params": sorted(set(page_param_matches)),
        "query_hash_count": len(set(query_hash_matches)),
        "has_static_next_link": has_static_next_link,
        "has_japanese_load_more_text": has_japanese_load_more_text,
        "has_generic_load_more_translation": has_generic_load_more_translation,
    }


def configuration_attribute_summary(html: str) -> list[dict[str, str]]:
    try:
        configuration = configuration_payload(html)
    except Exception:
        return []
    summaries: list[dict[str, str]] = []
    for option in configuration.get("options", []):
        values = option.get("values", [])
        summaries.append(
            {
                "attribute_id": str(option.get("attributeId", "")),
                "attribute_label": str(option.get("attributeLabel", "")),
                "value_count": str(len(values) if isinstance(values, list) else 0),
            }
        )
    return summaries


def is_retryable_error(code: str) -> bool:
    if code in RETRYABLE_ERROR_CODES:
        return True
    return bool(re.fullmatch(r"HTTP_5\d\d", code))


def looks_like_captcha(html: str) -> bool:
    sample = html[:20000].lower()
    return "captcha" in sample or "cf-challenge" in sample or "recaptcha" in sample


def fetch_with_control(url: str, timeout: int, retries: int, limiter: RateLimiter):
    attempts = retries + 1
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        limiter.wait()
        try:
            result = fetch_url(url, timeout)
            limiter.mark()
            if looks_like_captcha(result.html):
                raise StopRunError("RATE_LIMITED: captcha or challenge page detected")
            return result
        except StopRunError:
            limiter.mark()
            raise
        except Exception as exc:
            limiter.mark()
            code, _detail = split_error(exc)
            if code in STOP_ERROR_CODES:
                raise StopRunError(str(exc)) from exc
            last_error = exc
            if attempt >= attempts or not is_retryable_error(code):
                break
    assert last_error is not None
    raise last_error


def safe_raw_name(prefix: str, index: int, url: str) -> str:
    tail = url.rstrip("/").split("/")[-1] or "page"
    tail = re.sub(r"[^A-Za-z0-9._-]+", "_", tail)[:120]
    return f"{prefix}_{index:03d}_{tail}.html"


def candidate_fallback(product_url: str) -> VariantCandidate:
    return VariantCandidate(
        product_url=product_url,
        variant_url=product_url,
        variant_url_key="",
        selected_leg_id="",
        selected_leg="",
        selected_upholstery_id="",
        selected_upholstery="",
        candidate_status="pending",
        candidate_error="",
    )


def add_category_metadata(row: dict[str, str], category: CategoryTarget) -> dict[str, str]:
    enriched = dict(row)
    enriched["category_name"] = category.name
    enriched["category_url"] = category.url
    return enriched


def write_discovered_urls_csv(path: Path, run_id: str, rows: list[dict[str, str]]) -> None:
    columns = ["run_id", "category_name", "category_url", "product_url", "discovery_status", "discovery_error"]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def checksum_files(paths: list[Path]) -> dict[str, str]:
    return {relative_output_path(path): sha256_file(path) for path in paths}


def error_code_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        code = row.get("scrape_error_code", "")
        if not code:
            continue
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def completeness_error_row(url: str, code: str, message: str, when: str | None = None) -> dict[str, str]:
    checked_at = when or datetime.now(timezone.utc).isoformat()
    return {
        "url": url,
        "phase": "completeness",
        "error_code": code,
        "message": message,
        "first_seen_at": checked_at,
        "last_seen_at": checked_at,
    }


def product_variant_completeness_entry(
    *,
    product_url: str,
    category: CategoryTarget,
    product_name: str = "",
    product_fetch_attempt_count: int = 0,
    product_fetch_success_count: int = 0,
    product_fetch_failure_count: int = 0,
    variant_candidate_count: int = 0,
    unique_variant_candidate_count: int = 0,
    variant_invalid_candidate_count: int = 0,
    variant_fetch_attempt_count: int = 0,
    variant_success_count: int = 0,
    variant_failure_count: int = 0,
    variant_skipped_count: int = 0,
    variant_limit_per_product: int = 0,
) -> dict[str, object]:
    limit_applied = variant_limit_per_product > 0
    reasons: list[str] = []
    if product_fetch_attempt_count <= 0:
        reasons.append("product_fetch_not_attempted")
    if product_fetch_success_count <= 0:
        if product_fetch_failure_count > 0:
            reasons.append("product_fetch_failed")
        elif product_fetch_attempt_count > 0:
            reasons.append("product_fetch_incomplete")
    if variant_invalid_candidate_count:
        reasons.append(f"variant_invalid_candidate_count={variant_invalid_candidate_count}")
    if limit_applied and variant_skipped_count:
        reasons.append(f"variant_limit_applied skipped={variant_skipped_count}")

    candidate_attempt_equation_ok = variant_candidate_count == (
        variant_fetch_attempt_count + variant_skipped_count
    )
    fetch_result_equation_ok = variant_fetch_attempt_count == (
        variant_success_count + variant_failure_count
    )
    if not candidate_attempt_equation_ok:
        reasons.append(
            "variant_candidate_count_mismatch "
            f"candidate={variant_candidate_count} attempt={variant_fetch_attempt_count} skipped={variant_skipped_count}"
        )
    if not fetch_result_equation_ok:
        reasons.append(
            "variant_fetch_count_mismatch "
            f"attempt={variant_fetch_attempt_count} success={variant_success_count} failure={variant_failure_count}"
        )

    fetch_attempt_complete = (
        not limit_applied
        and product_fetch_success_count > 0
        and candidate_attempt_equation_ok
        and fetch_result_equation_ok
        and variant_skipped_count == 0
    )
    comparison_complete = (
        fetch_attempt_complete
        and variant_failure_count == 0
        and variant_success_count == variant_candidate_count
        and variant_candidate_count > 0
    )
    if fetch_attempt_complete and not comparison_complete:
        reasons.append(
            "comparison_incomplete "
            f"candidate={variant_candidate_count} success={variant_success_count} failure={variant_failure_count}"
        )

    return {
        "category_slug": category.slug,
        "category_name": category.name,
        "category_url": category.url,
        "product_name": product_name,
        "product_fetch_attempt_count": product_fetch_attempt_count,
        "product_fetch_success_count": product_fetch_success_count,
        "product_fetch_failure_count": product_fetch_failure_count,
        "variant_candidate_count": variant_candidate_count,
        "unique_variant_candidate_count": unique_variant_candidate_count,
        "variant_invalid_candidate_count": variant_invalid_candidate_count,
        "variant_fetch_attempt_count": variant_fetch_attempt_count,
        "variant_success_count": variant_success_count,
        "variant_failure_count": variant_failure_count,
        "variant_skipped_count": variant_skipped_count,
        "variant_limit_per_product": variant_limit_per_product,
        "limit_applied": limit_applied,
        "fetch_attempt_complete": fetch_attempt_complete,
        "comparison_complete": comparison_complete,
        "candidate_attempt_equation_ok": candidate_attempt_equation_ok,
        "fetch_result_equation_ok": fetch_result_equation_ok,
        "reasons": reasons,
    }


def initial_product_variant_stats(product_url: str, category: CategoryTarget) -> dict[str, object]:
    return {
        "product_url": product_url,
        "category": category,
        "product_name": "",
        "product_fetch_attempt_count": 0,
        "product_fetch_success_count": 0,
        "product_fetch_failure_count": 0,
        "variant_candidate_count": 0,
        "unique_variant_candidate_count": 0,
        "variant_invalid_candidate_count": 0,
        "variant_fetch_attempt_count": 0,
        "variant_success_count": 0,
        "variant_failure_count": 0,
        "variant_skipped_count": 0,
    }


def finalize_product_variant_completeness(
    product_variant_stats: dict[str, dict[str, object]],
    variant_limit_per_product: int,
) -> tuple[dict[str, dict[str, object]], list[dict[str, str]]]:
    completeness: dict[str, dict[str, object]] = {}
    errors: list[dict[str, str]] = []
    for product_url, stats in sorted(product_variant_stats.items()):
        category = stats["category"]
        assert isinstance(category, CategoryTarget)
        entry = product_variant_completeness_entry(
            product_url=product_url,
            category=category,
            product_name=str(stats.get("product_name", "")),
            product_fetch_attempt_count=int(stats.get("product_fetch_attempt_count") or 0),
            product_fetch_success_count=int(stats.get("product_fetch_success_count") or 0),
            product_fetch_failure_count=int(stats.get("product_fetch_failure_count") or 0),
            variant_candidate_count=int(stats.get("variant_candidate_count") or 0),
            unique_variant_candidate_count=int(stats.get("unique_variant_candidate_count") or 0),
            variant_invalid_candidate_count=int(stats.get("variant_invalid_candidate_count") or 0),
            variant_fetch_attempt_count=int(stats.get("variant_fetch_attempt_count") or 0),
            variant_success_count=int(stats.get("variant_success_count") or 0),
            variant_failure_count=int(stats.get("variant_failure_count") or 0),
            variant_skipped_count=int(stats.get("variant_skipped_count") or 0),
            variant_limit_per_product=variant_limit_per_product,
        )
        completeness[product_url] = entry
        reasons = [str(reason) for reason in entry.get("reasons", [])]
        limit_only = reasons and all(reason.startswith("variant_limit_applied") for reason in reasons)
        if not reasons or limit_only:
            continue
        message = f"product_url={product_url} " + "; ".join(reasons)
        if not entry.get("candidate_attempt_equation_ok"):
            errors.append(completeness_error_row(product_url, "variant_candidate_count_mismatch", message))
        if not entry.get("fetch_attempt_complete") and not entry.get("limit_applied"):
            errors.append(completeness_error_row(product_url, "incomplete_variant_fetch", message))
        if entry.get("fetch_attempt_complete") and not entry.get("comparison_complete"):
            errors.append(completeness_error_row(product_url, "comparison_incomplete", message))
    return completeness, errors


def build_category_completeness(
    *,
    target_categories: list[CategoryTarget],
    discovered_rows: list[dict[str, str]],
    selected_product_urls: list[str],
    product_category_by_url: dict[str, CategoryTarget],
    processed_product_urls: set[str],
    product_limit_per_category: int,
    product_limit: int,
    category_pagination_summaries: dict[str, dict[str, object]],
) -> tuple[dict[str, dict[str, object]], list[dict[str, str]]]:
    discovered_by_slug: dict[str, list[str]] = {category.slug: [] for category in target_categories}
    discovery_failed_by_slug: dict[str, list[str]] = {category.slug: [] for category in target_categories}
    category_by_url = {category.url: category for category in target_categories}
    for row in discovered_rows:
        category = category_by_url.get(row.get("category_url", ""))
        if not category:
            continue
        product_url = row.get("product_url", "")
        if product_url:
            discovered_by_slug.setdefault(category.slug, []).append(product_url)
        if row.get("discovery_status") == "failed":
            discovery_failed_by_slug.setdefault(category.slug, []).append(row.get("discovery_error", ""))

    chunk_input_by_slug: dict[str, int] = {category.slug: 0 for category in target_categories}
    processed_by_slug: dict[str, set[str]] = {category.slug: set() for category in target_categories}
    for product_url in selected_product_urls:
        category = product_category_by_url.get(product_url)
        if category:
            chunk_input_by_slug[category.slug] = chunk_input_by_slug.get(category.slug, 0) + 1
    for product_url in processed_product_urls:
        category = product_category_by_url.get(product_url)
        if category:
            processed_by_slug.setdefault(category.slug, set()).add(product_url)

    limit_applied = product_limit_per_category > 0 or product_limit > 0
    completeness: dict[str, dict[str, object]] = {}
    errors: list[dict[str, str]] = []
    for category in target_categories:
        discovered = discovered_by_slug.get(category.slug, [])
        unique_discovered = sorted(set(discovered))
        chunk_input_count = chunk_input_by_slug.get(category.slug, 0)
        processed_count = len(processed_by_slug.get(category.slug, set()))
        reasons: list[str] = []
        if limit_applied:
            reasons.append("product_limit_applied")
        if discovery_failed_by_slug.get(category.slug):
            reasons.append("category_discovery_failed")
        if not unique_discovered:
            reasons.append("no_discovered_products")
        if not limit_applied and len(unique_discovered) != chunk_input_count:
            reasons.append(
                f"discovered_vs_chunk_input_mismatch discovered={len(unique_discovered)} chunk_input={chunk_input_count}"
            )
        discovery_complete = not reasons
        product_processing_complete = chunk_input_count == processed_count
        entry = {
            "category_name": category.name,
            "category_url": category.url,
            "category_slug": category.slug,
            "discovered_product_count": len(discovered),
            "unique_discovered_product_count": len(unique_discovered),
            "chunk_input_product_count": chunk_input_count,
            "processed_product_count": processed_count,
            "product_limit_per_category": product_limit_per_category,
            "product_limit": product_limit,
            "limit_applied": limit_applied,
            "discovery_complete_scope": "current_discovery_logic",
            "discovery_complete": discovery_complete,
            "product_processing_complete": product_processing_complete,
            "pagination_summary": category_pagination_summaries.get(category.url, {}),
            "reasons": reasons,
        }
        completeness[category.slug] = entry
        non_limit_reasons = [reason for reason in reasons if reason != "product_limit_applied"]
        if non_limit_reasons:
            errors.append(
                completeness_error_row(
                    category.url,
                    "incomplete_product_discovery",
                    f"category_slug={category.slug} " + "; ".join(non_limit_reasons),
                )
            )
        if not product_processing_complete:
            errors.append(
                completeness_error_row(
                    category.url,
                    "incomplete_variant_fetch",
                    "category_slug="
                    f"{category.slug} chunk_input_product_count={chunk_input_count} "
                    f"processed_product_count={processed_count}",
                )
            )
    return completeness, errors


def determine_run_status(
    success_count: int,
    failure_count: int,
    schema_mismatch_count: int,
    stop_reason: str,
) -> tuple[str, list[str], float]:
    target_count = success_count + failure_count
    failure_rate = failure_count / target_count if target_count else 1.0
    reasons: list[str] = []
    if stop_reason:
        reasons.append(f"stopped: {stop_reason}")
    if failure_rate > MAX_FAILURE_RATE:
        reasons.append(f"failure_rate {failure_rate:.3f} > {MAX_FAILURE_RATE:.2f}")
    if target_count >= ABSOLUTE_FAILURE_TARGET_COUNT and failure_count >= ABSOLUTE_FAILURE_COUNT:
        reasons.append(
            f"failure_count {failure_count} >= {ABSOLUTE_FAILURE_COUNT} with target_count {target_count}"
        )
    if schema_mismatch_count >= MAX_SCHEMA_MISMATCH_COUNT:
        reasons.append(f"schema_mismatch_count {schema_mismatch_count} >= {MAX_SCHEMA_MISMATCH_COUNT}")

    if reasons:
        return "failed", reasons, failure_rate
    if success_count and failure_count:
        return "partial_success", reasons, failure_rate
    if success_count:
        return "success", reasons, failure_rate
    return "failed", ["no successful rows"], failure_rate


def select_products_by_category(
    category_products: dict[str, list[str]],
    limit_per_category: int,
    global_limit: int,
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for category_url, product_urls in category_products.items():
        selected_for_category = 0
        for product_url in product_urls:
            if product_url in seen:
                continue
            selected.append(product_url)
            seen.add(product_url)
            selected_for_category += 1
            if global_limit > 0 and len(selected) >= global_limit:
                return selected
            if limit_per_category > 0 and selected_for_category >= limit_per_category:
                break
    return selected


def select_variant_candidates(candidates: list[VariantCandidate], limit_per_product: int) -> list[VariantCandidate]:
    valid_candidates = [candidate for candidate in candidates if candidate.candidate_status == "pending"]
    if limit_per_product <= 0:
        return valid_candidates
    return valid_candidates[:limit_per_product]


def run(args: argparse.Namespace) -> int:
    started_at = datetime.now(timezone.utc)
    run_id = args.run_id or started_at.strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir) / "runs" / run_id
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    limiter = RateLimiter(interval_seconds=args.request_interval)
    if args.product_urls_file:
        if not args.category_url:
            raise ValueError("--category-url is required when --product-urls-file is specified")
        target_categories = [category_from_args(args)]
    else:
        target_categories = read_target_categories(Path(args.targets))
    logs: list[str] = []
    rows: list[dict[str, str]] = []
    candidates: list[VariantCandidate] = []
    discovered_rows: list[dict[str, str]] = []
    product_candidate_counts: dict[str, int] = {}
    product_attribute_summaries: dict[str, list[dict[str, str]]] = {}
    category_pagination_summaries: dict[str, dict[str, object]] = {}
    product_variant_stats: dict[str, dict[str, object]] = {}
    category_products_by_url: dict[str, list[str]] = {}
    product_category_by_url: dict[str, CategoryTarget] = {}
    selected_product_urls: list[str] = []
    discovered_product_url_count = 0
    stop_reason = ""

    try:
        seen_products: set[str] = set()
        if args.product_urls_file:
            target = target_categories[0]
            product_urls = read_product_urls_file(Path(args.product_urls_file))
            category_products_by_url[target.url] = product_urls
            for product_url in product_urls:
                product_category_by_url[product_url] = target
                discovered_rows.append(
                    {
                        "run_id": run_id,
                        "category_name": target.name,
                        "category_url": target.url,
                        "product_url": product_url,
                        "discovery_status": "success",
                        "discovery_error": "",
                    }
                )
            logs.append(
                f"product_urls_file={args.product_urls_file} category_name={target.name} "
                f"category_url={target.url} product_url_count={len(product_urls)}"
            )
        for category_index, target in enumerate(target_categories, start=1):
            if args.product_urls_file:
                break
            target_url = target.url
            valid, error_code = validate_input_url(target_url)
            if not valid:
                rows.append(add_category_metadata(failed_row(run_id, target_url, error_code, "input URL is not allowed"), target))
                discovered_rows.append(
                    {
                        "run_id": run_id,
                        "category_name": target.name,
                        "category_url": target_url,
                        "product_url": "",
                        "discovery_status": "failed",
                        "discovery_error": error_code,
                    }
                )
                continue
            try:
                category = fetch_with_control(target_url, args.timeout, args.retries, limiter)
                raw_name = safe_raw_name("category", category_index, target_url)
                (raw_dir / raw_name).write_text(category.html, encoding="utf-8")
                category_pagination_summaries[target_url] = category_pagination_summary(category.html)
                category_products = collect_product_urls(target_url, category.html)
                category_products_by_url[target_url] = []
                logs.append(f"category_name={target.name} category_url={target_url} product_url_count={len(category_products)}")
                for product_url in category_products:
                    category_products_by_url[target_url].append(product_url)
                    if product_url not in product_category_by_url:
                        product_category_by_url[product_url] = target
                    discovered_rows.append(
                        {
                            "run_id": run_id,
                            "category_name": target.name,
                            "category_url": target_url,
                            "product_url": product_url,
                            "discovery_status": "duplicate" if product_url in seen_products else "success",
                            "discovery_error": "duplicate_product_url" if product_url in seen_products else "",
                        }
                    )
                    seen_products.add(product_url)
            except StopRunError as exc:
                stop_reason = str(exc)
                raise
            except Exception as exc:
                code, detail = split_error(exc)
                rows.append(add_category_metadata(failed_row(run_id, target_url, code, detail), target))
                discovered_rows.append(
                    {
                        "run_id": run_id,
                        "category_name": target.name,
                        "category_url": target_url,
                        "product_url": "",
                        "discovery_status": "failed",
                        "discovery_error": code,
                    }
                )
                logs.append(f"failed_category_url={target_url} code={code} detail={detail}")

        selected_product_urls = select_products_by_category(
            category_products_by_url,
            args.product_limit_per_category,
            args.product_limit,
        )
        discovered_product_url_count = len(product_category_by_url)
        logs.append(f"discovered_product_url_count={discovered_product_url_count}")
        logs.append(f"product_limit={args.product_limit}")
        logs.append(f"product_limit_per_category={args.product_limit_per_category}")
        logs.append(f"variant_limit_per_product={args.variant_limit_per_product}")
        logs.append(f"request_interval={args.request_interval}")
        logs.append(f"retries={args.retries}")

        for product_index, product_url in enumerate(selected_product_urls, start=1):
            product_category = product_category_by_url[product_url]
            product_stats = product_variant_stats.setdefault(
                product_url,
                initial_product_variant_stats(product_url, product_category),
            )
            product_stats["product_fetch_attempt_count"] = int(product_stats["product_fetch_attempt_count"]) + 1
            try:
                product_page = fetch_with_control(product_url, args.timeout, args.retries, limiter)
                product_stats["product_fetch_success_count"] = int(product_stats["product_fetch_success_count"]) + 1
                raw_name = safe_raw_name("product", product_index, product_url)
                (raw_dir / raw_name).write_text(product_page.html, encoding="utf-8")
                product_attribute_summaries[product_url] = configuration_attribute_summary(product_page.html)
                try:
                    product_candidates = extract_candidates(product_url, product_page.html)
                except Exception as exc:
                    product_candidates = [candidate_fallback(product_url)]
                    code, detail = split_error(exc)
                    logs.append(
                        f"candidate_extraction_fallback_url={product_url} code={code} detail={detail}"
                    )
                product_candidate_counts[product_url] = len(product_candidates)
                candidates.extend(product_candidates)
                pending_candidates = [
                    candidate for candidate in product_candidates if candidate.candidate_status == "pending"
                ]
                product_stats["variant_candidate_count"] = len(product_candidates)
                product_stats["unique_variant_candidate_count"] = len(
                    {candidate.variant_url for candidate in product_candidates if candidate.variant_url}
                )
                product_stats["variant_invalid_candidate_count"] = len(product_candidates) - len(pending_candidates)

                selected_candidates = select_variant_candidates(product_candidates, args.variant_limit_per_product)
                product_stats["variant_skipped_count"] = (
                    max(len(pending_candidates) - len(selected_candidates), 0)
                    if args.variant_limit_per_product > 0
                    else 0
                )
                for candidate_index, candidate in enumerate(selected_candidates, start=1):
                    product_stats["variant_fetch_attempt_count"] = int(product_stats["variant_fetch_attempt_count"]) + 1
                    try:
                        variant_page = fetch_with_control(
                            candidate.variant_url,
                            args.timeout,
                            args.retries,
                            limiter,
                        )
                        raw_name = safe_raw_name(
                            f"variant_{product_index:03d}",
                            candidate_index,
                            candidate.variant_url,
                        )
                        raw_path = raw_dir / raw_name
                        raw_path.write_text(variant_page.html, encoding="utf-8")
                        parsed_row = parse_product(variant_page, f"raw/{raw_name}", run_id)
                        if parsed_row.get("product_name") and not product_stats.get("product_name"):
                            product_stats["product_name"] = parsed_row["product_name"]
                        rows.append(add_category_metadata(parsed_row, product_category))
                        product_stats["variant_success_count"] = int(product_stats["variant_success_count"]) + 1
                        logs.append(f"fetched_variant_url={candidate.variant_url}")
                    except StopRunError:
                        raise
                    except Exception as exc:
                        code, detail = split_error(exc)
                        rows.append(add_category_metadata(failed_row(run_id, candidate.variant_url, code, detail), product_category))
                        product_stats["variant_failure_count"] = int(product_stats["variant_failure_count"]) + 1
                        logs.append(f"failed_variant_url={candidate.variant_url} code={code} detail={detail}")
            except StopRunError as exc:
                stop_reason = str(exc)
                raise
            except Exception as exc:
                code, detail = split_error(exc)
                rows.append(add_category_metadata(failed_row(run_id, product_url, code, detail), product_category))
                product_stats["product_fetch_failure_count"] = int(product_stats["product_fetch_failure_count"]) + 1
                logs.append(f"failed_product_url={product_url} code={code} detail={detail}")
    except StopRunError as exc:
        stop_reason = str(exc)
        logs.append(f"run_stopped={stop_reason}")

    discovered_product_url_count = len(product_category_by_url)
    enriched_rows = enrich_rows(rows)
    errors = error_rows(enriched_rows)
    product_variant_completeness, product_completeness_errors = finalize_product_variant_completeness(
        product_variant_stats,
        args.variant_limit_per_product,
    )
    category_completeness, category_completeness_errors = build_category_completeness(
        target_categories=target_categories,
        discovered_rows=discovered_rows,
        selected_product_urls=selected_product_urls,
        product_category_by_url=product_category_by_url,
        processed_product_urls=set(product_variant_stats),
        product_limit_per_category=args.product_limit_per_category,
        product_limit=args.product_limit,
        category_pagination_summaries=category_pagination_summaries,
    )
    errors.extend(product_completeness_errors)
    errors.extend(category_completeness_errors)

    current_path = output_dir / "products_current.csv"
    snapshot_path = output_dir / f"products_{started_at.strftime('%Y-%m-%d')}_{run_id}.csv"
    candidates_path = output_dir / "variant_candidates.csv"
    discovered_path = output_dir / "discovered_product_urls.csv"
    errors_path = output_dir / "errors.csv"
    log_path = output_dir / "scrape_log.txt"
    metadata_path = output_dir / "run_metadata.json"

    write_phase2_csv(current_path, enriched_rows)
    write_phase2_csv(snapshot_path, enriched_rows)
    write_candidates_csv(candidates_path, run_id, candidates)
    write_discovered_urls_csv(discovered_path, run_id, discovered_rows)
    write_errors_csv(errors_path, errors)
    log_path.write_text("\n".join(logs) + "\n", encoding="utf-8")

    success_count = sum(1 for row in rows if row["scrape_status"] == "success")
    failure_count = sum(1 for row in rows if row["scrape_status"] == "failed")
    scrape_error_code_counts = error_code_counts(enriched_rows)
    schema_mismatch_count = scrape_error_code_counts.get("SCHEMA_MISMATCH", 0)
    discovered_counts_by_category = {
        target.url: len(category_products_by_url.get(target.url, [])) for target in target_categories
    }
    selected_counts_by_category: dict[str, int] = {}
    for product_url in selected_product_urls:
        category = product_category_by_url[product_url]
        selected_counts_by_category[category.url] = selected_counts_by_category.get(category.url, 0) + 1
    run_status, run_status_reasons, failure_rate = determine_run_status(
        success_count,
        failure_count,
        schema_mismatch_count,
        stop_reason,
    )
    full_variant_run = (
        args.product_limit <= 0
        and args.product_limit_per_category <= 0
        and args.variant_limit_per_product <= 0
    )
    if full_variant_run:
        incomplete_discovery_categories = [
            slug for slug, entry in category_completeness.items() if not entry.get("discovery_complete")
        ]
        unprocessed_category_products = [
            slug
            for slug, entry in category_completeness.items()
            if not entry.get("product_processing_complete")
        ]
        incomplete_fetch_products = [
            product_url
            for product_url, entry in product_variant_completeness.items()
            if not entry.get("fetch_attempt_complete")
        ]
        comparison_incomplete_products = [
            product_url
            for product_url, entry in product_variant_completeness.items()
            if entry.get("fetch_attempt_complete") and not entry.get("comparison_complete")
        ]
        if incomplete_discovery_categories or unprocessed_category_products or incomplete_fetch_products:
            run_status = "failed"
            run_status_reasons.extend(
                [
                    f"discovery_complete=false categories={','.join(incomplete_discovery_categories)}"
                    if incomplete_discovery_categories
                    else "",
                    f"product_processing_complete=false categories={','.join(unprocessed_category_products)}"
                    if unprocessed_category_products
                    else "",
                    f"fetch_attempt_complete=false product_count={len(incomplete_fetch_products)}"
                    if incomplete_fetch_products
                    else "",
                ]
            )
            run_status_reasons = [reason for reason in run_status_reasons if reason]
        elif comparison_incomplete_products:
            run_status = "partial_success"
            run_status_reasons = [
                reason
                for reason in run_status_reasons
                if not reason.startswith("failure_rate ") and not reason.startswith("failure_count ")
            ]
            run_status_reasons.append(
                f"comparison_complete=false product_count={len(comparison_incomplete_products)}"
            )

    checksum_targets = [
        current_path,
        snapshot_path,
        candidates_path,
        discovered_path,
        errors_path,
        log_path,
        *collect_output_files(raw_dir),
    ]
    output_files = [*checksum_targets, metadata_path]
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PHASE3_PARSER_VERSION,
        "phase1_parser_version": PARSER_VERSION,
        "commit_sha": commit_sha(),
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "target_urls": [target.url for target in target_categories],
        "target_categories": [
            {"category_name": target.name, "category_url": target.url, "category_slug": target.slug}
            for target in target_categories
        ],
        "category_name": target_categories[0].name if len(target_categories) == 1 else args.category_name,
        "category_url": target_categories[0].url if len(target_categories) == 1 else args.category_url,
        "category_slug": args.category_slug or (target_categories[0].slug if len(target_categories) == 1 else ""),
        "chunk_slug": args.chunk_slug,
        "chunk_index": args.chunk_index,
        "chunk_product_count": len(read_product_urls_file(Path(args.product_urls_file))) if args.product_urls_file else 0,
        "product_urls_file": args.product_urls_file,
        "product_limit": args.product_limit,
        "product_limit_per_category": args.product_limit_per_category,
        "variant_limit_per_product": args.variant_limit_per_product,
        "request_interval": args.request_interval,
        "timeout": args.timeout,
        "retries": args.retries,
        "discovered_product_url_count": discovered_product_url_count,
        "discovered_product_counts_by_category": discovered_counts_by_category,
        "selected_product_count": len(selected_product_urls),
        "selected_product_counts_by_category": selected_counts_by_category,
        "processed_product_count": len(product_variant_stats),
        "product_candidate_counts": product_candidate_counts,
        "product_attribute_summaries": product_attribute_summaries,
        "category_completeness": category_completeness,
        "product_variant_completeness": product_variant_completeness,
        "category_pagination_summaries": category_pagination_summaries,
        "variant_candidate_count": len(candidates),
        "variant_fetch_attempt_count": sum(
            int(entry.get("variant_fetch_attempt_count") or 0)
            for entry in product_variant_completeness.values()
        ),
        "variant_success_count": sum(
            int(entry.get("variant_success_count") or 0) for entry in product_variant_completeness.values()
        ),
        "variant_failure_count": sum(
            int(entry.get("variant_failure_count") or 0) for entry in product_variant_completeness.values()
        ),
        "variant_skipped_count": sum(
            int(entry.get("variant_skipped_count") or 0) for entry in product_variant_completeness.values()
        ),
        "variant_key_success_count": sum(1 for row in enriched_rows if row.get("variant_key")),
        "error_count": len(errors),
        "scrape_error_code_counts": scrape_error_code_counts,
        "failure_rate": failure_rate,
        "schema_mismatch_count": schema_mismatch_count,
        "run_status_reasons": run_status_reasons,
        "stop_reason": stop_reason,
        "output_files": [relative_output_path(path) for path in output_files],
        "output_file_checksums": checksum_files(checksum_targets),
        "run_status": run_status,
        "success_count": success_count,
        "failure_count": failure_count,
        "notes": [
            "Phase 3 discovers product URLs from allowed category pages and processes them sequentially.",
            "Concurrency is fixed at 1; request_interval controls the request rate.",
            "HTTP_429, HTTP_5xx, TIMEOUT_CONNECT, TIMEOUT_READ, and RATE_LIMITED are retried per URL.",
            "HTTP_403 or captcha/challenge detection stops the run immediately.",
            "products_current.csv and the dated products snapshot have the Phase 2 enriched schema.",
            "variant_limit_per_product=0 means all pending variant candidates for each product are fetched.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if success_count else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run BoExio Phase 3 product master generation.")
    parser.add_argument("--targets", default="config/target_categories.csv")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--category-url", default="")
    parser.add_argument("--category-name", default="")
    parser.add_argument("--category-slug", default="")
    parser.add_argument("--chunk-slug", default="")
    parser.add_argument("--chunk-index", type=int, default=0)
    parser.add_argument("--product-urls-file", default="")
    parser.add_argument("--product-limit", type=int, default=0)
    parser.add_argument("--product-limit-per-category", type=int, default=3)
    parser.add_argument("--variant-limit-per-product", type=int, default=1)
    parser.add_argument("--request-interval", type=float, default=5.0)
    parser.add_argument("--retries", type=int, default=2)
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
