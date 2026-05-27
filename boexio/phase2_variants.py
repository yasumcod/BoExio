from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product as cartesian_product
from pathlib import Path
from urllib.parse import urljoin

from boexio.phase1_poc import (
    CSV_COLUMNS,
    PARSER_VERSION,
    SCHEMA_VERSION,
    collect_output_files,
    commit_sha,
    failed_row,
    fetch_url,
    parse_product,
    read_target_urls,
    relative_output_path,
    select_representative_product,
    sha256_file,
    split_error,
    validate_discovered_product_url,
    validate_input_url,
)


PHASE2_PARSER_VERSION = "0.2.1"
PHASE2_CSV_COLUMNS = [
    *CSV_COLUMNS,
    "category_name",
    "category_url",
    "variant_key",
    "variant_key_from",
    "variant_key_error_type",
    "variant_key_error_detail",
    "list_price_value",
    "display_price_value",
    "canonical_price_value",
    "price_compare_value",
    "price_compare_from",
    "price_normalization_error",
]
CANDIDATE_COLUMNS = [
    "run_id",
    "product_url",
    "variant_url",
    "variant_url_key",
    "selected_leg_id",
    "selected_leg",
    "selected_upholstery_id",
    "selected_upholstery",
    "candidate_status",
    "candidate_error",
]
ERROR_COLUMNS = ["url", "phase", "error_code", "message", "first_seen_at", "last_seen_at"]
SYNONYM_REPLACEMENTS = (
    ("ファブリック", "fabric"),
    ("ｆａｂｒｉｃ", "fabric"),
    ("レザー", "leather"),
    ("革", "leather"),
    ("オーク", "oak"),
    ("無垢材", " solid wood "),
    ("自然", "natural "),
    ("暗色", "dark "),
)


@dataclass(frozen=True)
class OptionValue:
    attribute_id: str
    attribute_label: str
    option_id: str
    name: str


@dataclass(frozen=True)
class VariantCandidate:
    product_url: str
    variant_url: str
    variant_url_key: str
    selected_leg_id: str
    selected_leg: str
    selected_upholstery_id: str
    selected_upholstery: str
    candidate_status: str = "pending"
    candidate_error: str = ""


def unescape_next_payload(html: str) -> str:
    return html.replace(r"\"", '"').replace(r"\/", "/")


def balanced_json_object(text: str, marker: str) -> dict:
    start = text.find(marker)
    if start == -1:
        raise ValueError(f"marker not found: {marker}")
    object_start = text.find("{", start)
    if object_start == -1:
        raise ValueError(f"object start not found after marker: {marker}")

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[object_start:], object_start):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[object_start : index + 1])
    raise ValueError(f"object end not found after marker: {marker}")


def product_payload(html: str) -> dict:
    return balanced_json_object(unescape_next_payload(html), '"product":{"superMasterKey"')


def configuration_payload(html: str) -> dict:
    return balanced_json_object(unescape_next_payload(html), '"configuration":{"options"')


def selected_options_payload(html: str) -> dict[str, str]:
    product = product_payload(html)
    selected = product.get("selectedOptions", {})
    return selected if isinstance(selected, dict) else {}


def option_values(configuration: dict, attribute_id: str) -> list[OptionValue]:
    values: list[OptionValue] = []
    for option in configuration.get("options", []):
        if option.get("attributeId") != attribute_id:
            continue
        for value in option.get("values", []):
            option_id = str(value.get("id", ""))
            name = str(value.get("name", ""))
            if option_id and name:
                values.append(
                    OptionValue(
                        attribute_id=attribute_id,
                        attribute_label=str(option.get("attributeLabel", "")),
                        option_id=option_id,
                        name=name,
                    )
                )
    return values


def replace_option_id(variant_url_key: str, old_value: str, new_value: str) -> str:
    return variant_url_key.replace(old_value.lower(), new_value.lower()).replace(old_value, new_value.lower())


