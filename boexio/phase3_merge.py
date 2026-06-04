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


def as_int(value: object, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def full_run_mode(discovery_metadata: dict) -> bool:
    return (
        as_int(discovery_metadata.get("product_limit"), 0) <= 0
        and as_int(discovery_metadata.get("product_limit_per_category"), 0) <= 0
        and as_int(discovery_metadata.get("variant_limit_per_product"), 1) <= 0
        and not discovery_metadata.get("chunk_slug_filter")
    )


def merge_product_variant_completeness(
    product_variant_completeness: dict[str, dict[str, object]],
    chunk_metadata: dict,
) -> None:
    chunk_products = chunk_metadata.get("product_variant_completeness", {})
    if not isinstance(chunk_products, dict):
        return
    for product_url, entry in chunk_products.items():
        if not isinstance(entry, dict):
            continue
        product_variant_completeness[str(product_url)] = dict(entry)


def aggregate_category_completeness(
    *,
    discovery_metadata: dict,
    expected: list[dict[str, object]],
    product_variant_completeness: dict[str, dict[str, object]],
    missing_chunks: list[str],
    failed_chunks: list[str],
) -> dict[str, dict[str, object]]:
    discovery_categories = discovery_metadata.get("category_completeness", {})
    if not isinstance(discovery_categories, dict):
        discovery_categories = {}

    category_info: dict[str, dict[str, object]] = {}
    for category in discovery_metadata.get("target_categories", []):
        if not isinstance(category, dict):
            continue
        slug = str(category.get("category_slug", ""))
        if not slug:
            continue
        category_info[slug] = {
            "category_name": category.get("category_name", ""),
            "category_url": category.get("category_url", ""),
            "category_slug": slug,
        }
    for chunk in expected:
        slug = str(chunk.get("category_slug", ""))
        if not slug:
            continue
        info = category_info.setdefault(slug, {"category_slug": slug})
        info.setdefault("category_name", chunk.get("category_name", ""))
        info.setdefault("category_url", chunk.get("category_url", ""))
    for slug, entry in discovery_categories.items():
        if not isinstance(entry, dict):
            continue
        info = category_info.setdefault(str(slug), {"category_slug": str(slug)})
        info.update(
            {
                "category_name": entry.get("category_name", info.get("category_name", "")),
                "category_url": entry.get("category_url", info.get("category_url", "")),
                "category_slug": entry.get("category_slug", slug),
            }
        )
    for entry in product_variant_completeness.values():
        slug = str(entry.get("category_slug", ""))
        if not slug:
            continue
        info = category_info.setdefault(slug, {"category_slug": slug})
        info.setdefault("category_name", entry.get("category_name", ""))
        info.setdefault("category_url", entry.get("category_url", ""))

    expected_chunks_by_category: dict[str, list[str]] = {}
    expected_products_by_category: dict[str, int] = {}
    for chunk in expected:
        slug = str(chunk.get("category_slug", ""))
        if not slug:
            continue
        expected_chunks_by_category.setdefault(slug, []).append(str(chunk.get("chunk_slug", "")))
        expected_products_by_category[slug] = expected_products_by_category.get(slug, 0) + as_int(
            chunk.get("chunk_product_count"), 0
        )

    missing_by_category: dict[str, list[str]] = {}
    failed_by_category: dict[str, list[str]] = {}
    expected_by_slug = {str(chunk.get("chunk_slug", "")): chunk for chunk in expected if chunk.get("chunk_slug")}
    for chunk_slug in missing_chunks:
        chunk = expected_by_slug.get(chunk_slug, {})
        category_slug = str(chunk.get("category_slug", ""))
        if category_slug:
            missing_by_category.setdefault(category_slug, []).append(chunk_slug)
    for chunk_slug in failed_chunks:
        chunk = expected_by_slug.get(chunk_slug, {})
        category_slug = str(chunk.get("category_slug", ""))
        if not category_slug:
            for product_entry in product_variant_completeness.values():
                if product_entry.get("chunk_slug") == chunk_slug:
                    category_slug = str(product_entry.get("category_slug", ""))
                    break
        if category_slug:
            failed_by_category.setdefault(category_slug, []).append(chunk_slug)

    processed_by_category: dict[str, set[str]] = {}
    variant_sums: dict[str, dict[str, int]] = {}
    product_fetch_incomplete_by_category: dict[str, int] = {}
    comparison_incomplete_by_category: dict[str, int] = {}
    for product_url, entry in product_variant_completeness.items():
        slug = str(entry.get("category_slug", ""))
        if not slug:
            continue
        if as_int(entry.get("product_fetch_attempt_count"), 0) > 0:
            processed_by_category.setdefault(slug, set()).add(product_url)
        sums = variant_sums.setdefault(
            slug,
            {
                "variant_candidate_count": 0,
                "variant_fetch_attempt_count": 0,
                "variant_success_count": 0,
                "variant_failure_count": 0,
                "variant_skipped_count": 0,
            },
        )
        for key in sums:
            sums[key] += as_int(entry.get(key), 0)
        if not entry.get("fetch_attempt_complete"):
            product_fetch_incomplete_by_category[slug] = product_fetch_incomplete_by_category.get(slug, 0) + 1
        elif not entry.get("comparison_complete"):
            comparison_incomplete_by_category[slug] = comparison_incomplete_by_category.get(slug, 0) + 1

    aggregate: dict[str, dict[str, object]] = {}
    product_limit_applied = (
        as_int(discovery_metadata.get("product_limit"), 0) > 0
        or as_int(discovery_metadata.get("product_limit_per_category"), 0) > 0
    )
    variant_limit_applied = as_int(discovery_metadata.get("variant_limit_per_product"), 1) > 0
    filter_applied = bool(discovery_metadata.get("chunk_slug_filter"))
    for slug in sorted(category_info):
        base = discovery_categories.get(slug, {}) if isinstance(discovery_categories.get(slug, {}), dict) else {}
        info = category_info[slug]
        chunk_input_count = expected_products_by_category.get(slug, as_int(base.get("chunk_input_product_count"), 0))
        processed_count = len(processed_by_category.get(slug, set()))
        sums = variant_sums.get(
            slug,
            {
                "variant_candidate_count": 0,
                "variant_fetch_attempt_count": 0,
                "variant_success_count": 0,
                "variant_failure_count": 0,
                "variant_skipped_count": 0,
            },
        )
        category_missing_chunks = sorted(missing_by_category.get(slug, []))
        category_failed_chunks = sorted(failed_by_category.get(slug, []))
        reasons: list[str] = []
        base_reasons = base.get("reasons", [])
        if isinstance(base_reasons, list):
            reasons.extend(str(reason) for reason in base_reasons)
        if category_missing_chunks:
            reasons.append(f"missing_chunks={','.join(category_missing_chunks)}")
        if category_failed_chunks:
            reasons.append(f"failed_chunks={','.join(category_failed_chunks)}")
        if chunk_input_count != processed_count:
            reasons.append(
                f"chunk_input_vs_processed_mismatch chunk_input={chunk_input_count} processed={processed_count}"
            )
        if product_fetch_incomplete_by_category.get(slug, 0):
            reasons.append(f"fetch_incomplete_products={product_fetch_incomplete_by_category[slug]}")
        if comparison_incomplete_by_category.get(slug, 0):
            reasons.append(f"comparison_incomplete_products={comparison_incomplete_by_category[slug]}")

        discovery_complete = bool(base.get("discovery_complete", False))
        if product_limit_applied or filter_applied:
            discovery_complete = False
        fetch_attempt_complete = (
            discovery_complete
            and not category_missing_chunks
            and not category_failed_chunks
            and chunk_input_count == processed_count
            and product_fetch_incomplete_by_category.get(slug, 0) == 0
            and not variant_limit_applied
        )
        comparison_complete = (
            fetch_attempt_complete
            and comparison_incomplete_by_category.get(slug, 0) == 0
            and sums.get("variant_failure_count", 0) == 0
            and sums.get("variant_success_count", 0) == sums.get("variant_candidate_count", 0)
            and sums.get("variant_candidate_count", 0) > 0
        )
        aggregate[slug] = {
            "category_name": info.get("category_name", ""),
            "category_url": info.get("category_url", ""),
            "category_slug": slug,
            "discovered_product_count": as_int(base.get("discovered_product_count"), 0),
            "unique_discovered_product_count": as_int(base.get("unique_discovered_product_count"), 0),
            "chunk_input_product_count": chunk_input_count,
            "processed_product_count": processed_count,
            **sums,
            "missing_chunks": category_missing_chunks,
            "failed_chunks": category_failed_chunks,
            "product_limit_applied": product_limit_applied,
            "variant_limit_applied": variant_limit_applied,
            "filter_applied": filter_applied,
            "discovery_complete_scope": base.get("discovery_complete_scope", "current_discovery_logic"),
            "discovery_complete": discovery_complete,
            "fetch_attempt_complete": fetch_attempt_complete,
            "comparison_complete": comparison_complete,
            "reasons": reasons,
        }
    return aggregate


def strict_status_from_completeness(category_completeness: dict[str, dict[str, object]]) -> tuple[str, list[str]]:
    incomplete_discovery = [
        slug for slug, entry in category_completeness.items() if not entry.get("discovery_complete")
    ]
    incomplete_fetch = [
        slug for slug, entry in category_completeness.items() if not entry.get("fetch_attempt_complete")
    ]
    incomplete_comparison = [
        slug for slug, entry in category_completeness.items() if not entry.get("comparison_complete")
    ]
    reasons: list[str] = []
    if incomplete_discovery:
        reasons.append(f"discovery_complete=false categories={','.join(incomplete_discovery)}")
    if incomplete_fetch:
        reasons.append(f"fetch_attempt_complete=false categories={','.join(incomplete_fetch)}")
    if incomplete_discovery or incomplete_fetch:
        return "failed", reasons
    if incomplete_comparison:
        reasons.append(f"comparison_complete=false categories={','.join(incomplete_comparison)}")
        return "partial_success", reasons
    return "success", reasons


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
    partial_chunks: list[str] = []
    product_variant_completeness: dict[str, dict[str, object]] = {}

    for directory in chunk_dirs(Path(args.chunks_dir)):
        metadata = read_json(directory / "run_metadata.json")
        chunk_slug = chunk_slug_from_metadata(metadata, directory)
        present_chunk_slugs.add(chunk_slug)
        chunk_status = str(metadata.get("run_status") or "missing")
        if chunk_status == "partial_success":
            partial_chunks.append(chunk_slug)
        elif chunk_status != "success":
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

        chunk_candidate_rows = read_csv_rows(directory / "variant_candidates.csv")
        chunk_discovered_rows = read_csv_rows(directory / "discovered_product_urls.csv")
        chunk_error_rows = read_csv_rows(directory / "errors.csv")
        candidate_rows.extend(chunk_candidate_rows)
        discovered_rows.extend(chunk_discovered_rows)
        merged_errors.extend(chunk_error_rows)
        merge_product_variant_completeness(product_variant_completeness, metadata)
        chunk_counts[chunk_slug] = {
            "category_slug": metadata.get("category_slug", ""),
            "category_name": metadata.get("category_name", ""),
            "chunk_index": metadata.get("chunk_index", 0),
            "chunk_product_count": metadata.get("chunk_product_count", 0),
            "run_status": chunk_status,
            "input_product_rows": len(chunk_product_rows),
            "accepted_product_rows": accepted_count,
            "duplicate_rows": duplicate_count,
            "error_count": len(chunk_error_rows),
            "variant_candidate_count": metadata.get("variant_candidate_count", len(chunk_candidate_rows)),
            "variant_fetch_attempt_count": metadata.get("variant_fetch_attempt_count", 0),
            "variant_success_count": metadata.get("variant_success_count", 0),
            "variant_failure_count": metadata.get("variant_failure_count", 0),
            "variant_skipped_count": metadata.get("variant_skipped_count", 0),
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

    for chunk_slug in missing_chunks:
        chunk = expected_by_slug.get(chunk_slug, {})
        merged_errors.append(
            error_row(
                str(chunk.get("category_url") or chunk_slug),
                "missing_chunk_artifact",
                "category_slug="
                f"{chunk.get('category_slug', '')} chunk_slug={chunk_slug} "
                f"expected_product_count={chunk.get('chunk_product_count', 0)}",
            )
        )

    category_completeness = aggregate_category_completeness(
        discovery_metadata=discovery_metadata,
        expected=expected,
        product_variant_completeness=product_variant_completeness,
        missing_chunks=missing_chunks,
        failed_chunks=sorted(set(failed_chunks)),
    )
    full_run = full_run_mode(discovery_metadata)
    run_status_reasons: list[str] = []
    if full_run:
        overall_status, run_status_reasons = strict_status_from_completeness(category_completeness)
        if missing_categories:
            overall_status = "failed"
            run_status_reasons.append(f"missing_categories={','.join(missing_categories)}")
        if missing_chunks:
            overall_status = "failed"
            run_status_reasons.append(f"missing_chunks={','.join(missing_chunks)}")
        if failed_chunks:
            overall_status = "failed"
            run_status_reasons.append(f"failed_chunks={','.join(sorted(set(failed_chunks)))}")
        if overall_status == "success" and (partial_chunks or merged_errors):
            overall_status = "partial_success"
            if partial_chunks:
                run_status_reasons.append(f"partial_chunks={','.join(sorted(set(partial_chunks)))}")
            if merged_errors:
                run_status_reasons.append(f"error_count={len(merged_errors)}")
    elif missing_categories or missing_chunks:
        overall_status = "failed"
        if missing_categories:
            run_status_reasons.append(f"missing_categories={','.join(missing_categories)}")
        if missing_chunks:
            run_status_reasons.append(f"missing_chunks={','.join(missing_chunks)}")
    elif failed_chunks or partial_chunks or merged_errors:
        overall_status = "partial_success"
        if failed_chunks:
            run_status_reasons.append(f"failed_chunks={','.join(sorted(set(failed_chunks)))}")
        if partial_chunks:
            run_status_reasons.append(f"partial_chunks={','.join(sorted(set(partial_chunks)))}")
        if merged_errors:
            run_status_reasons.append(f"error_count={len(merged_errors)}")
    else:
        overall_status = "success"

    if full_run:
        for slug, entry in category_completeness.items():
            category_url = str(entry.get("category_url") or slug)
            if not entry.get("discovery_complete"):
                merged_errors.append(
                    error_row(
                        category_url,
                        "incomplete_product_discovery",
                        f"category_slug={slug} reasons={'; '.join(str(reason) for reason in entry.get('reasons', []))}",
                    )
                )
            if not entry.get("fetch_attempt_complete"):
                merged_errors.append(
                    error_row(
                        category_url,
                        "incomplete_variant_fetch",
                        f"category_slug={slug} candidate={entry.get('variant_candidate_count', 0)} "
                        f"attempt={entry.get('variant_fetch_attempt_count', 0)} "
                        f"skipped={entry.get('variant_skipped_count', 0)}",
                    )
                )
            elif not entry.get("comparison_complete"):
                merged_errors.append(
                    error_row(
                        category_url,
                        "comparison_incomplete",
                        f"category_slug={slug} candidate={entry.get('variant_candidate_count', 0)} "
                        f"success={entry.get('variant_success_count', 0)} "
                        f"failure={entry.get('variant_failure_count', 0)}",
                    )
                )

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
    comparison_incomplete_categories = sorted(
        slug for slug, entry in category_completeness.items() if not entry.get("comparison_complete")
    )
    fetch_incomplete_categories = sorted(
        slug for slug, entry in category_completeness.items() if not entry.get("fetch_attempt_complete")
    )
    discovery_incomplete_categories = sorted(
        slug for slug, entry in category_completeness.items() if not entry.get("discovery_complete")
    )
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
        "category_completeness": category_completeness,
        "product_variant_completeness": product_variant_completeness,
        "discovery_incomplete_categories": discovery_incomplete_categories,
        "fetch_incomplete_categories": fetch_incomplete_categories,
        "comparison_incomplete_categories": comparison_incomplete_categories,
        "missing_categories": missing_categories,
        "missing_chunks": missing_chunks,
        "failed_chunks": sorted(set(failed_chunks)),
        "partial_chunks": sorted(set(partial_chunks)),
        "duplicate_error_count": sum(
            1
            for row in merged_errors
            if row.get("error_code") in {"duplicate_variant_key", "duplicate_source_url"}
        ),
        "error_count": len(merged_errors),
        "full_run_completeness_gate": full_run,
        "run_status_reasons": run_status_reasons,
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
