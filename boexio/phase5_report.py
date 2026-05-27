from __future__ import annotations

import argparse
import csv
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from boexio.phase1_poc import commit_sha, relative_output_path, sha256_file
from boexio.phase2_variants import ERROR_COLUMNS
from boexio.phase4_diff import ADDED_COLUMNS, PRICE_CHANGE_COLUMNS, REMOVED_COLUMNS
from boexio.quote_columns import QUOTE_MASTER_COLUMNS, quote_master_rows
from boexio.xlsx_writer import Worksheet, write_xlsx


PHASE5_PARSER_VERSION = "0.5.0"
REPORT_SCHEMA_VERSION = "0.1.0"
SUMMARY_ROWS = [
    ("取得日", "generated_at"),
    ("対象商品数", "target_product_count"),
    ("取得成功数", "success_count"),
    ("取得失敗数", "failure_count"),
    ("総構成数", "current_row_count"),
    ("価格変更数", "price_change_count"),
    ("値上げ数", "increase_count"),
    ("値下げ数", "decrease_count"),
    ("新規追加数", "added_count"),
    ("削除候補数", "removed_count"),
    ("新規候補数", "new_candidate_count"),
    ("確定終了数", "discontinued_count"),
    ("復活数", "revived_count"),
    ("通貨不一致件数", "currency_mismatch_count"),
    ("比較不可件数", "comparison_error_count"),
]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def csv_headers(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or [])


def validate_errors_csv(path: Path) -> None:
    headers = csv_headers(path)
    missing = [column for column in ERROR_COLUMNS if column not in headers]
    if missing:
        raise RuntimeError(f"errors CSV is missing required columns: {', '.join(missing)}")


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def default_diff_file(diff_run_dir: Path, prefix: str) -> Path:
    matches = sorted(diff_run_dir.glob(f"{prefix}_*.csv"))
    return matches[0] if matches else diff_run_dir / f"{prefix}.csv"


def to_number(value: str) -> int | float | str:
    if value == "":
        return ""
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def table_rows(columns: list[str], rows: list[dict[str, str]]) -> list[list[str | int | float]]:
    output: list[list[str | int | float]] = [columns]
    for row in rows:
        output.append([to_number(row.get(column, "")) for column in columns])
    return output


def summary_from_inputs(diff_summary: dict, current_rows: list[dict[str, str]], generated_at: str) -> dict[str, int | str]:
    success_count = sum(1 for row in current_rows if row.get("scrape_status") == "success")
    failure_count = sum(1 for row in current_rows if row.get("scrape_status") == "failed")
    target_products = len(
        {
            (row.get("series", ""), row.get("product_name", ""))
            for row in current_rows
            if row.get("product_name")
        }
    )
    return {
        "generated_at": generated_at,
        "target_product_count": target_products,
        "success_count": success_count,
        "failure_count": failure_count,
        "current_row_count": len(current_rows),
        "price_change_count": int(diff_summary.get("price_change_count", 0)),
        "increase_count": int(diff_summary.get("increase_count", 0)),
        "decrease_count": int(diff_summary.get("decrease_count", 0)),
        "added_count": int(diff_summary.get("added_count", 0)),
        "removed_count": int(diff_summary.get("removed_count", 0)),
        "new_candidate_count": int(diff_summary.get("added_count", 0)),
        "discontinued_count": int(diff_summary.get("discontinued_count", 0)),
        "revived_count": int(diff_summary.get("revived_count", 0)),
        "currency_mismatch_count": int(diff_summary.get("currency_mismatch_count", 0)),
        "comparison_error_count": int(diff_summary.get("comparison_error_count", 0)),
    }


def summary_sheet_rows(summary: dict[str, int | str], diff_summary: dict) -> list[list[str | int]]:
    rows: list[list[str | int]] = [["指標", "値"]]
    for label, key in SUMMARY_ROWS:
        rows.append([label, summary.get(key, 0)])
    rows.append(["", ""])
    rows.append(["入力 previous_csv", str(diff_summary.get("previous_csv", ""))])
    rows.append(["入力 current_csv", str(diff_summary.get("current_csv", ""))])
    return rows


def current_master_columns(rows: list[dict[str, str]]) -> list[str]:
    return QUOTE_MASTER_COLUMNS


def apply_current_master_metadata(rows: list[dict[str, str]], metadata: dict) -> list[dict[str, str]]:
    parser_version = str(metadata.get("parser_version", ""))
    schema_version = str(metadata.get("schema_version", ""))
    enriched_rows: list[dict[str, str]] = []
    for row in rows:
        enriched = dict(row)
        if parser_version and not enriched.get("parser_version"):
            enriched["parser_version"] = parser_version
        if schema_version and not enriched.get("schema_version"):
            enriched["schema_version"] = schema_version
        enriched_rows.append(enriched)
    return enriched_rows


def worksheet_widths(columns: list[str]) -> list[float]:
    widths: list[float] = []
    for column in columns:
        if "url" in column:
            widths.append(46)
        elif column in {"selected_upholstery", "product_name"}:
            widths.append(34)
        elif column in {"message", "material"}:
            widths.append(54)
        elif "price" in column or "count" in column:
            widths.append(16)
        else:
            widths.append(20)
    return widths


