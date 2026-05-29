from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from boexio.phase1_poc import commit_sha, relative_output_path, sha256_file
from boexio.phase2_variants import ERROR_COLUMNS, PHASE2_CSV_COLUMNS, write_errors_csv


PHASE4_PARSER_VERSION = "0.4.0"
DIFF_SCHEMA_VERSION = "0.1.0"
DISCONTINUED_AFTER_MISSING_STREAK = 4
BACKWARD_COMPATIBLE_PHASE2_COLUMNS = {"category_name", "category_url", "run_id"}

PRICE_CHANGE_COLUMNS = [
    "run_id",
    "variant_key",
    "product_name",
    "item_number",
    "selected_size",
    "selected_upholstery",
    "selected_leg",
    "previous_price",
    "current_price",
    "price_delta",
    "price_change_rate",
    "change_direction",
    "previous_url",
    "current_url",
    "previous_checked_at",
    "current_checked_at",
    "currency",
    "tax_type",
    "price_compare_from",
]
ADDED_COLUMNS = [
    "run_id",
    "variant_key",
    "product_name",
    "item_number",
    "selected_size",
    "selected_upholstery",
    "selected_leg",
    "current_price",
    "current_state",
    "revived_at",
    "revived_price",
    "source_url",
    "source_checked_at",
]
REMOVED_COLUMNS = [
    "run_id",
    "variant_key",
    "product_name",
    "item_number",
    "selected_size",
    "selected_upholstery",
    "selected_leg",
    "previous_price",
    "current_state",
    "missing_streak",
    "first_missing_at",
    "discontinued_at",
    "missing_streak_at_discontinue",
    "revived_at",
    "revived_price",
    "source_url",
    "source_checked_at",
]


