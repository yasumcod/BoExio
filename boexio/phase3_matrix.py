from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from boexio.phase2_variants import ERROR_COLUMNS, extract_candidates
from boexio.phase3_master import (
    CategoryTarget,
    RateLimiter,
    category_pagination_summary,
    collect_product_urls,
    fetch_with_control,
    read_target_categories,
    safe_raw_name,
    sitemap_discovery_outputs,
    split_error,
    validate_input_url,
)
from boexio.phase3_discovery import (
    CATEGORY_EXPECTED_COLUMNS,
    CATEGORY_PRODUCT_MASTER_COUNT_COLUMNS,
    CLASSIFIED_PRODUCT_COLUMNS,
    SITEMAP_INDEX_URL,
    SITEMAP_PRODUCT_COLUMNS,
    write_csv_rows,
)


DISCOVERED_COLUMNS = ["run_id", "category_name", "category_url", "product_url", "discovery_status", "discovery_error"]


@dataclass(frozen=True)
class ProductChunk:
    category_name: str
    category_url: str
    category_slug: str
    chunk_index: int
    chunk_slug: str
    product_urls: list[str]
    product_urls_file: str


@dataclass(frozen=True)
class ProductVariantPlan:
    product_url: str
    variant_offset: int
    variant_limit: int
    estimated_variant_count: int


@dataclass(frozen=True)
class VariantChunk:
    category_name: str
    category_url: str
    category_slug: str
    chunk_index: int
    chunk_slug: str
    product_plans: list[ProductVariantPlan]
    product_plan_file: str
    estimated_request_count: int


def matrix_for_categories(categories: list[CategoryTarget]) -> dict[str, list[dict[str, str]]]:
    return {
        "include": [
            {
                "category_name": category.name,
                "category_url": category.url,
                "category_slug": category.slug,
            }
            for category in categories
        ]
    }


def limited_product_urls(product_urls: list[str], product_limit_per_category: int) -> list[str]:
    if product_limit_per_category <= 0:
        return list(product_urls)
    return list(product_urls[:product_limit_per_category])


