from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from itertools import product as cartesian_product
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from boexio.phase1_poc import (
    CSV_COLUMNS,
    PARSER_VERSION,
    SCHEMA_VERSION,
    USER_AGENT,
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


PHASE2_PARSER_VERSION = "0.2.2"
VARIANT_OPTIONS_URL = "https://www.boconcept.com/api/product/variant-options/?locale=ja-jp"
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
    "super_master_key",
    "selected_options_json",
    "selected_option_names_json",
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
    previous_requirements: dict[str, object]


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
    selected_options_json: str = ""
    selected_option_names_json: str = ""
    super_master_key: str = ""


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
                        previous_requirements=(
                            value.get("previousRequirements", {})
                            if isinstance(value.get("previousRequirements", {}), dict)
                            else {}
                        ),
                    )
                )
    return values


def configuration_options(configuration: dict) -> list[tuple[str, str, list[OptionValue]]]:
    options: list[tuple[str, str, list[OptionValue]]] = []
    for option in configuration.get("options", []):
        attribute_id = str(option.get("attributeId", ""))
        if not attribute_id:
            continue
        values = option_values(configuration, attribute_id)
        if values:
            options.append((attribute_id, str(option.get("attributeLabel", "")), values))
    return options


def option_token_spans(variant_url_key: str, option_id: str) -> list[tuple[int, int]]:
    if not option_id:
        return []
    pattern = re.compile(
        rf"(?<=[:_]){re.escape(option_id)}(?=$|-\d+[:_])",
        flags=re.IGNORECASE,
    )
    return [match.span() for match in pattern.finditer(variant_url_key)]


def build_variant_url_key(
    base_variant_url_key: str,
    option_spans: dict[str, tuple[int, int]],
    replacements: dict[str, str],
) -> str:
    variant_url_key = base_variant_url_key
    replacements_with_spans = [
        (option_spans[attribute_id], new_option_id)
        for attribute_id, new_option_id in replacements.items()
        if attribute_id in option_spans
    ]
    for (start, end), new_option_id in sorted(replacements_with_spans, reverse=True):
        variant_url_key = f"{variant_url_key[:start]}{new_option_id.lower()}{variant_url_key[end:]}"
    return variant_url_key


def variant_url(product_url: str, variant_url_key: str) -> str:
    parts = product_url.rstrip("/").split("/")
    slug = parts[-2] if len(parts) >= 2 else ""
    return urljoin(product_url, f"/ja-jp/p/{slug}/{variant_url_key}/")


def requirement_values(value: object) -> set[str]:
    if isinstance(value, list):
        return {str(item) for item in value}
    if isinstance(value, dict):
        nested = value.get("values", value.get("value", []))
        return requirement_values(nested)
    if value is None:
        return set()
    return {str(value)}


def option_combination_allowed(selected: dict[str, OptionValue]) -> bool:
    for option in selected.values():
        for attribute_id, required in option.previous_requirements.items():
            allowed_values = requirement_values(required)
            selected_requirement = selected.get(attribute_id)
            if allowed_values and (
                selected_requirement is None or selected_requirement.option_id not in allowed_values
            ):
                return False
    return True


def selected_option_json(selected: dict[str, OptionValue], field: str) -> str:
    values = {
        attribute_id: getattr(option, field)
        for attribute_id, option in sorted(selected.items())
    }
    return json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def extract_candidates(product_url: str, html: str) -> list[VariantCandidate]:
    product = product_payload(html)
    configuration = configuration_payload(html)
    selected_options = selected_options_payload(html)
    base_variant_url_key = str(product.get("variantUrlKey", ""))
    if not base_variant_url_key:
        raise ValueError("variantUrlKey was not found")

    dimensions: list[tuple[str, list[OptionValue]]] = []
    option_spans: dict[str, tuple[int, int]] = {}
    used_option_spans: set[tuple[int, int]] = set()
    fixed_options: dict[str, OptionValue] = {}
    for attribute_id, _attribute_label, values in configuration_options(configuration):
        selected_option_id = str(selected_options.get(attribute_id, ""))
        if not selected_option_id and len(values) == 1:
            selected_option_id = values[0].option_id
        selected_value = next(
            (value for value in values if value.option_id.lower() == selected_option_id.lower()),
            None,
        )
        if selected_value is None:
            if len(values) > 1:
                raise ValueError(f"selected option was not found for configurable attribute: {attribute_id}")
            fixed_options[attribute_id] = values[0]
            continue

        available_spans = [
            span
            for span in option_token_spans(base_variant_url_key, selected_option_id)
            if span not in used_option_spans
        ]
        if not available_spans:
            if len(values) > 1:
                raise ValueError(f"selected option token was not found in variantUrlKey: {attribute_id}")
            fixed_options[attribute_id] = selected_value
            continue
        span = available_spans[0]
        option_spans[attribute_id] = span
        used_option_spans.add(span)
        dimensions.append((attribute_id, values))

    candidates: list[VariantCandidate] = []
    combinations = cartesian_product(*(values for _attribute_id, values in dimensions))
    if not dimensions:
        combinations = [()]
    seen_variant_keys: set[str] = set()
    for combination in combinations:
        selected = dict(fixed_options)
        selected.update(
            {
                attribute_id: option
                for (attribute_id, _values), option in zip(dimensions, combination)
            }
        )
        if not option_combination_allowed(selected):
            continue
        replacements = {
            attribute_id: option.option_id
            for attribute_id, option in selected.items()
            if attribute_id in option_spans
        }
        variant_url_key = build_variant_url_key(
            base_variant_url_key,
            option_spans,
            replacements,
        )
        if variant_url_key in seen_variant_keys:
            continue
        seen_variant_keys.add(variant_url_key)
        url = variant_url(product_url, variant_url_key)
        valid, error_code = validate_discovered_product_url(url)
        leg = selected.get("vaMaterialLeg") or selected.get("vaMaterialLegStyle")
        upholstery = selected.get("vaMaterialUpholstery") or selected.get("vaMaterialSeat")
        candidates.append(
            VariantCandidate(
                product_url=product_url,
                variant_url=url,
                variant_url_key=variant_url_key,
                selected_leg_id=leg.option_id if leg else "",
                selected_leg=leg.name if leg else "",
                selected_upholstery_id=upholstery.option_id if upholstery else "",
                selected_upholstery=upholstery.name if upholstery else "",
                candidate_status="pending" if valid else "invalid",
                candidate_error=error_code,
                selected_options_json=selected_option_json(selected, "option_id"),
                selected_option_names_json=selected_option_json(selected, "name"),
                super_master_key=str(product.get("superMasterKey", "")),
            )
        )
    if not candidates:
        raise ValueError("no valid option combinations were generated")
    return candidates


