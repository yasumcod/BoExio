from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from boexio.phase1_poc import SCHEMA_VERSION, collect_output_files, commit_sha, relative_output_path, sha256_file
from boexio.phase2_variants import CANDIDATE_COLUMNS, ERROR_COLUMNS, PHASE2_CSV_COLUMNS
from boexio.phase3_matrix import DISCOVERED_COLUMNS
from boexio.phase3_master import PHASE3_PARSER_VERSION


def read_json(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def chunk_dirs(root: Path) -> list[Path]:
    candidates = [path for path in root.rglob("run_metadata.json") if path.is_file()]
    return sorted({path.parent for path in candidates})


def error_row(url: str, code: str, message: str) -> dict[str, str]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "url": url,
        "phase": "merge",
        "error_code": code,
        "message": message,
        "first_seen_at": now,
        "last_seen_at": now,
    }


def chunk_slug_from_metadata(metadata: dict, directory: Path) -> str:
    return str(metadata.get("chunk_slug") or directory.name)


def expected_chunks(matrix: dict) -> list[dict[str, object]]:
    include = matrix.get("include", [])
    return include if isinstance(include, list) else []


def count_by(rows: Iterable[dict[str, str]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key, "")
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def checksum_files(paths: list[Path]) -> dict[str, str]:
    return {relative_output_path(path): sha256_file(path) for path in paths if path.exists()}


def merge_chunks(args: argparse.Namespace) -> int:
    started_at = datetime.now(timezone.utc)
    run_id = args.run_id or started_at.strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir) / "runs" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    matrix = read_json(Path(args.matrix_json)) if args.matrix_json else {"include": []}
    discovery_metadata = read_json(Path(args.discovery_metadata)) if args.discovery_metadata else {}
    expected = expected_chunks(matrix)
    expected_by_slug = {str(chunk.get("chunk_slug", "")): chunk for chunk in expected if chunk.get("chunk_slug")}

    product_rows: list[dict[str, str]] = []
    candidate_rows: list[dict[str, str]] = []
    discovered_rows: list[dict[str, str]] = []
    merged_errors: list[dict[str, str]] = []
    logs: list[str] = []
    seen_variant_keys: set[str] = set()
    seen_source_urls: set[str] = set()
    chunk_counts: dict[str, dict[str, object]] = {}
    present_chunk_slugs: set[str] = set()
    failed_chunks: list[str] = []

    for directory in chunk_dirs(Path(args.chunks_dir)):
        metadata = read_json(directory / "run_metadata.json")
        chunk_slug = chunk_slug_from_metadata(metadata, directory)
        present_chunk_slugs.add(chunk_slug)
        chunk_status = str(metadata.get("run_status") or "missing")
        if chunk_status != "success":
            failed_chunks.append(chunk_slug)

        chunk_product_rows = read_csv_rows(directory / "products_current.csv")
        accepted_count = 0
        duplicate_count = 0
        for row in chunk_product_rows:
            variant_key = row.get("variant_key", "")
            source_url = row.get("source_url", "")
            duplicate = False
            if variant_key and variant_key in seen_variant_keys:
                duplicate = True
                duplicate_count += 1
                merged_errors.append(
                    error_row(source_url, "duplicate_variant_key", f"duplicate variant_key={variant_key} in {chunk_slug}")
                )
            if source_url and source_url in seen_source_urls:
                duplicate = True
                duplicate_count += 1
                merged_errors.append(
                    error_row(source_url, "duplicate_source_url", f"duplicate source_url={source_url} in {chunk_slug}")
                )
            if duplicate:
                continue
            if variant_key:
                seen_variant_keys.add(variant_key)
            if source_url:
                seen_source_urls.add(source_url)
            product_rows.append({column: row.get(column, "") for column in PHASE2_CSV_COLUMNS})
            accepted_count += 1

        candidate_rows.extend(read_csv_rows(directory / "variant_candidates.csv"))
        discovered_rows.extend(read_csv_rows(directory / "discovered_product_urls.csv"))
        merged_errors.extend(read_csv_rows(directory / "errors.csv"))
        chunk_counts[chunk_slug] = {
            "category_slug": metadata.get("category_slug", ""),
            "category_name": metadata.get("category_name", ""),
            "chunk_index": metadata.get("chunk_index", 0),
            "chunk_product_count": metadata.get("chunk_product_count", 0),
            "run_status": chunk_status,
            "input_product_rows": len(chunk_product_rows),
            "accepted_product_rows": accepted_count,
            "duplicate_rows": duplicate_count,
            "error_count": len(read_csv_rows(directory / "errors.csv")),
        }
        logs.append(
            f"chunk_slug={chunk_slug} run_status={chunk_status} "
            f"input_rows={len(chunk_product_rows)} accepted_rows={accepted_count}"
        )

    missing_chunks = sorted(set(expected_by_slug) - present_chunk_slugs)
    if discovery_metadata.get("category_slug_filter") or discovery_metadata.get("chunk_slug_filter"):
        expected_categories = {
            str(chunk.get("category_slug", "")) for chunk in expected if chunk.get("category_slug")
        }
    else:
        expected_categories = {
            str(category.get("category_slug", ""))
            for category in discovery_metadata.get("target_categories", [])
            if category.get("category_slug")
        }
    categories_with_selected_products = {
        str(chunk.get("category_slug", ""))
        for chunk in expected
        if chunk.get("category_slug") and int(chunk.get("chunk_product_count") or 0) > 0
    }
    zero_product_categories = set(discovery_metadata.get("zero_product_categories", []))
    missing_categories = sorted((expected_categories - categories_with_selected_products) | zero_product_categories)

    if missing_categories or missing_chunks:
        overall_status = "failed"
    elif failed_chunks or merged_errors:
        overall_status = "partial_success"
    else:
        overall_status = "success"

    current_path = output_dir / "products_current.csv"
    snapshot_path = output_dir / f"products_{started_at.strftime('%Y-%m-%d')}_{run_id}.csv"
    candidates_path = output_dir / "variant_candidates.csv"
    discovered_path = output_dir / "discovered_product_urls.csv"
    errors_path = output_dir / "errors.csv"
    log_path = output_dir / "scrape_log.txt"
    metadata_path = output_dir / "run_metadata.json"

    write_csv(current_path, PHASE2_CSV_COLUMNS, product_rows)
    write_csv(snapshot_path, PHASE2_CSV_COLUMNS, product_rows)
    write_csv(candidates_path, CANDIDATE_COLUMNS, candidate_rows)
    write_csv(discovered_path, DISCOVERED_COLUMNS, discovered_rows)
    write_csv(errors_path, ERROR_COLUMNS, merged_errors)
    log_path.write_text("\n".join(logs) + "\n", encoding="utf-8")

    checksum_targets = [current_path, snapshot_path, candidates_path, discovered_path, errors_path, log_path]
    output_files = [*checksum_targets, metadata_path]
    category_counts = count_by(product_rows, "category_name")
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PHASE3_PARSER_VERSION,
        "merge_parser_version": "0.1.0",
        "commit_sha": commit_sha(),
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "source_chunk_count": len(present_chunk_slugs),
        "expected_chunk_count": len(expected_by_slug),
        "category_product_row_counts": category_counts,
        "chunk_product_row_counts": chunk_counts,
        "missing_categories": missing_categories,
        "missing_chunks": missing_chunks,
        "failed_chunks": sorted(set(failed_chunks)),
        "duplicate_error_count": sum(
            1
            for row in merged_errors
            if row.get("error_code") in {"duplicate_variant_key", "duplicate_source_url"}
        ),
        "error_count": len(merged_errors),
        "output_files": [relative_output_path(path) for path in output_files],
        "output_file_checksums": checksum_files(checksum_targets),
        "run_status": overall_status,
        "overall_run_status": overall_status,
        "notes": [
            "Phase 3 aggregate output is built from product chunk artifacts.",
            "products_current.csv uses variant_key as the primary duplicate key; first row wins.",
            "Duplicate source_url rows are also recorded in errors.csv; first row wins.",
            "Missing required categories or missing expected chunks mark the aggregate run as failed.",
            "Failed chunk metadata with generated artifacts marks the aggregate run as partial_success.",
        ],
    }
    write_json(metadata_path, metadata)
    return 1 if overall_status == "failed" else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge BoExio Phase 3 product chunk artifacts.")
    parser.add_argument("--chunks-dir", required=True)
    parser.add_argument("--matrix-json", default="")
    parser.add_argument("--discovery-metadata", default="")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--run-id", default="")
    return parser


def main() -> int:
    return merge_chunks(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