@dataclass(frozen=True)
class DiffInputs:
    previous_csv: Path
    current_csv: Path
    previous_metadata: Path | None
    current_metadata: Path | None


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def read_metadata(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def schema_version(metadata: dict) -> str:
    return str(metadata.get("schema_version", ""))


def ensure_schema_compatible(previous_metadata: dict, current_metadata: dict) -> tuple[bool, str]:
    previous_schema = schema_version(previous_metadata)
    current_schema = schema_version(current_metadata)
    if not previous_schema or not current_schema:
        return True, "schema metadata missing; CSV columns will be validated instead"
    if previous_schema != current_schema:
        return False, f"schema_version mismatch: previous={previous_schema} current={current_schema}"
    return True, ""


def validate_columns(rows: list[dict[str, str]], path: Path) -> list[str]:
    if not rows:
        return []
    required_columns = [
        column for column in PHASE2_CSV_COLUMNS if column not in BACKWARD_COMPATIBLE_PHASE2_COLUMNS
    ]
    missing = [column for column in required_columns if column not in rows[0]]
    return [f"{path}: missing column {column}" for column in missing]


def error_row(url: str, code: str, message: str, when: str) -> dict[str, str]:
    return {
        "url": url,
        "phase": "diff",
        "error_code": code,
        "message": message,
        "first_seen_at": when,
        "last_seen_at": when,
    }


def group_by_variant_key(rows: list[dict[str, str]], run_at: str) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    grouped: dict[str, dict[str, str]] = {}
    errors: list[dict[str, str]] = []
    for row in rows:
        key = row.get("variant_key", "").strip()
        url = row.get("source_url", "")
        checked_at = row.get("source_checked_at") or run_at
        if row.get("scrape_status") != "success":
            errors.append(
                error_row(
                    url,
                    row.get("scrape_error_code") or "source_row_not_success",
                    row.get("scrape_error_message") or "source row is not successful",
                    checked_at,
                )
            )
            continue
        if not key:
            errors.append(error_row(url, "missing_variant_key", "variant_key is required for diff", checked_at))
            continue
        if key in grouped:
            errors.append(error_row(url, "duplicate_variant_key", f"duplicate variant_key: {key}", checked_at))
            continue
        grouped[key] = row
    return grouped, errors


def decimal_value(value: str) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def comparable_error(previous: dict[str, str], current: dict[str, str]) -> tuple[str, str]:
    for row_name, row in (("previous", previous), ("current", current)):
        if not row.get("price_compare_value", "").strip():
            return "missing_comparable_price", f"{row_name} price_compare_value is missing"
        if decimal_value(row.get("price_compare_value", "")) is None:
            return "price_parse_error", f"{row_name} price_compare_value is not numeric"
    for column, code in (
        ("currency", "currency_mismatch"),
        ("tax_type", "tax_type_mismatch"),
        ("price_compare_from", "price_source_mismatch"),
    ):
        previous_value = previous.get(column, "")
        current_value = current.get(column, "")
        if previous_value != current_value:
            return code, f"{column} differs: previous={previous_value} current={current_value}"
    return "", ""


def price_change_row(run_id: str, previous: dict[str, str], current: dict[str, str]) -> dict[str, str]:
    previous_price = decimal_value(previous["price_compare_value"]) or Decimal(0)
    current_price = decimal_value(current["price_compare_value"]) or Decimal(0)
    delta = current_price - previous_price
    rate = Decimal(0) if previous_price == 0 else delta / previous_price
    direction = "increase" if delta > 0 else "decrease" if delta < 0 else "unchanged"
    return {
        "run_id": run_id,
        "variant_key": current.get("variant_key", ""),
        "product_name": current.get("product_name") or previous.get("product_name", ""),
        "item_number": current.get("item_number") or previous.get("item_number", ""),
        "selected_size": current.get("selected_size") or previous.get("selected_size", ""),
        "selected_upholstery": current.get("selected_upholstery") or previous.get("selected_upholstery", ""),
        "selected_leg": current.get("selected_leg") or previous.get("selected_leg", ""),
        "previous_price": str(previous_price),
        "current_price": str(current_price),
        "price_delta": str(delta),
        "price_change_rate": f"{rate:.6f}",
        "change_direction": direction,
        "previous_url": previous.get("source_url", ""),
        "current_url": current.get("source_url", ""),
        "previous_checked_at": previous.get("source_checked_at", ""),
        "current_checked_at": current.get("source_checked_at", ""),
        "currency": current.get("currency", ""),
        "tax_type": current.get("tax_type", ""),
        "price_compare_from": current.get("price_compare_from", ""),
    }


def added_row(run_id: str, current: dict[str, str], previous_state: dict[str, str] | None = None) -> dict[str, str]:
    was_discontinued = previous_state and previous_state.get("current_state") == "discontinued"
    return {
        "run_id": run_id,
        "variant_key": current.get("variant_key", ""),
        "product_name": current.get("product_name", ""),
        "item_number": current.get("item_number", ""),
        "selected_size": current.get("selected_size", ""),
        "selected_upholstery": current.get("selected_upholstery", ""),
        "selected_leg": current.get("selected_leg", ""),
        "current_price": current.get("price_compare_value", ""),
        "current_state": "revived" if was_discontinued else "new",
        "revived_at": current.get("source_checked_at", "") if was_discontinued else "",
        "revived_price": current.get("price_compare_value", "") if was_discontinued else "",
        "source_url": current.get("source_url", ""),
        "source_checked_at": current.get("source_checked_at", ""),
    }


def integer_value(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def removed_row(run_id: str, previous: dict[str, str], run_at: str) -> dict[str, str]:
    previous_streak = integer_value(previous.get("missing_streak", ""), 0)
    missing_streak = previous_streak + 1
    current_state = "discontinued" if missing_streak >= DISCONTINUED_AFTER_MISSING_STREAK else "missing_candidate"
    first_missing_at = previous.get("first_missing_at") or run_at
    discontinued_at = previous.get("discontinued_at") or (run_at if current_state == "discontinued" else "")
    missing_streak_at_discontinue = (
        previous.get("missing_streak_at_discontinue")
        or (str(missing_streak) if current_state == "discontinued" else "")
    )
    return {
        "run_id": run_id,
        "variant_key": previous.get("variant_key", ""),
        "product_name": previous.get("product_name", ""),
        "item_number": previous.get("item_number", ""),
        "selected_size": previous.get("selected_size", ""),
        "selected_upholstery": previous.get("selected_upholstery", ""),
        "selected_leg": previous.get("selected_leg", ""),
        "previous_price": previous.get("price_compare_value", ""),
        "current_state": current_state,
        "missing_streak": str(missing_streak),
        "first_missing_at": first_missing_at,
        "discontinued_at": discontinued_at,
        "missing_streak_at_discontinue": missing_streak_at_discontinue,
        "revived_at": "",
        "revived_price": "",
        "source_url": previous.get("source_url", ""),
        "source_checked_at": previous.get("source_checked_at", ""),
    }


def find_previous_state_for_added(key: str, previous_rows: list[dict[str, str]]) -> dict[str, str] | None:
    for row in previous_rows:
        if row.get("variant_key") == key and row.get("current_state") == "discontinued":
            return row
    return None


def diff_rows(
    run_id: str,
    previous_rows: list[dict[str, str]],
    current_rows: list[dict[str, str]],
    run_at: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    previous_by_key, previous_errors = group_by_variant_key(previous_rows, run_at)
    current_by_key, current_errors = group_by_variant_key(current_rows, run_at)
    errors = [*previous_errors, *current_errors]

    price_changes: list[dict[str, str]] = []
    added: list[dict[str, str]] = []
    removed: list[dict[str, str]] = []

    previous_keys = set(previous_by_key)
    current_keys = set(current_by_key)
    for key in sorted(previous_keys & current_keys):
        previous = previous_by_key[key]
        current = current_by_key[key]
        if previous.get("current_state") == "discontinued":
            added.append(added_row(run_id, current, previous))
            continue
        code, message = comparable_error(previous, current)
        if code:
            errors.append(error_row(current.get("source_url", ""), code, message, current.get("source_checked_at") or run_at))
            continue
        previous_price = decimal_value(previous["price_compare_value"])
        current_price = decimal_value(current["price_compare_value"])
        if previous_price != current_price:
            price_changes.append(price_change_row(run_id, previous, current))

    for key in sorted(current_keys - previous_keys):
        added.append(added_row(run_id, current_by_key[key], find_previous_state_for_added(key, previous_rows)))

    for key in sorted(previous_keys - current_keys):
        removed.append(removed_row(run_id, previous_by_key[key], run_at))

    return price_changes, added, removed, errors


def checksum_files(paths: list[Path]) -> dict[str, str]:
    return {relative_output_path(path): sha256_file(path) for path in paths}


def default_metadata_path(csv_path: Path) -> Path | None:
    candidate = csv_path.parent / "run_metadata.json"
    return candidate if candidate.exists() else None


def resolve_inputs(args: argparse.Namespace) -> DiffInputs:
    previous_csv = Path(args.previous_csv)
    current_csv = Path(args.current_csv)
    previous_metadata = Path(args.previous_metadata) if args.previous_metadata else default_metadata_path(previous_csv)
    current_metadata = Path(args.current_metadata) if args.current_metadata else default_metadata_path(current_csv)
    return DiffInputs(previous_csv, current_csv, previous_metadata, current_metadata)


def run(args: argparse.Namespace) -> int:
    started_at = datetime.now(timezone.utc)
    run_id = args.run_id or started_at.strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir) / "runs" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = resolve_inputs(args)

    previous_metadata = read_metadata(inputs.previous_metadata)
    current_metadata = read_metadata(inputs.current_metadata)
    schema_ok, schema_note = ensure_schema_compatible(previous_metadata, current_metadata)
    previous_rows = read_csv_rows(inputs.previous_csv)
    current_rows = read_csv_rows(inputs.current_csv)
    validation_errors = [*validate_columns(previous_rows, inputs.previous_csv), *validate_columns(current_rows, inputs.current_csv)]

    run_at = started_at.isoformat()
    price_changes: list[dict[str, str]] = []
    added: list[dict[str, str]] = []
    removed: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    if not schema_ok:
        errors.append(error_row(str(inputs.current_csv), "schema_version_mismatch", schema_note, run_at))
    for message in validation_errors:
        errors.append(error_row(str(inputs.current_csv), "schema_mismatch", message, run_at))
    if schema_ok and not validation_errors:
        price_changes, added, removed, errors = diff_rows(run_id, previous_rows, current_rows, run_at)

    date_prefix = started_at.strftime("%Y-%m-%d")
    price_changes_path = output_dir / f"price_changes_{date_prefix}_{run_id}.csv"
    added_path = output_dir / f"new_items_{date_prefix}_{run_id}.csv"
    removed_path = output_dir / f"removed_items_{date_prefix}_{run_id}.csv"
    errors_path = output_dir / "errors.csv"
    summary_path = output_dir / "diff_summary.json"
    metadata_path = output_dir / "run_metadata.json"

    write_csv(price_changes_path, PRICE_CHANGE_COLUMNS, price_changes)
    write_csv(added_path, ADDED_COLUMNS, added)
    write_csv(removed_path, REMOVED_COLUMNS, removed)
    write_errors_csv(errors_path, errors)

    increase_count = sum(1 for row in price_changes if row.get("change_direction") == "increase")
    decrease_count = sum(1 for row in price_changes if row.get("change_direction") == "decrease")
    error_counts: dict[str, int] = {}
    for row in errors:
        code = row.get("error_code", "")
        error_counts[code] = error_counts.get(code, 0) + 1
    summary = {
        "run_id": run_id,
        "previous_csv": str(inputs.previous_csv),
        "current_csv": str(inputs.current_csv),
        "previous_row_count": len(previous_rows),
        "current_row_count": len(current_rows),
        "price_change_count": len(price_changes),
        "increase_count": increase_count,
        "decrease_count": decrease_count,
        "added_count": len([row for row in added if row.get("current_state") == "new"]),
        "removed_count": len(removed),
        "revived_count": len([row for row in added if row.get("current_state") == "revived"]),
        "currency_mismatch_count": error_counts.get("currency_mismatch", 0),
        "comparison_error_count": len(errors),
        "error_counts": dict(sorted(error_counts.items())),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    run_status = "failed" if not schema_ok or validation_errors else "success"
    checksum_targets = [price_changes_path, added_path, removed_path, errors_path, summary_path]
    output_files = [*checksum_targets, metadata_path]
    metadata = {
        "schema_version": DIFF_SCHEMA_VERSION,
        "parser_version": PHASE4_PARSER_VERSION,
        "commit_sha": commit_sha(),
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "previous_csv": str(inputs.previous_csv),
        "current_csv": str(inputs.current_csv),
        "previous_metadata": str(inputs.previous_metadata) if inputs.previous_metadata else "",
        "current_metadata": str(inputs.current_metadata) if inputs.current_metadata else "",
        "previous_schema_version": schema_version(previous_metadata),
        "current_schema_version": schema_version(current_metadata),
        "schema_compatibility_note": schema_note,
        "summary": summary,
        "output_files": [relative_output_path(path) for path in output_files],
        "output_file_checksums": checksum_files(checksum_targets),
        "run_status": run_status,
        "notes": [
            "Phase 4 compares rows by variant_key.",
            "price_compare_value is compared only when currency, tax_type, and price_compare_from match.",
            "Removed rows start as missing_candidate and become discontinued after four missing detections.",
            "schema_version mismatch stops diff and is written to errors.csv.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if run_status == "success" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run BoExio Phase 4 CSV diff.")
    parser.add_argument("--previous-csv", required=True)
    parser.add_argument("--current-csv", required=True)
    parser.add_argument("--previous-metadata", default="")
    parser.add_argument("--current-metadata", default="")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--run-id", default="")
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