def build_variant_url_key(
    base_variant_url_key: str,
    selected_options: dict[str, str],
    replacements: dict[str, str],
) -> str:
    variant_url_key = base_variant_url_key
    for attribute_id, new_option_id in replacements.items():
        current_option_id = selected_options.get(attribute_id, "")
        if current_option_id:
            variant_url_key = replace_option_id(variant_url_key, current_option_id, new_option_id)
    return variant_url_key


def variant_url(product_url: str, variant_url_key: str) -> str:
    parts = product_url.rstrip("/").split("/")
    slug = parts[-2] if len(parts) >= 2 else ""
    return urljoin(product_url, f"/ja-jp/p/{slug}/{variant_url_key}/")


def extract_candidates(product_url: str, html: str) -> list[VariantCandidate]:
    product = product_payload(html)
    configuration = configuration_payload(html)
    selected_options = selected_options_payload(html)
    base_variant_url_key = str(product.get("variantUrlKey", ""))
    if not base_variant_url_key:
        raise ValueError("variantUrlKey was not found")

    legs = option_values(configuration, "vaMaterialLeg")
    upholstery_attribute_id = "vaMaterialUpholstery"
    upholsteries = option_values(configuration, upholstery_attribute_id)
    if not upholsteries:
        upholstery_attribute_id = "vaMaterialSeat"
        upholsteries = option_values(configuration, upholstery_attribute_id)
    if not legs or not upholsteries:
        raise ValueError("leg or upholstery/seat options were not found")

    candidates: list[VariantCandidate] = []
    for leg, upholstery in cartesian_product(legs, upholsteries):
        variant_url_key = build_variant_url_key(
            base_variant_url_key,
            selected_options,
            {
                "vaMaterialLeg": leg.option_id,
                upholstery_attribute_id: upholstery.option_id,
            },
        )
        url = variant_url(product_url, variant_url_key)
        valid, error_code = validate_discovered_product_url(url)
        candidates.append(
            VariantCandidate(
                product_url=product_url,
                variant_url=url,
                variant_url_key=variant_url_key,
                selected_leg_id=leg.option_id,
                selected_leg=leg.name,
                selected_upholstery_id=upholstery.option_id,
                selected_upholstery=upholstery.name,
                candidate_status="pending" if valid else "invalid",
                candidate_error=error_code,
            )
        )
    return candidates


def write_candidates_csv(path: Path, run_id: str, candidates: list[VariantCandidate]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CANDIDATE_COLUMNS)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "run_id": run_id,
                    "product_url": candidate.product_url,
                    "variant_url": candidate.variant_url,
                    "variant_url_key": candidate.variant_url_key,
                    "selected_leg_id": candidate.selected_leg_id,
                    "selected_leg": candidate.selected_leg,
                    "selected_upholstery_id": candidate.selected_upholstery_id,
                    "selected_upholstery": candidate.selected_upholstery,
                    "candidate_status": candidate.candidate_status,
                    "candidate_error": candidate.candidate_error,
                }
            )