def build_worksheets(
    summary: dict[str, int | str],
    diff_summary: dict,
    price_changes: list[dict[str, str]],
    added: list[dict[str, str]],
    removed: list[dict[str, str]],
    current_rows: list[dict[str, str]],
    errors: list[dict[str, str]],
) -> list[Worksheet]:
    current_columns = current_master_columns(current_rows)
    sales_current_rows = quote_master_rows(current_rows)
    return [
        Worksheet("summary", summary_sheet_rows(summary, diff_summary), [28, 72], freeze_top_row=True, auto_filter=False),
        Worksheet("price_changes", table_rows(PRICE_CHANGE_COLUMNS, price_changes), worksheet_widths(PRICE_CHANGE_COLUMNS)),
        Worksheet("added", table_rows(ADDED_COLUMNS, added), worksheet_widths(ADDED_COLUMNS)),
        Worksheet("removed", table_rows(REMOVED_COLUMNS, removed), worksheet_widths(REMOVED_COLUMNS)),
        Worksheet("current_master", table_rows(current_columns, sales_current_rows), worksheet_widths(current_columns)),
        Worksheet("errors", table_rows(ERROR_COLUMNS, errors), worksheet_widths(ERROR_COLUMNS)),
    ]


def validate_xlsx(path: Path, expected_sheet_count: int) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        required = {"[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml"}
        for index in range(1, expected_sheet_count + 1):
            required.add(f"xl/worksheets/sheet{index}.xml")
        missing = required - names
        if missing:
            raise RuntimeError(f"xlsx missing required parts: {', '.join(sorted(missing))}")


def checksum_files(paths: list[Path]) -> dict[str, str]:
    return {relative_output_path(path): sha256_file(path) for path in paths}


def run(args: argparse.Namespace) -> int:
    started_at = datetime.now(timezone.utc)
    run_id = args.run_id or started_at.strftime("%Y%m%dT%H%M%SZ")
    diff_run_dir = Path(args.diff_run_dir)
    output_dir = Path(args.output_dir) / "runs" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    price_changes_path = Path(args.price_changes_csv) if args.price_changes_csv else default_diff_file(diff_run_dir, "price_changes")
    added_path = Path(args.added_csv) if args.added_csv else default_diff_file(diff_run_dir, "new_items")
    removed_path = Path(args.removed_csv) if args.removed_csv else default_diff_file(diff_run_dir, "removed_items")
    errors_path = Path(args.errors_csv) if args.errors_csv else diff_run_dir / "errors.csv"
    diff_summary_path = Path(args.diff_summary) if args.diff_summary else diff_run_dir / "diff_summary.json"
    current_master_path = Path(args.current_master)

    validate_errors_csv(errors_path)
    price_changes = read_csv_rows(price_changes_path)
    added = read_csv_rows(added_path)
    removed = read_csv_rows(removed_path)
    errors = read_csv_rows(errors_path)
    current_rows = read_csv_rows(current_master_path)
    current_metadata_path = current_master_path.parent / "run_metadata.json"
    current_rows = apply_current_master_metadata(current_rows, read_json(current_metadata_path))
    diff_summary = read_json(diff_summary_path)
    summary = summary_from_inputs(diff_summary, current_rows, started_at.isoformat())
    discontinued_count = sum(1 for row in removed if row.get("current_state") == "discontinued")
    summary["discontinued_count"] = discontinued_count

    worksheets = build_worksheets(summary, diff_summary, price_changes, added, removed, current_rows, errors)
    report_path = output_dir / f"weekly_report_{started_at.strftime('%Y-%m-%d')}_{run_id}.xlsx"
    write_xlsx(report_path, worksheets)
    validate_xlsx(report_path, expected_sheet_count=6)

    metadata_path = output_dir / "run_metadata.json"
    checksum_targets = [report_path]
    metadata = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "parser_version": PHASE5_PARSER_VERSION,
        "commit_sha": commit_sha(),
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "diff_run_dir": str(diff_run_dir),
        "current_master": str(current_master_path),
        "inputs": {
            "price_changes_csv": str(price_changes_path),
            "added_csv": str(added_path),
            "removed_csv": str(removed_path),
            "errors_csv": str(errors_path),
            "diff_summary": str(diff_summary_path),
            "current_master_metadata": str(current_metadata_path) if current_metadata_path.exists() else "",
        },
        "summary": summary,
        "output_files": [relative_output_path(report_path), relative_output_path(metadata_path)],
        "output_file_checksums": checksum_files(checksum_targets),
        "run_status": "success",
        "notes": [
            "Phase 5 generates a six-sheet Excel workbook for sales/admin review.",
            "The workbook contains summary, price_changes, added, removed, current_master, and errors sheets.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run BoExio Phase 5 Excel report generation.")
    parser.add_argument("--diff-run-dir", required=True)
    parser.add_argument("--current-master", required=True)
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--price-changes-csv", default="")
    parser.add_argument("--added-csv", default="")
    parser.add_argument("--removed-csv", default="")
    parser.add_argument("--errors-csv", default="")
    parser.add_argument("--diff-summary", default="")
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
