from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

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


PHASE3_PARSER_VERSION = "0.3.0"
RETRYABLE_ERROR_CODES = {"HTTP_429", "TIMEOUT_CONNECT", "TIMEOUT_READ", "RATE_LIMITED"}
STOP_ERROR_CODES = {"HTTP_403"}
MAX_FAILURE_RATE = 0.30
ABSOLUTE_FAILURE_TARGET_COUNT = 20
ABSOLUTE_FAILURE_COUNT = 5
MAX_SCHEMA_MISMATCH_COUNT = 3


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


def write_discovered_urls_csv(path: Path, run_id: str, rows: list[dict[str, str]]) -> None:
    columns = ["run_id", "category_url", "product_url", "discovery_status", "discovery_error"]
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


def run(args: argparse.Namespace) -> int:
    started_at = datetime.now(timezone.utc)
    run_id = args.run_id or started_at.strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir) / "runs" / run_id
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    limiter = RateLimiter(interval_seconds=args.request_interval)
    target_urls = read_target_urls(Path(args.targets))
    logs: list[str] = []
    rows: list[dict[str, str]] = []
    candidates: list[VariantCandidate] = []
    discovered_rows: list[dict[str, str]] = []
    product_candidate_counts: dict[str, int] = {}
    product_attribute_summaries: dict[str, list[dict[str, str]]] = {}
    category_pagination_summaries: dict[str, dict[str, object]] = {}
    stop_reason = ""

    try:
        discovered_product_urls: list[str] = []
        seen_products: set[str] = set()
        for category_index, target_url in enumerate(target_urls, start=1):
            valid, error_code = validate_input_url(target_url)
            if not valid:
                rows.append(failed_row(run_id, target_url, error_code, "input URL is not allowed"))
                discovered_rows.append(
                    {
                        "run_id": run_id,
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
                logs.append(f"category_url={target_url} product_url_count={len(category_products)}")
                for product_url in category_products:
                    if product_url in seen_products:
                        continue
                    seen_products.add(product_url)
                    discovered_product_urls.append(product_url)
                    discovered_rows.append(
                        {
                            "run_id": run_id,
                            "category_url": target_url,
                            "product_url": product_url,
                            "discovery_status": "success",
                            "discovery_error": "",
                        }
                    )
            except StopRunError as exc:
                stop_reason = str(exc)
                raise
            except Exception as exc:
                code, detail = split_error(exc)
                rows.append(failed_row(run_id, target_url, code, detail))
                discovered_rows.append(
                    {
                        "run_id": run_id,
                        "category_url": target_url,
                        "product_url": "",
                        "discovery_status": "failed",
                        "discovery_error": code,
                    }
                )
                logs.append(f"failed_category_url={target_url} code={code} detail={detail}")

        selected_product_urls = discovered_product_urls[: args.product_limit]
        logs.append(f"discovered_product_url_count={len(discovered_product_urls)}")
        logs.append(f"product_limit={args.product_limit}")
        logs.append(f"variant_limit_per_product={args.variant_limit_per_product}")
        logs.append(f"request_interval={args.request_interval}")
        logs.append(f"retries={args.retries}")

        for product_index, product_url in enumerate(selected_product_urls, start=1):
            try:
                product_page = fetch_with_control(product_url, args.timeout, args.retries, limiter)
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

                valid_candidates = [
                    candidate for candidate in product_candidates if candidate.candidate_status == "pending"
                ]
                for candidate_index, candidate in enumerate(
                    valid_candidates[: args.variant_limit_per_product],
                    start=1,
                ):
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
                        rows.append(parse_product(variant_page, f"raw/{raw_name}", run_id))
                        logs.append(f"fetched_variant_url={candidate.variant_url}")
                    except StopRunError:
                        raise
                    except Exception as exc:
                        code, detail = split_error(exc)
                        rows.append(failed_row(run_id, candidate.variant_url, code, detail))
                        logs.append(f"failed_variant_url={candidate.variant_url} code={code} detail={detail}")
            except StopRunError as exc:
                stop_reason = str(exc)
                raise
            except Exception as exc:
                code, detail = split_error(exc)
                rows.append(failed_row(run_id, product_url, code, detail))
                logs.append(f"failed_product_url={product_url} code={code} detail={detail}")
    except StopRunError as exc:
        stop_reason = str(exc)
        logs.append(f"run_stopped={stop_reason}")

    enriched_rows = enrich_rows(rows)
    errors = error_rows(enriched_rows)

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
    run_status, run_status_reasons, failure_rate = determine_run_status(
        success_count,
        failure_count,
        schema_mismatch_count,
        stop_reason,
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
        "target_urls": target_urls,
        "product_limit": args.product_limit,
        "variant_limit_per_product": args.variant_limit_per_product,
        "request_interval": args.request_interval,
        "timeout": args.timeout,
        "retries": args.retries,
        "discovered_product_url_count": sum(
            1 for row in discovered_rows if row["discovery_status"] == "success"
        ),
        "processed_product_count": len(product_candidate_counts),
        "product_candidate_counts": product_candidate_counts,
        "product_attribute_summaries": product_attribute_summaries,
        "category_pagination_summaries": category_pagination_summaries,
        "variant_candidate_count": len(candidates),
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
        ],
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if success_count else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run BoExio Phase 3 product master generation.")
    parser.add_argument("--targets", default="config/target_urls.txt")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--product-limit", type=int, default=3)
    parser.add_argument("--variant-limit-per-product", type=int, default=1)
    parser.add_argument("--request-interval", type=float, default=5.0)
    parser.add_argument("--retries", type=int, default=2)
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