def normalize_attribute(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    for source, replacement in SYNONYM_REPLACEMENTS:
        normalized = normalized.replace(unicodedata.normalize("NFKC", source).lower(), replacement)
    normalized = re.sub(r"[-_/・|:：]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def generate_variant_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    variant_id = row.get("variant_id", "").strip()
    sku = row.get("sku", "").strip()
    if variant_id:
        return variant_id, "variant_id", "", ""
    if sku:
        return sku, "sku", "", ""

    required = ["item_number", "selected_size", "selected_upholstery", "selected_leg"]
    missing = [field for field in required if not row.get(field, "").strip()]
    if missing:
        return "", "", "missing_required_attribute", f"missing fields: {', '.join(missing)}"

    try:
        parts = [normalize_attribute(row[field]) for field in required]
    except Exception as exc:
        return "", "", "normalization_failed", str(exc)
    if not any(parts):
        return "", "", "empty_key_after_normalization", "all normalized key parts are empty"
    return "|".join(parts), "normalized_attributes", "", ""


def parse_price_value(value: str) -> tuple[str, str]:
    if not value:
        return "", ""
    normalized = unicodedata.normalize("NFKC", value)
    digits = re.sub(r"[^0-9]", "", normalized)
    if not digits:
        return "", f"price has no digits: {value}"
    return digits, ""


def enrich_row(row: dict[str, str]) -> dict[str, str]:
    enriched = {column: row.get(column, "") for column in PHASE2_CSV_COLUMNS}
    variant_key, key_from, key_error_type, key_error_detail = generate_variant_key(row)
    enriched["variant_key"] = variant_key
    enriched["variant_key_from"] = key_from
    enriched["variant_key_error_type"] = key_error_type
    enriched["variant_key_error_detail"] = key_error_detail

    price_errors: list[str] = []
    for source_column, output_column in (
        ("list_price", "list_price_value"),
        ("display_price", "display_price_value"),
        ("canonical_price", "canonical_price_value"),
    ):
        price_value, error = parse_price_value(row.get(source_column, ""))
        enriched[output_column] = price_value
        if error and row.get(source_column, ""):
            price_errors.append(f"{source_column}: {error}")

    if enriched["canonical_price_value"]:
        enriched["price_compare_value"] = enriched["canonical_price_value"]
        enriched["price_compare_from"] = "canonical_price"
    elif enriched["list_price_value"]:
        enriched["price_compare_value"] = enriched["list_price_value"]
        enriched["price_compare_from"] = "list_price"
    else:
        price_errors.append("missing comparable price")
    enriched["price_normalization_error"] = " / ".join(price_errors)
    return enriched


def enrich_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [enrich_row(row) for row in rows]


def write_phase2_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=PHASE2_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def error_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    now = datetime.now(timezone.utc).isoformat()
    errors: list[dict[str, str]] = []
    for row in rows:
        source_url = row.get("source_url", "")
        checked_at = row.get("source_checked_at") or now
        if row.get("scrape_status") == "failed":
            errors.append(
                {
                    "url": source_url,
                    "phase": "fetch",
                    "error_code": row.get("scrape_error_code", "UNKNOWN") or "UNKNOWN",
                    "message": row.get("scrape_error_message", ""),
                    "first_seen_at": checked_at,
                    "last_seen_at": checked_at,
                }
            )
            continue
        if row.get("variant_key_error_type"):
            errors.append(
                {
                    "url": source_url,
                    "phase": "normalize",
                    "error_code": row.get("variant_key_error_type", ""),
                    "message": row.get("variant_key_error_detail", ""),
                    "first_seen_at": checked_at,
                    "last_seen_at": checked_at,
                }
            )
        if row.get("price_normalization_error"):
            errors.append(
                {
                    "url": source_url,
                    "phase": "normalize",
                    "error_code": "price_normalization_error",
                    "message": row.get("price_normalization_error", ""),
                    "first_seen_at": checked_at,
                    "last_seen_at": checked_at,
                }
            )
    return errors


def write_errors_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=ERROR_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def checksum_files(paths: list[Path]) -> dict[str, str]:
    return {relative_output_path(path): sha256_file(path) for path in paths}


def run(args: argparse.Namespace) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir) / "runs" / run_id
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    logs: list[str] = []
    rows: list[dict[str, str]] = []
    target_urls = read_target_urls(Path(args.targets))

    candidates: list[VariantCandidate] = []
    product_url = ""
    for target_url in target_urls[:1]:
        valid, error_code = validate_input_url(target_url)
        if not valid:
            rows.append(failed_row(run_id, target_url, error_code, "input URL is not allowed"))
            continue
        try:
            category = fetch_url(target_url, args.timeout)
            (raw_dir / "category.html").write_text(category.html, encoding="utf-8")
            product_url = select_representative_product(target_url, category.html) or ""
            if not product_url:
                rows.append(failed_row(run_id, target_url, "SELECTOR_MISS", "product URL was not found"))
                continue

            product_page = fetch_url(product_url, args.timeout)
            (raw_dir / "product_base.html").write_text(product_page.html, encoding="utf-8")
            candidates = extract_candidates(product_url, product_page.html)
            valid_candidates = [candidate for candidate in candidates if candidate.candidate_status == "pending"]
            logs.append(f"selected_product_url={product_url}")
            logs.append(f"variant_candidate_count={len(candidates)}")
            logs.append(f"variant_fetch_limit={args.variant_limit}")
            logs.append(f"variant_fetch_offset={args.variant_offset}")

            selected_candidates = valid_candidates[args.variant_offset : args.variant_offset + args.variant_limit]
            for index, candidate in enumerate(selected_candidates, start=1):
                try:
                    variant_page = fetch_url(candidate.variant_url, args.timeout)
                    raw_name = f"variant_{index:03d}_{candidate.variant_url_key.replace(':', '_')}.html"
                    raw_path = raw_dir / raw_name
                    raw_path.write_text(variant_page.html, encoding="utf-8")
                    rows.append(parse_product(variant_page, f"raw/{raw_name}", run_id))
                    logs.append(f"fetched_variant_url={candidate.variant_url}")
                except Exception as exc:
                    code, detail = split_error(exc)
                    rows.append(failed_row(run_id, candidate.variant_url, code, detail))
                    logs.append(f"failed_variant_url={candidate.variant_url} code={code} detail={detail}")
        except Exception as exc:
            code, detail = split_error(exc)
            rows.append(failed_row(run_id, target_url, code, detail))
            logs.append(f"failed_url={target_url} code={code} detail={detail}")

    csv_path = output_dir / "products_poc.csv"
    candidates_path = output_dir / "variant_candidates.csv"
    errors_path = output_dir / "phase2_errors.csv"
    log_path = output_dir / "scrape_log.txt"
    metadata_path = output_dir / "run_metadata.json"
    enriched_rows = enrich_rows(rows)
    errors = error_rows(enriched_rows)
    write_phase2_csv(csv_path, enriched_rows)
    write_candidates_csv(candidates_path, run_id, candidates)
    write_errors_csv(errors_path, errors)
    log_path.write_text("\n".join(logs) + "\n", encoding="utf-8")

    success_count = sum(1 for row in rows if row["scrape_status"] == "success")
    failure_count = sum(1 for row in rows if row["scrape_status"] == "failed")
    run_status = "success" if success_count and not failure_count else "partial_success" if success_count else "failed"
    checksum_targets = [csv_path, candidates_path, errors_path, log_path, *collect_output_files(raw_dir)]
    output_files = [*checksum_targets, metadata_path]
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PHASE2_PARSER_VERSION,
        "phase1_parser_version": PARSER_VERSION,
        "commit_sha": commit_sha(),
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "target_urls": target_urls,
        "product_url": product_url,
        "variant_candidate_count": len(candidates),
        "variant_fetch_limit": args.variant_limit,
        "variant_fetch_offset": args.variant_offset,
        "variant_key_success_count": sum(1 for row in enriched_rows if row.get("variant_key")),
        "phase2_error_ready_count": len(errors),
        "output_files": [relative_output_path(path) for path in output_files],
        "output_file_checksums": checksum_files(checksum_targets),
        "run_status": run_status,
        "success_count": success_count,
        "failure_count": failure_count,
        "notes": [
            "Phase 2 PoC extracts all leg/upholstery candidates from embedded Next.js configuration.options.",
            "products_poc.csv contains fetched variant rows up to variant_fetch_limit to avoid high request volume during PoC.",
            "variant_id and sku are verified for fetched variants; full candidate list is in variant_candidates.csv.",
            "variant_key uses variant_id first, sku second, and normalized attributes as fallback.",
            "price_compare_value uses canonical_price first and list_price second; display from-prices are not preferred for comparison.",
            "phase2_errors.csv uses the report error shape: url, phase, error_code, message, first_seen_at, last_seen_at.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if success_count else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run BoExio Phase 2 variant PoC.")
    parser.add_argument("--targets", default="config/target_urls.txt")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--variant-limit", type=int, default=6)
    parser.add_argument("--variant-offset", type=int, default=0)
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
