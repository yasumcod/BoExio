from __future__ import annotations

import argparse
import csv
import json
import shutil
import tarfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib import request

from boexio.phase2_variants import ERROR_COLUMNS, PHASE2_CSV_COLUMNS


PHASE6_PARSER_VERSION = "0.6.0"


@dataclass(frozen=True)
class PhaseResult:
    phase: str
    directory: Path
    command_exit_code: int
    run_status: str
    metadata_path: Path | None


def release_tag_for_date(run_date: date) -> str:
    return f"weekly-{run_date.isoformat()}"


def release_name_for_date(run_date: date) -> str:
    return f"BoExio Weekly Report {run_date.isoformat()}"


def write_empty_previous_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=PHASE2_CSV_COLUMNS)
        writer.writeheader()


def prepare_previous(downloaded_csv: Path, output_csv: Path, downloaded_metadata: Path, output_metadata: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if downloaded_csv.exists() and downloaded_csv.stat().st_size > 0:
        shutil.copy2(downloaded_csv, output_csv)
    else:
        write_empty_previous_csv(output_csv)

    if downloaded_metadata.exists() and downloaded_metadata.stat().st_size > 0:
        shutil.copy2(downloaded_metadata, output_metadata)
    elif output_metadata.exists():
        output_metadata.unlink()


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def run_status_from_metadata(path: Path) -> str:
    metadata = read_json(path)
    return str(metadata.get("run_status") or "missing")


def phase_result(phase: str, directory: Path, command_exit_code: int) -> PhaseResult:
    metadata_path = directory / "run_metadata.json"
    return PhaseResult(
        phase=phase,
        directory=directory,
        command_exit_code=command_exit_code,
        run_status=run_status_from_metadata(metadata_path),
        metadata_path=metadata_path if metadata_path.exists() else None,
    )


def overall_run_status(results: list[PhaseResult], validation_exit_codes: dict[str, int]) -> str:
    if any(code != 0 for code in validation_exit_codes.values()):
        return "failed"
    if any(result.command_exit_code != 0 or result.run_status in {"failed", "missing"} for result in results):
        return "failed"
    if any(result.run_status == "partial_success" for result in results):
        return "partial_success"
    return "success"


def copy_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.stat().st_size == 0:
        write_text_for_destination(destination, f"{source.name} was generated but empty.\n")
        return True
    if destination.suffix.lower() == ".csv":
        write_text_for_destination(destination, source.read_text(encoding="utf-8-sig"))
        return True
    shutil.copy2(source, destination)
    return True


def write_text_for_destination(destination: Path, text: str) -> None:
    encoding = "utf-8-sig" if destination.suffix.lower() == ".csv" else "utf-8"
    destination.write_text(text, encoding=encoding)


def copy_first_matching(directory: Path, pattern: str, destination: Path) -> bool:
    matches = sorted(directory.glob(pattern))
    if not matches:
        return False
    return copy_if_exists(matches[0], destination)


def write_errors(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=ERROR_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def stage_phase_outputs(
    phase3_dir: Path,
    phase4_dir: Path,
    phase5_dir: Path,
    logs_dir: Path,
    output_dir: Path,
) -> list[str]:
    copied: list[str] = []
    mappings = [
        (phase3_dir / "products_current.csv", output_dir / "phase3_products_current.csv"),
        (phase3_dir / "variant_candidates.csv", output_dir / "phase3_variant_candidates.csv"),
        (phase3_dir / "discovered_product_urls.csv", output_dir / "phase3_discovered_product_urls.csv"),
        (phase3_dir / "errors.csv", output_dir / "phase3_errors.csv"),
        (phase3_dir / "scrape_log.txt", output_dir / "phase3_scrape_log.txt"),
        (phase3_dir / "run_metadata.json", output_dir / "phase3_run_metadata.json"),
        (phase4_dir / "errors.csv", output_dir / "phase4_errors.csv"),
        (phase4_dir / "diff_summary.json", output_dir / "phase4_diff_summary.json"),
        (phase4_dir / "run_metadata.json", output_dir / "phase4_run_metadata.json"),
        (phase5_dir / "run_metadata.json", output_dir / "phase5_run_metadata.json"),
    ]
    for source, destination in mappings:
        if copy_if_exists(source, destination):
            copied.append(destination.name)

    glob_mappings = [
        (phase3_dir, "products_*.csv", "phase3_products_snapshot.csv"),
        (phase4_dir, "price_changes_*.csv", "phase4_price_changes.csv"),
        (phase4_dir, "new_items_*.csv", "phase4_new_items.csv"),
        (phase4_dir, "removed_items_*.csv", "phase4_removed_items.csv"),
        (phase5_dir, "weekly_report_*.xlsx", "phase5_weekly_report.xlsx"),
    ]
    for directory, pattern, name in glob_mappings:
        if copy_first_matching(directory, pattern, output_dir / name):
            copied.append(name)

    for log_path in sorted(logs_dir.glob("*.log")):
        destination = output_dir / f"workflow_{log_path.name}"
        if copy_if_exists(log_path, destination):
            copied.append(destination.name)

    return sorted(set(copied))


def create_bundle(output_dir: Path, bundle_name: str) -> Path:
    bundle_path = output_dir / bundle_name
    with tarfile.open(bundle_path, "w:gz") as archive:
        for path in sorted(output_dir.iterdir()):
            if path == bundle_path:
                continue
            archive.add(path, arcname=path.name)
    return bundle_path


def stage(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_date = date.fromisoformat(args.run_date)
    release_tag = args.release_tag or release_tag_for_date(run_date)
    release_name = args.release_name or release_name_for_date(run_date)
    validation_exit_codes = {
        "py_compile": args.py_compile_exit_code,
        "tests": args.tests_exit_code,
        "workflow_yaml": args.workflow_yaml_exit_code,
    }
    results = [
        phase_result("phase3", Path(args.phase3_dir), args.phase3_exit_code),
        phase_result("phase4", Path(args.phase4_dir), args.phase4_exit_code),
        phase_result("phase5", Path(args.phase5_dir), args.phase5_exit_code),
    ]
    copied = stage_phase_outputs(
        Path(args.phase3_dir),
        Path(args.phase4_dir),
        Path(args.phase5_dir),
        Path(args.logs_dir),
        output_dir,
    )
    phase3_metadata = read_json(Path(args.phase3_dir) / "run_metadata.json")
    status = overall_run_status(results, validation_exit_codes)
    now = datetime.now(timezone.utc).isoformat()
    errors: list[dict[str, str]] = []
    for name, code in validation_exit_codes.items():
        if code != 0:
            errors.append(error_row(name, "validation_failed", f"{name} exited with {code}", now))
    for result in results:
        if result.command_exit_code != 0:
            errors.append(
                error_row(result.phase, "phase_command_failed", f"{result.phase} exited with {result.command_exit_code}", now)
            )
        if result.run_status in {"failed", "missing"}:
            errors.append(error_row(result.phase, "phase_run_status_failed", f"run_status={result.run_status}", now))

    errors_path = output_dir / "phase6_errors.csv"
    write_errors(errors_path, errors)
    copied.append(errors_path.name)

    metadata = {
        "schema_version": "0.1.0",
        "parser_version": PHASE6_PARSER_VERSION,
        "run_id": args.run_id,
        "run_date": run_date.isoformat(),
        "release_tag": release_tag,
        "release_name": release_name,
        "previous_release_tag": args.previous_release_tag,
        "previous_csv": args.previous_csv,
        "generated_at": now,
        "validation_exit_codes": validation_exit_codes,
        "phase_results": [
            {
                "phase": result.phase,
                "directory": str(result.directory),
                "command_exit_code": result.command_exit_code,
                "run_status": result.run_status,
                "metadata_path": str(result.metadata_path or ""),
            }
            for result in results
        ],
        "overall_run_status": status,
        "missing_categories": phase3_metadata.get("missing_categories", []),
        "missing_chunks": phase3_metadata.get("missing_chunks", []),
        "failed_chunks": phase3_metadata.get("failed_chunks", []),
        "category_product_row_counts": phase3_metadata.get("category_product_row_counts", {}),
        "chunk_product_row_counts": phase3_metadata.get("chunk_product_row_counts", {}),
        "output_files": sorted(set(copied)),
        "notes": [
            "Phase 6 retrieves phase3_products_current.csv from the latest previous GitHub Release when available.",
            "If no previous CSV is available, an empty Phase 2 schema CSV is used so the first run reports current rows as new items.",
            "partial_success publishes usable artifacts while listing failed chunks; failed or missing phases fail the workflow.",
            "TODO: Decide the long-term GitHub Releases retention/deletion policy.",
            "TODO: Decide the production notification destination and formal BOEXIO_CONTACT_EMAIL value.",
        ],
    }
    metadata_path = output_dir / "phase6_metadata.json"
    release_body_path = output_dir / "release_body.md"
    bundle_name = f"boexio_weekly_bundle_{run_date.isoformat()}.tar.gz"
    metadata["output_files"] = sorted(set([*copied, metadata_path.name, release_body_path.name, bundle_name]))
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    release_body_path.write_text(release_body(metadata), encoding="utf-8")
    create_bundle(output_dir, bundle_name)
    return 0


def error_row(url: str, code: str, message: str, when: str) -> dict[str, str]:
    return {
        "url": url,
        "phase": "phase6",
        "error_code": code,
        "message": message,
        "first_seen_at": when,
        "last_seen_at": when,
    }


def release_body(metadata: dict) -> str:
    lines = [
        f"# {metadata['release_name']}",
        "",
        f"- run_status: `{metadata['overall_run_status']}`",
        f"- run_id: `{metadata['run_id']}`",
        f"- previous_release_tag: `{metadata.get('previous_release_tag') or 'none'}`",
        "",
        "## Phase Results",
    ]
    for result in metadata["phase_results"]:
        lines.append(
            f"- {result['phase']}: run_status=`{result['run_status']}`, exit_code=`{result['command_exit_code']}`"
        )
    lines.extend(["", "## Missing / Failed Chunks"])
    missing_categories = metadata.get("missing_categories", [])
    missing_chunks = metadata.get("missing_chunks", [])
    failed_chunks = metadata.get("failed_chunks", [])
    lines.append(f"- missing_categories: `{', '.join(missing_categories) if missing_categories else 'none'}`")
    lines.append(f"- missing_chunks: `{', '.join(missing_chunks) if missing_chunks else 'none'}`")
    lines.append(f"- failed_chunks: `{', '.join(failed_chunks) if failed_chunks else 'none'}`")
    lines.extend(
        [
            "",
            "## Notes",
            "- Generated artifacts, metadata, errors, and workflow logs are attached as Release assets.",
            "- The same staged files are uploaded as a GitHub Actions artifact with 30-day retention.",
        ]
    )
    return "\n".join(lines) + "\n"


def notify(args: argparse.Namespace) -> int:
    metadata = read_json(Path(args.metadata))
    if not args.webhook_url:
        return 0
    payload = {
        "text": (
            f"{metadata.get('release_name', 'BoExio Weekly Report')} "
            f"run_status={metadata.get('overall_run_status', 'unknown')} "
            f"release={args.release_url}"
        )
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    http_request = request.Request(
        args.webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(http_request, timeout=args.timeout) as response:
        response.read()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BoExio Phase 6 workflow helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    previous = subparsers.add_parser("prepare-previous")
    previous.add_argument("--downloaded-csv", required=True)
    previous.add_argument("--output-csv", required=True)
    previous.add_argument("--downloaded-metadata", required=True)
    previous.add_argument("--output-metadata", required=True)
    previous.set_defaults(
        func=lambda args: prepare_previous(
            Path(args.downloaded_csv),
            Path(args.output_csv),
            Path(args.downloaded_metadata),
            Path(args.output_metadata),
        )
        or 0
    )

    stage_parser = subparsers.add_parser("stage")
    stage_parser.add_argument("--run-id", required=True)
    stage_parser.add_argument("--run-date", required=True)
    stage_parser.add_argument("--release-tag", default="")
    stage_parser.add_argument("--release-name", default="")
    stage_parser.add_argument("--previous-release-tag", default="")
    stage_parser.add_argument("--previous-csv", default="")
    stage_parser.add_argument("--phase3-dir", required=True)
    stage_parser.add_argument("--phase4-dir", required=True)
    stage_parser.add_argument("--phase5-dir", required=True)
    stage_parser.add_argument("--logs-dir", required=True)
    stage_parser.add_argument("--output-dir", required=True)
    stage_parser.add_argument("--py-compile-exit-code", type=int, required=True)
    stage_parser.add_argument("--tests-exit-code", type=int, required=True)
    stage_parser.add_argument("--workflow-yaml-exit-code", type=int, required=True)
    stage_parser.add_argument("--phase3-exit-code", type=int, required=True)
    stage_parser.add_argument("--phase4-exit-code", type=int, required=True)
    stage_parser.add_argument("--phase5-exit-code", type=int, required=True)
    stage_parser.set_defaults(func=stage)

    notify_parser = subparsers.add_parser("notify")
    notify_parser.add_argument("--webhook-url", default="")
    notify_parser.add_argument("--metadata", required=True)
    notify_parser.add_argument("--release-url", default="")
    notify_parser.add_argument("--timeout", type=int, default=10)
    notify_parser.set_defaults(func=notify)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