def chunk_product_urls(
    category: CategoryTarget,
    product_urls: list[str],
    chunk_size: int,
    matrix_dir: Path | None = None,
) -> list[ProductChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    chunks: list[ProductChunk] = []
    for offset in range(0, len(product_urls), chunk_size):
        chunk_index = len(chunks) + 1
        chunk_slug = f"{category.slug}-{chunk_index:03d}"
        product_urls_file = f"matrix/{chunk_slug}-product-urls.txt"
        chunk_urls = list(product_urls[offset : offset + chunk_size])
        if matrix_dir is not None:
            path = matrix_dir / f"{chunk_slug}-product-urls.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(chunk_urls) + "\n", encoding="utf-8")
        chunks.append(
            ProductChunk(
                category_name=category.name,
                category_url=category.url,
                category_slug=category.slug,
                chunk_index=chunk_index,
                chunk_slug=chunk_slug,
                product_urls=chunk_urls,
                product_urls_file=product_urls_file,
            )
        )
    return chunks


def matrix_for_chunks(chunks: list[ProductChunk]) -> dict[str, list[dict[str, object]]]:
    return {
        "include": [
            {
                "category_name": chunk.category_name,
                "category_url": chunk.category_url,
                "category_slug": chunk.category_slug,
                "chunk_index": chunk.chunk_index,
                "chunk_slug": chunk.chunk_slug,
                "chunk_product_count": len(chunk.product_urls),
                "product_urls_file": chunk.product_urls_file,
            }
            for chunk in chunks
        ]
    }


def variant_request_budget(request_interval: float, target_minutes: int) -> int:
    if target_minutes <= 0:
        raise ValueError("variant_shard_target_minutes must be greater than 0")
    effective_interval = max(request_interval, 1.0)
    return max(1, math.floor(target_minutes * 60 / effective_interval))


def shard_product_variants(
    product_url: str,
    variant_count: int,
    max_requests_per_chunk: int,
) -> list[ProductVariantPlan]:
    if max_requests_per_chunk <= 0:
        raise ValueError("max_requests_per_chunk must be greater than 0")
    if variant_count <= 0:
        return []
    return [
        ProductVariantPlan(
            product_url=product_url,
            variant_offset=offset,
            variant_limit=min(max_requests_per_chunk, variant_count - offset),
            estimated_variant_count=variant_count,
        )
        for offset in range(0, variant_count, max_requests_per_chunk)
    ]


def pack_variant_plans(
    category: CategoryTarget,
    product_plans: list[ProductVariantPlan],
    chunk_size: int,
    max_requests_per_chunk: int,
    matrix_dir: Path | None = None,
) -> list[VariantChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    chunks: list[VariantChunk] = []
    current: list[ProductVariantPlan] = []
    current_requests = 0

    def flush() -> None:
        nonlocal current, current_requests
        if not current:
            return
        chunk_index = len(chunks) + 1
        chunk_slug = f"{category.slug}-{chunk_index:03d}"
        product_plan_file = f"matrix/{chunk_slug}-product-plan.json"
        if matrix_dir is not None:
            write_json(
                matrix_dir / f"{chunk_slug}-product-plan.json",
                {
                    "products": [
                        {
                            "product_url": plan.product_url,
                            "variant_offset": plan.variant_offset,
                            "variant_limit": plan.variant_limit,
                            "estimated_variant_count": plan.estimated_variant_count,
                        }
                        for plan in current
                    ]
                },
            )
        chunks.append(
            VariantChunk(
                category_name=category.name,
                category_url=category.url,
                category_slug=category.slug,
                chunk_index=chunk_index,
                chunk_slug=chunk_slug,
                product_plans=list(current),
                product_plan_file=product_plan_file,
                estimated_request_count=current_requests,
            )
        )
        current = []
        current_requests = 0

    for plan in product_plans:
        plan_requests = plan.variant_limit
        product_already_present = any(item.product_url == plan.product_url for item in current)
        if current and (
            current_requests + plan_requests > max_requests_per_chunk
            or (not product_already_present and len({item.product_url for item in current}) >= chunk_size)
        ):
            flush()
        current.append(plan)
        current_requests += plan_requests
        if current_requests >= max_requests_per_chunk:
            flush()
    flush()
    return chunks


def matrix_for_variant_chunks(
    chunks: list[VariantChunk],
    request_interval: float = 0,
) -> dict[str, list[dict[str, object]]]:
    return {
        "include": [
            {
                "category_name": chunk.category_name,
                "category_url": chunk.category_url,
                "category_slug": chunk.category_slug,
                "chunk_index": chunk.chunk_index,
                "chunk_slug": chunk.chunk_slug,
                "chunk_product_count": len({plan.product_url for plan in chunk.product_plans}),
                "product_plan_file": chunk.product_plan_file,
                "product_urls": sorted({plan.product_url for plan in chunk.product_plans}),
                "estimated_request_count": chunk.estimated_request_count,
                "estimated_minimum_seconds": round(
                    chunk.estimated_request_count * max(request_interval, 0),
                    3,
                ),
            }
            for chunk in chunks
        ]
    }


def validate_chunk_matrix(matrix: dict[str, object]) -> None:
    include = matrix.get("include")
    if not isinstance(include, list) or not include:
        raise ValueError("chunk matrix must define at least one vector")


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_categories(args: argparse.Namespace) -> int:
    categories = read_target_categories(Path(args.targets))
    payload = matrix_for_categories(categories)
    write_json(Path(args.output), payload)
    return 0


def validate_chunk_matrix_file(args: argparse.Namespace) -> int:
    matrix = json.loads(Path(args.input).read_text(encoding="utf-8"))
    validate_chunk_matrix(matrix)
    return 0


def parse_category_slug_filter(value: str) -> set[str]:
    return {slug.strip() for slug in value.split(",") if slug.strip()}


def discover_products(args: argparse.Namespace) -> int:
    started_at = datetime.now(timezone.utc)
    run_id = args.run_id or started_at.strftime("%Y%m%dT%H%M%SZ")
    matrix_dir = Path(args.output_dir)
    raw_dir = matrix_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    categories = read_target_categories(Path(args.targets))
    category_slug_filter = parse_category_slug_filter(args.category_slug)
    if category_slug_filter:
        categories = [category for category in categories if category.slug in category_slug_filter]
    limiter = RateLimiter(interval_seconds=args.request_interval)

    chunks: list[VariantChunk] = []
    discovered_rows: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    logs: list[str] = []
    discovered_counts_by_category: dict[str, int] = {}
    selected_counts_by_category: dict[str, int] = {}
    category_pagination_summaries: dict[str, dict[str, object]] = {}
    remaining_global = args.product_limit if args.product_limit > 0 else None
    sitemap_category_products_by_url: dict[str, list[str]] = {}
    sitemap_category_completeness: dict[str, dict[str, object]] = {}
    sitemap_discovery_metadata: dict[str, object] = {}

    if args.discovery_mode == "sitemap":
        (
            sitemap_category_products_by_url,
            _sitemap_product_category_by_url,
            discovered_rows,
            sitemap_pagination_summaries,
            sitemap_errors,
            sitemap_discovery_metadata,
            sitemap_rows,
            expected_rows,
            product_master_count_rows,
            classified_rows,
        ) = sitemap_discovery_outputs(
            args=args,
            target_categories=categories,
            run_id=run_id,
            raw_dir=raw_dir,
            limiter=limiter,
            logs=logs,
        )
        errors.extend(sitemap_errors)
        sitemap_category_completeness = {
            slug: entry
            for slug, entry in sitemap_discovery_metadata.get("category_completeness", {}).items()
            if isinstance(entry, dict)
        }
        category_pagination_summaries = {
            category.slug: sitemap_pagination_summaries.get(category.url, {})
            for category in categories
        }
        write_csv_rows(matrix_dir / "sitemap_product_urls.csv", SITEMAP_PRODUCT_COLUMNS, sitemap_rows)
        write_csv_rows(matrix_dir / "category_expected_counts.csv", CATEGORY_EXPECTED_COLUMNS, expected_rows)
        write_csv_rows(
            matrix_dir / "category_product_master_counts.csv",
            CATEGORY_PRODUCT_MASTER_COUNT_COLUMNS,
            product_master_count_rows,
        )
        write_csv_rows(matrix_dir / "classified_product_urls.csv", CLASSIFIED_PRODUCT_COLUMNS, classified_rows)
        write_json(matrix_dir / "phase3_discovery_metadata.json", sitemap_discovery_metadata)

    for category_index, category in enumerate(categories, start=1):
        try:
            if args.discovery_mode == "sitemap":
                product_urls = sitemap_category_products_by_url.get(category.url, [])
            else:
                valid, error_code = validate_input_url(category.url)
                if not valid:
                    discovered_rows.append(
                        {
                            "run_id": run_id,
                            "category_name": category.name,
                            "category_url": category.url,
                            "product_url": "",
                            "discovery_status": "failed",
                            "discovery_error": error_code,
                        }
                    )
                    errors.append(error_row(category.url, "discover-products", error_code, "input URL is not allowed"))
                    discovered_counts_by_category[category.slug] = 0
                    selected_counts_by_category[category.slug] = 0
                    continue
                page = fetch_with_control(category.url, args.timeout, args.retries, limiter)
                raw_name = safe_raw_name("category", category_index, category.url)
                (raw_dir / raw_name).write_text(page.html, encoding="utf-8")
                category_pagination_summaries[category.slug] = category_pagination_summary(page.html)
                product_urls = collect_product_urls(category.url, page.html)
            limited_urls = limited_product_urls(product_urls, args.product_limit_per_category)
            if remaining_global is not None:
                limited_urls = limited_urls[:remaining_global]
                remaining_global -= len(limited_urls)
            discovered_counts_by_category[category.slug] = len(product_urls)
            selected_counts_by_category[category.slug] = len(limited_urls)
            logs.append(
                f"category_slug={category.slug} category_name={category.name} "
                f"discovered={len(product_urls)} selected={len(limited_urls)}"
            )
            if not product_urls:
                errors.append(error_row(category.url, "discover-products", "no_products_found", "category had 0 product URLs"))
            if args.discovery_mode != "sitemap":
                for product_url in product_urls:
                    discovered_rows.append(
                        {
                            "run_id": run_id,
                            "category_name": category.name,
                            "category_url": category.url,
                            "product_url": product_url,
                            "discovery_status": "success",
                            "discovery_error": "",
                        }
                    )
            max_requests_per_chunk = variant_request_budget(
                args.request_interval,
                args.variant_shard_target_minutes,
            )
            category_plans: list[ProductVariantPlan] = []
            for product_index, product_url in enumerate(limited_urls, start=1):
                try:
                    product_page = fetch_with_control(product_url, args.timeout, args.retries, limiter)
                    raw_name = safe_raw_name(
                        f"planned_product_{category.slug}",
                        product_index,
                        product_url,
                    )
                    (raw_dir / raw_name).write_text(product_page.html, encoding="utf-8")
                    candidates = [
                        candidate
                        for candidate in extract_candidates(product_url, product_page.html)
                        if candidate.candidate_status == "pending"
                    ]
                    candidate_count = len(candidates)
                    if args.variant_limit_per_product > 0:
                        candidate_count = min(candidate_count, args.variant_limit_per_product)
                    category_plans.extend(
                        shard_product_variants(
                            product_url,
                            candidate_count,
                            max_requests_per_chunk,
                        )
                    )
                    logs.append(
                        f"planned_product_url={product_url} candidate_count={candidate_count} "
                        f"shard_count={math.ceil(candidate_count / max_requests_per_chunk) if candidate_count else 0}"
                    )
                    if candidate_count == 0:
                        errors.append(
                            error_row(
                                product_url,
                                "plan-variants",
                                "no_variant_candidates",
                                "product had 0 pending variant candidates",
                            )
                        )
                except Exception as exc:
                    code, detail = split_error(exc)
                    errors.append(error_row(product_url, "plan-variants", code, detail))
                    logs.append(f"failed_variant_plan_url={product_url} code={code} detail={detail}")
            category_chunks = pack_variant_plans(
                category,
                category_plans,
                args.chunk_size,
                max_requests_per_chunk,
                matrix_dir,
            )
            if args.chunk_slug:
                category_chunks = [chunk for chunk in category_chunks if chunk.chunk_slug == args.chunk_slug]
            chunks.extend(category_chunks)
        except Exception as exc:
            code, detail = split_error(exc)
            discovered_counts_by_category[category.slug] = 0
            selected_counts_by_category[category.slug] = 0
            discovered_rows.append(
                {
                    "run_id": run_id,
                    "category_name": category.name,
                    "category_url": category.url,
                    "product_url": "",
                    "discovery_status": "failed",
                    "discovery_error": code,
                }
            )
            errors.append(error_row(category.url, "discover-products", code, detail))
            logs.append(f"failed_category_slug={category.slug} code={code} detail={detail}")

    chunk_matrix = matrix_for_variant_chunks(chunks, args.request_interval)
    chunk_input_counts_by_category: dict[str, int] = {}
    for category in categories:
        chunk_input_counts_by_category[category.slug] = len(
            {
                plan.product_url
                for chunk in chunks
                if chunk.category_slug == category.slug
                for plan in chunk.product_plans
            }
        )
    product_limit_applied = args.product_limit_per_category > 0 or args.product_limit > 0
    filter_applied = bool(args.chunk_slug)
    category_completeness: dict[str, dict[str, object]] = {}
    for category in categories:
        category_rows = [row for row in discovered_rows if row.get("category_url") == category.url]
        discovered_urls = [row.get("product_url", "") for row in category_rows if row.get("product_url")]
        discovery_errors = [
            row.get("discovery_error", "")
            for row in category_rows
            if row.get("discovery_status") == "failed"
        ]
        unique_discovered_count = len(set(discovered_urls))
        chunk_input_count = chunk_input_counts_by_category.get(category.slug, 0)
        reasons: list[str] = []
        if product_limit_applied:
            reasons.append("product_limit_applied")
        if filter_applied:
            reasons.append("chunk_filter_applied")
        if discovery_errors:
            reasons.append("category_discovery_failed")
        if unique_discovered_count == 0:
            reasons.append("no_discovered_products")
        if not product_limit_applied and not filter_applied and unique_discovered_count != chunk_input_count:
            reasons.append(
                "discovered_vs_chunk_input_mismatch "
                f"discovered={unique_discovered_count} chunk_input={chunk_input_count}"
            )
        category_completeness[category.slug] = {
            "category_name": category.name,
            "category_url": category.url,
            "category_slug": category.slug,
            "discovered_product_count": len(discovered_urls),
            "unique_discovered_product_count": unique_discovered_count,
            "chunk_input_product_count": chunk_input_count,
            "processed_product_count": 0,
            "product_limit_per_category": args.product_limit_per_category,
            "product_limit": args.product_limit,
            "variant_limit_per_product": args.variant_limit_per_product,
            "limit_applied": product_limit_applied,
            "filter_applied": filter_applied,
            "discovery_complete_scope": "current_discovery_logic",
            "discovery_complete": not reasons,
            "pagination_summary": category_pagination_summaries.get(category.slug, {}),
            "reasons": reasons,
        }
    if sitemap_category_completeness:
        for slug, sitemap_entry in sitemap_category_completeness.items():
            base_entry = category_completeness.get(slug, {})
            merged_entry = dict(sitemap_entry)
            merged_entry["chunk_input_product_count"] = base_entry.get("chunk_input_product_count", 0)
            merged_entry["processed_product_count"] = 0
            merged_entry["product_limit_per_category"] = args.product_limit_per_category
            merged_entry["product_limit"] = args.product_limit
            merged_entry["variant_limit_per_product"] = args.variant_limit_per_product
            merged_entry["filter_applied"] = bool(args.chunk_slug)
            merged_entry["pagination_summary"] = base_entry.get("pagination_summary", {})
            category_completeness[slug] = merged_entry
    write_json(matrix_dir / "chunk_matrix.json", chunk_matrix)
    write_json(matrix_dir / "category_matrix.json", matrix_for_categories(categories))
    write_csv(matrix_dir / "discovered_product_urls.csv", DISCOVERED_COLUMNS, discovered_rows)
    write_csv(matrix_dir / "errors.csv", ERROR_COLUMNS, errors)
    (matrix_dir / "discover_products_log.txt").write_text("\n".join(logs) + "\n", encoding="utf-8")

    metadata = {
        "schema_version": "0.1.0",
        "parser_version": "0.1.0",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "run_profile": args.run_profile,
        "discovery_mode": args.discovery_mode,
        "sitemap_url": args.sitemap_url,
        "product_sitemap_url": sitemap_discovery_metadata.get("product_sitemap_url", args.product_sitemap_url),
        "sitemap_product_url_count": sitemap_discovery_metadata.get("sitemap_product_url_count", 0),
        "category_expected_counts": sitemap_discovery_metadata.get("category_expected_counts", {}),
        "phase3_discovery_metadata": sitemap_discovery_metadata,
        "product_limit_per_category": args.product_limit_per_category,
        "product_limit": args.product_limit,
        "variant_limit_per_product": args.variant_limit_per_product,
        "chunk_size": args.chunk_size,
        "variant_shard_target_minutes": args.variant_shard_target_minutes,
        "max_requests_per_chunk": variant_request_budget(
            args.request_interval,
            args.variant_shard_target_minutes,
        ),
        "category_slug_filter": args.category_slug,
        "chunk_slug_filter": args.chunk_slug,
        "target_categories": [
            {"category_name": category.name, "category_url": category.url, "category_slug": category.slug}
            for category in categories
        ],
        "discovered_product_counts_by_category": discovered_counts_by_category,
        "selected_product_counts_by_category": selected_counts_by_category,
        "chunk_input_product_counts_by_category": chunk_input_counts_by_category,
        "category_completeness": category_completeness,
        "zero_product_categories": [
            category.slug for category in categories if discovered_counts_by_category.get(category.slug, 0) == 0
        ],
        "chunk_count": len(chunks),
        "chunks": [
            {
                "category_name": chunk.category_name,
                "category_url": chunk.category_url,
                "category_slug": chunk.category_slug,
                "chunk_index": chunk.chunk_index,
                "chunk_slug": chunk.chunk_slug,
                "chunk_product_count": len({plan.product_url for plan in chunk.product_plans}),
                "product_plan_file": chunk.product_plan_file,
                "estimated_request_count": chunk.estimated_request_count,
            }
            for chunk in chunks
        ],
        "category_pagination_summaries": category_pagination_summaries,
        "error_count": len(errors),
        "run_status": "partial_success" if errors and chunks else "failed" if errors else "success",
    }
    write_json(matrix_dir / "run_metadata.json", metadata)
    return 0


def error_row(url: str, phase: str, code: str, message: str) -> dict[str, str]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "url": url,
        "phase": phase,
        "error_code": code,
        "message": message,
        "first_seen_at": now,
        "last_seen_at": now,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate BoExio Phase 3 GitHub Actions matrices.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    categories = subparsers.add_parser("categories")
    categories.add_argument("--targets", default="config/target_categories.csv")
    categories.add_argument("--output", default="matrix/category_matrix.json")
    categories.set_defaults(func=write_categories)

    validate = subparsers.add_parser("validate-chunk-matrix")
    validate.add_argument("--input", required=True)
    validate.set_defaults(func=validate_chunk_matrix_file)

    products = subparsers.add_parser("discover-products")
    products.add_argument("--targets", default="config/target_categories.csv")
    products.add_argument("--output-dir", default="matrix")
    products.add_argument("--timeout", type=int, default=30)
    products.add_argument("--run-id", default="")
    products.add_argument("--product-limit", type=int, default=0)
    products.add_argument("--product-limit-per-category", type=int, default=3)
    products.add_argument("--variant-limit-per-product", type=int, default=1)
    products.add_argument("--run-profile", default="")
    products.add_argument("--discovery-mode", choices=("category-html", "sitemap"), default="category-html")
    products.add_argument("--sitemap-url", default=SITEMAP_INDEX_URL)
    products.add_argument("--product-sitemap-url", default="")
    products.add_argument("--category-expected-counts-file", default="")
    products.add_argument("--classified-product-urls-file", default="")
    products.add_argument("--chunk-size", type=int, default=5)
    products.add_argument("--variant-shard-target-minutes", type=int, default=180)
    products.add_argument("--request-interval", type=float, default=5.0)
    products.add_argument("--retries", type=int, default=2)
    products.add_argument("--category-slug", default="")
    products.add_argument("--chunk-slug", default="")
    products.set_defaults(func=discover_products)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
