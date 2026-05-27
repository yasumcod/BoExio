from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from boexio.phase2_variants import ERROR_COLUMNS
from boexio.phase3_master import (
    CategoryTarget,
    RateLimiter,
    category_pagination_summary,
    collect_product_urls,
    fetch_with_control,
    read_target_categories,
    safe_raw_name,
    split_error,
    validate_input_url,
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


def discover_products(args: argparse.Namespace) -> int:
    started_at = datetime.now(timezone.utc)
    run_id = args.run_id or started_at.strftime("%Y%m%dT%H%M%SZ")
    matrix_dir = Path(args.output_dir)
    raw_dir = matrix_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    categories = read_target_categories(Path(args.targets))
    if args.category_slug:
        categories = [category for category in categories if category.slug == args.category_slug]
    limiter = RateLimiter(interval_seconds=args.request_interval)

    chunks: list[ProductChunk] = []
    discovered_rows: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    logs: list[str] = []
    discovered_counts_by_category: dict[str, int] = {}
    selected_counts_by_category: dict[str, int] = {}
    category_pagination_summaries: dict[str, dict[str, object]] = {}
    remaining_global = args.product_limit if args.product_limit > 0 else None

    for category_index, category in enumerate(categories, start=1):
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
        try:
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
            category_chunks = chunk_product_urls(category, limited_urls, args.chunk_size, matrix_dir)
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

    chunk_matrix = matrix_for_chunks(chunks)
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
        "product_limit_per_category": args.product_limit_per_category,
        "product_limit": args.product_limit,
        "chunk_size": args.chunk_size,
        "category_slug_filter": args.category_slug,
        "chunk_slug_filter": args.chunk_slug,
        "target_categories": [
            {"category_name": category.name, "category_url": category.url, "category_slug": category.slug}
            for category in categories
        ],
        "discovered_product_counts_by_category": discovered_counts_by_category,
        "selected_product_counts_by_category": selected_counts_by_category,
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
                "chunk_product_count": len(chunk.product_urls),
                "product_urls_file": chunk.product_urls_file,
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

    products = subparsers.add_parser("discover-products")
    products.add_argument("--targets", default="config/target_categories.csv")
    products.add_argument("--output-dir", default="matrix")
    products.add_argument("--timeout", type=int, default=30)
    products.add_argument("--run-id", default="")
    products.add_argument("--product-limit", type=int, default=0)
    products.add_argument("--product-limit-per-category", type=int, default=3)
    products.add_argument("--chunk-size", type=int, default=5)
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