def resolve_candidate(candidate: VariantCandidate, timeout: int) -> tuple[VariantCandidate | None, dict]:
    if not candidate.super_master_key:
        raise ValueError("superMasterKey was not found")
    selections = json.loads(candidate.selected_options_json or "{}")
    request_body = json.dumps(
        {
            "superMasterKey": candidate.super_master_key,
            "selections": selections,
        }
    )
    request = Request(
        VARIANT_OPTIONS_URL,
        data=request_body.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"HTTP_{exc.code}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("TIMEOUT_READ: request timed out") from exc
    except URLError as exc:
        reason = str(exc.reason)
        if "unknown url type: https" not in reason and "CERTIFICATE_VERIFY_FAILED" not in reason:
            code = "TIMEOUT_CONNECT" if "timed out" in reason.lower() else "UNKNOWN"
            raise RuntimeError(f"{code}: {reason}") from exc
        result = subprocess.run(
            [
                "curl",
                "-sS",
                "-L",
                "--max-time",
                str(timeout),
                "-A",
                USER_AGENT,
                "-H",
                "Content-Type: application/json",
                "--data",
                request_body,
                VARIANT_OPTIONS_URL,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        if result.returncode != 0:
            code = "TIMEOUT_READ" if "timed out" in result.stderr.lower() else "UNKNOWN"
            raise RuntimeError(f"{code}: curl failed: {result.stderr.strip()}")
        payload = json.loads(result.stdout)
    if payload.get("status") != "ok":
        response_status = payload.get("res", {}).get("status")
        if response_status == 404:
            return None, payload
        raise ValueError(f"variant option resolution failed: {payload.get('message', 'unknown error')}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("variant option response did not contain product data")
    variant_url_key = str(data.get("variantUrlKey", ""))
    if not variant_url_key:
        raise ValueError("resolved variantUrlKey was not found")
    return (
        replace(
            candidate,
            variant_url=variant_url(candidate.product_url, variant_url_key),
            variant_url_key=variant_url_key,
            candidate_status="pending",
            candidate_error="",
        ),
        data,
    )


def resolved_variant_row(
    candidate: VariantCandidate,
    payload: dict,
    raw_ref: str,
    run_id: str,
    checked_at: str,
) -> dict[str, str]:
    attributes = payload.get("attributes", {})
    if not isinstance(attributes, dict):
        attributes = {}
    price = payload.get("price", {})
    if not isinstance(price, dict):
        price = {}
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        assets = []
    image_url = next(
        (
            str(asset.get("source", ""))
            for asset in assets
            if isinstance(asset, dict) and asset.get("source")
        ),
        "",
    )
    formatted_price = str(price.get("formattedPrice", ""))
    variant_key = str(payload.get("variantKey", ""))
    return {
        "run_id": run_id,
        "source_url": candidate.variant_url,
        "source_checked_at": checked_at,
        "scrape_status": "success",
        "scrape_error_code": "",
        "scrape_error_message": "",
        "brand": "BoConcept",
        "series": str(payload.get("name", "")),
        "product_name": str(payload.get("description", "")) or str(payload.get("name", "")),
        "base_item_number": str(payload.get("productMasterKey", "")),
        "variant_id": str(payload.get("variantUrlKey", "")),
        "sku": variant_key,
        "item_number": variant_key,
        "selected_size": "",
        "selected_upholstery": candidate.selected_upholstery,
        "selected_leg": candidate.selected_leg,
        "width_cm": str(attributes.get("width", "")),
        "depth_cm": str(attributes.get("depth", "")),
        "height_cm": str(attributes.get("height", "")),
        "weight_kg": str(attributes.get("weight", "")),
        "material": str(attributes.get("productSpecification", "")),
        "list_price": formatted_price,
        "display_price": formatted_price,
        "canonical_price": formatted_price,
        "price_from": "variant_options_api",
        "currency": str(price.get("currency", "")),
        "tax_type": "tax_included" if formatted_price else "",
        "image_url": image_url,
        "pdf_url": "",
        "raw_data_ref": raw_ref,
    }


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
                    "super_master_key": candidate.super_master_key,
                    "selected_options_json": candidate.selected_options_json,
                    "selected_option_names_json": candidate.selected_option_names_json,
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
