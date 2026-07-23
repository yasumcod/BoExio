from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse
from xml.etree import ElementTree

from boexio.phase1_poc import validate_discovered_product_url
from boexio.phase2_variants import unescape_next_payload


SITEMAP_INDEX_URL = "https://www.boconcept.com/sitemap.xml"
PRODUCT_SITEMAP_URL = "https://www.boconcept.com/ja-jp/sitemap/products/"
SITEMAP_PRODUCT_COLUMNS = ["source_sitemap_url", "product_url", "discovery_status", "discovery_error"]
CATEGORY_EXPECTED_COLUMNS = [
    "category_name",
    "category_url",
    "category_slug",
    "expected_product_count",
    "initial_visible_product_count",
    "expected_count_status",
    "expected_count_error",
]
CATEGORY_PRODUCT_MASTER_COUNT_COLUMNS = [
    "category_name",
    "category_url",
    "category_slug",
    "product_master_name",
    "expected_count",
]
CLASSIFIED_PRODUCT_COLUMNS = [
    "product_url",
    "representative_product_url",
    "product_master_key",
    "product_master_name",
    "super_master_key",
    "bi_product_group",
    "bi_product_type",
    "item_category",
    "item_category2",
    "is_outlet",
    "canonical_url",
    "default_variant_url",
    "classification_slug",
    "classification_status",
    "classification_error",
    "dedupe_key",
    "dedupe_status",
    "representative_reason",
]


@dataclass(frozen=True)
class CategoryExpectedCount:
    category_name: str
    category_url: str
    category_slug: str
    expected_product_count: int | None
    initial_visible_product_count: int | None
    expected_count_status: str
    expected_count_error: str = ""
    expected_product_master_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ProductClassification:
    product_url: str
    product_master_key: str = ""
    product_master_name: str = ""
    super_master_key: str = ""
    bi_product_group: str = ""
    bi_product_type: str = ""
    item_category: str = ""
    item_category2: str = ""
    is_outlet: str = ""
    canonical_url: str = ""
    default_variant_url: str = ""
    is_default: bool = False
    classification_slug: str = ""
    classification_status: str = "unknown"
    classification_error: str = ""

    @property
    def dedupe_key(self) -> str:
        return self.product_master_key or self.super_master_key or self.canonical_url or self.product_url


@dataclass(frozen=True)
class DedupedProduct:
    representative: ProductClassification
    products: tuple[ProductClassification, ...]
    representative_reason: str


def _xml_locations(xml_text: str) -> list[str]:
    root = ElementTree.fromstring(xml_text)
    locations: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "loc" and element.text:
            locations.append(element.text.strip())
    return locations


def product_sitemap_url_from_index(xml_text: str, preferred_url: str = PRODUCT_SITEMAP_URL) -> str:
    locations = _xml_locations(xml_text)
    for location in locations:
        if location.rstrip("/") == preferred_url.rstrip("/"):
            return location
    for location in locations:
        parsed = urlparse(location)
        if parsed.netloc == "www.boconcept.com" and parsed.path.rstrip("/") == "/ja-jp/sitemap/products":
            return location
    raise ValueError("ja-jp product sitemap was not found in sitemap index")


def product_urls_from_sitemap(xml_text: str, source_sitemap_url: str = PRODUCT_SITEMAP_URL) -> tuple[list[str], list[dict[str, str]]]:
    product_urls: list[str] = []
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for location in _xml_locations(xml_text):
        product_url = urljoin(source_sitemap_url, location)
        valid, error_code = validate_discovered_product_url(product_url)
        if "/print/" in urlparse(product_url).path:
            valid = False
            error_code = "ROBOTS_DISALLOWED"
        if not valid:
            rows.append(
                {
                    "source_sitemap_url": source_sitemap_url,
                    "product_url": product_url,
                    "discovery_status": "failed",
                    "discovery_error": error_code,
                }
            )
            continue
        duplicate = product_url in seen
        rows.append(
            {
                "source_sitemap_url": source_sitemap_url,
                "product_url": product_url,
                "discovery_status": "duplicate" if duplicate else "success",
                "discovery_error": "duplicate_product_url" if duplicate else "",
            }
        )
        if duplicate:
            continue
        seen.add(product_url)
        product_urls.append(product_url)
    return product_urls, rows


def parse_category_expected_count(
    *,
    category_name: str,
    category_url: str,
    category_slug: str,
    html: str,
) -> CategoryExpectedCount:
    item_match = re.search(r"([0-9][0-9,]*)\s*アイテム", html)
    visible_match = re.search(r"([0-9][0-9,]*)\s*/\s*([0-9][0-9,]*)\s*製品を表示中", html)
    expected = int(item_match.group(1).replace(",", "")) if item_match else None
    initial_visible = int(visible_match.group(1).replace(",", "")) if visible_match else None
    visible_total = int(visible_match.group(2).replace(",", "")) if visible_match else None
    if expected is None and visible_total is not None:
        expected = visible_total
    errors: list[str] = []
    if expected is None:
        errors.append("expected_product_count_missing")
    if initial_visible is None:
        errors.append("initial_visible_product_count_missing")
    if item_match and visible_total is not None and expected != visible_total:
        errors.append(f"expected_count_mismatch item_count={expected} visible_total={visible_total}")
    return CategoryExpectedCount(
        category_name=category_name,
        category_url=category_url,
        category_slug=category_slug,
        expected_product_count=expected,
        initial_visible_product_count=initial_visible,
        expected_count_status="success" if not errors else "unknown",
        expected_count_error="; ".join(errors),
        expected_product_master_counts=parse_product_master_facet_counts(html),
    )


def _balanced_json_array(text: str, array_start: int) -> str:
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[array_start:], array_start):
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
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[array_start : index + 1]
    raise ValueError("balanced JSON array end not found")


def parse_product_master_facet_counts(html: str) -> dict[str, int]:
    text = unescape_next_payload(html)
    marker_index = text.find('"key":"product-master-name"')
    if marker_index == -1:
        return {}
    options_index = text.find('"options":[', marker_index)
    if options_index == -1:
        return {}
    array_start = text.find("[", options_index)
    if array_start == -1:
        return {}
    try:
        options = json.loads(_balanced_json_array(text, array_start))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    counts: dict[str, int] = {}
    for option in options:
        if not isinstance(option, dict):
            continue
        name = str(option.get("displayValue") or option.get("key") or "").strip()
        if not name:
            continue
        try:
            count = int(option.get("count", 0))
        except (TypeError, ValueError):
            continue
        counts[name] = count
    return dict(sorted(counts.items()))


def _regex_json_string(text: str, key: str) -> str:
    patterns = (
        rf'"{re.escape(key)}"\s*:\s*"([^"]*)"',
        rf'\\"{re.escape(key)}\\"\s*:\s*\\"([^\\"]*)\\"',
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return unescape(match.group(1))
    return ""


def _regex_json_bool(text: str, key: str) -> str:
    patterns = (
        rf'"{re.escape(key)}"\s*:\s*(true|false)',
        rf'\\"{re.escape(key)}\\"\s*:\s*(true|false)',
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return ""


def _canonical_url(html: str) -> str:
    patterns = (
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return unescape(match.group(1))
    return _regex_json_string(html, "canonicalUrl")


def _default_variant_url(html: str, product_url: str) -> tuple[str, bool]:
    text = unescape_next_payload(html)
    default_match = re.search(
        r'"isDefault"\s*:\s*true.{0,200}?"variantUrlKey"\s*:\s*"([^"]+)"',
        text,
        flags=re.DOTALL,
    ) or re.search(
        r'"variantUrlKey"\s*:\s*"([^"]+)".{0,200}?"isDefault"\s*:\s*true',
        text,
        flags=re.DOTALL,
    )
    if not default_match:
        return "", False
    variant_url_key = default_match.group(1)
    parts = product_url.rstrip("/").split("/")
    slug = parts[-2] if len(parts) >= 2 else ""
    return urljoin(product_url, f"/ja-jp/p/{slug}/{variant_url_key}/"), True


def classification_slug_for_metadata(
    bi_product_group: str,
    item_category: str,
    item_category2: str = "",
) -> tuple[str, str]:
    values = {
        value.strip().casefold()
        for value in (bi_product_group, item_category)
        if value.strip()
    }
    subcategory = item_category2.strip().casefold()
    if "chairs" in values or "chair" in values:
        return "chair", ""
    if "sofas" in values or "sofa" in values:
        return "sofa", ""
    if "tables" in values or "table" in values:
        return "table", ""
    if "beds" in values or "bed" in values:
        return "bed", ""
    if "storage" in values:
        return "storage", ""
    if "outdoor" in values or "outdoor furniture" in values:
        return "outdoor-furniture", ""
    if "accessories" in values or "accessory" in values:
        if subcategory in {"lamps", "lamp", "lighting"}:
            return "lamp", ""
        if subcategory in {"rugs", "rug"}:
            return "rug", ""
        return "accessories", ""
    return "", "unsupported_or_unknown_category"


def extract_product_classification(product_url: str, html: str) -> ProductClassification:
    text = unescape_next_payload(html)
    default_variant_url, is_default = _default_variant_url(html, product_url)
    product_master_key = _regex_json_string(text, "productMasterKey")
    product_master_name = _regex_json_string(text, "productMasterName")
    super_master_key = _regex_json_string(text, "superMasterKey")
    bi_product_group = _regex_json_string(text, "biProductGroup")
    bi_product_type = _regex_json_string(text, "biProductType")
    item_category = _regex_json_string(text, "itemCategory")
    item_category2 = _regex_json_string(text, "itemCategory2")
    is_outlet = _regex_json_bool(text, "isOutlet")
    canonical = _canonical_url(html)
    classification_slug, classification_error = classification_slug_for_metadata(
        bi_product_group,
        item_category,
        item_category2,
    )
    if classification_slug:
        status = "classified"
        error = ""
    else:
        status = "unknown"
        missing = [
            key
            for key, value in (
                ("biProductGroup", bi_product_group),
                ("itemCategory", item_category),
            )
            if not value
        ]
        error = classification_error
        if missing:
            error = f"metadata_missing {','.join(missing)}"
    return ProductClassification(
        product_url=product_url,
        product_master_key=product_master_key,
        product_master_name=product_master_name,
        super_master_key=super_master_key,
        bi_product_group=bi_product_group,
        bi_product_type=bi_product_type,
        item_category=item_category,
        item_category2=item_category2,
        is_outlet=is_outlet,
        canonical_url=canonical,
        default_variant_url=default_variant_url,
        is_default=is_default,
        classification_slug=classification_slug,
        classification_status=status,
        classification_error=error,
    )


def unknown_product_classification(product_url: str, error: str) -> ProductClassification:
    return ProductClassification(
        product_url=product_url,
        classification_status="unknown",
        classification_error=error,
    )


def dedupe_product_classifications(classifications: Iterable[ProductClassification]) -> dict[str, DedupedProduct]:
    groups: dict[str, list[ProductClassification]] = {}
    for classification in classifications:
        groups.setdefault(classification.dedupe_key, []).append(classification)
    deduped: dict[str, DedupedProduct] = {}
    for key, products in groups.items():
        default_products = [product for product in products if product.is_default and product.default_variant_url]
        if len(default_products) == 1:
            representative = default_products[0]
            reason = "default_variant"
        else:
            canonical_products = [product for product in products if product.canonical_url]
            if canonical_products:
                representative = canonical_products[0]
                reason = "canonical_url" if len(default_products) != 1 else "default_variant_ambiguous_canonical_url"
            else:
                representative = products[0]
                reason = "sitemap_order"
        deduped[key] = DedupedProduct(
            representative=representative,
            products=tuple(products),
            representative_reason=reason,
        )
    return deduped


def classified_rows(classifications: Iterable[ProductClassification], deduped: dict[str, DedupedProduct]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for classification in classifications:
        group = deduped.get(classification.dedupe_key)
        representative = group.representative if group else classification
        rows.append(
            {
                "product_url": classification.product_url,
                "representative_product_url": representative.default_variant_url
                or representative.canonical_url
                or representative.product_url,
                "product_master_key": classification.product_master_key,
                "product_master_name": classification.product_master_name,
                "super_master_key": classification.super_master_key,
                "bi_product_group": classification.bi_product_group,
                "bi_product_type": classification.bi_product_type,
                "item_category": classification.item_category,
                "item_category2": classification.item_category2,
                "is_outlet": classification.is_outlet,
                "canonical_url": classification.canonical_url,
                "default_variant_url": classification.default_variant_url,
                "classification_slug": classification.classification_slug,
                "classification_status": classification.classification_status,
                "classification_error": classification.classification_error,
                "dedupe_key": classification.dedupe_key,
                "dedupe_status": "representative"
                if representative.product_url == classification.product_url
                else "duplicate",
                "representative_reason": group.representative_reason if group else "sitemap_order",
            }
        )
    return rows


def category_products_from_deduped(
    deduped: dict[str, DedupedProduct],
    category_url_by_slug: dict[str, str],
) -> dict[str, list[str]]:
    products: dict[str, list[str]] = {url: [] for url in category_url_by_slug.values()}
    seen_by_slug: dict[str, set[str]] = {slug: set() for slug in category_url_by_slug}
    for key, group in deduped.items():
        slug = group.representative.classification_slug
        category_url = category_url_by_slug.get(slug)
        if not category_url or key in seen_by_slug.setdefault(slug, set()):
            continue
        seen_by_slug[slug].add(key)
        representative = group.representative
        products.setdefault(category_url, []).append(
            representative.default_variant_url or representative.canonical_url or representative.product_url
        )
    return products


def product_master_count_key(name: str) -> str:
    return unicodedata.normalize("NFKC", unquote(name)).strip().casefold()


def normalized_product_master_counts(counts: dict[str, int]) -> dict[str, tuple[str, int]]:
    normalized: dict[str, tuple[str, int]] = {}
    for display_name, count in counts.items():
        key = product_master_count_key(display_name)
        if not key:
            continue
        current_display, current_count = normalized.get(key, (display_name, 0))
        normalized[key] = (current_display, current_count + count)
    return normalized


def discovery_completeness_by_category(
    *,
    expected_counts: dict[str, CategoryExpectedCount],
    deduped: dict[str, DedupedProduct],
    product_limit_per_category: int,
    product_limit: int = 0,
) -> tuple[dict[str, dict[str, object]], list[dict[str, str]]]:
    classified_by_slug: dict[str, set[str]] = {}
    product_master_counts_by_slug: dict[str, dict[str, int]] = {}
    duplicate_by_slug: dict[str, int] = {}
    unknown_count = 0
    for key, group in deduped.items():
        slug = group.representative.classification_slug
        if not slug:
            unknown_count += len(group.products)
            continue
        classified_by_slug.setdefault(slug, set()).add(key)
        product_master_name = group.representative.product_master_name.strip()
        if product_master_name:
            counts = product_master_counts_by_slug.setdefault(slug, {})
            counts[product_master_name] = counts.get(product_master_name, 0) + 1
        duplicate_by_slug[slug] = duplicate_by_slug.get(slug, 0) + max(len(group.products) - 1, 0)

    limit_applied = product_limit_per_category > 0 or product_limit > 0
    now = datetime.now(timezone.utc).isoformat()
    completeness: dict[str, dict[str, object]] = {}
    errors: list[dict[str, str]] = []
    for slug, expected in expected_counts.items():
        classified_count = len(classified_by_slug.get(slug, set()))
        duplicate_count = duplicate_by_slug.get(slug, 0)
        expected_master_counts = expected.expected_product_master_counts
        actual_master_counts = product_master_counts_by_slug.get(slug, {})
        expected_master_counts_normalized = normalized_product_master_counts(expected_master_counts)
        actual_master_counts_normalized = normalized_product_master_counts(actual_master_counts)
        master_count_diffs = []
        for product_master_key in sorted(set(expected_master_counts_normalized) | set(actual_master_counts_normalized)):
            expected_display, expected_count = expected_master_counts_normalized.get(product_master_key, ("", 0))
            actual_display, actual_count = actual_master_counts_normalized.get(product_master_key, ("", 0))
            if expected_count == actual_count:
                continue
            product_master_name = expected_display or actual_display
            master_count_diffs.append(
                {
                    "product_master_name": product_master_name,
                    "expected": expected_count,
                    "actual": actual_count,
                    "delta": actual_count - expected_count,
                }
            )
        reasons: list[str] = []
        if limit_applied:
            reasons.append("product_limit_applied")
        if expected.expected_count_status != "success" or expected.expected_product_count is None:
            reasons.append(expected.expected_count_error or "expected_product_count_unknown")
        elif not limit_applied and expected.expected_product_count != classified_count:
            reasons.append(
                f"discovery_count_mismatch expected={expected.expected_product_count} actual={classified_count}"
            )
        if not limit_applied and master_count_diffs:
            diff_summary = ", ".join(
                f"{diff['product_master_name']} expected={diff['expected']} actual={diff['actual']}"
                for diff in master_count_diffs[:5]
            )
            if len(master_count_diffs) > 5:
                diff_summary += f", +{len(master_count_diffs) - 5} more"
            reasons.append(f"product_master_name_count_mismatch {diff_summary}")
        if not limit_applied and unknown_count:
            reasons.append(f"unknown_classification_count={unknown_count}")
        discovery_complete = not reasons
        completeness[slug] = {
            "category_name": expected.category_name,
            "category_url": expected.category_url,
            "category_slug": slug,
            "expected_product_count": expected.expected_product_count,
            "initial_visible_product_count": expected.initial_visible_product_count,
            "expected_count_status": expected.expected_count_status,
            "expected_count_error": expected.expected_count_error,
            "classified_unique_product_master_count": classified_count,
            "unknown_classification_count": unknown_count,
            "duplicate_product_url_count": duplicate_count,
            "deduped_product_count": classified_count,
            "expected_product_master_counts": dict(sorted(expected_master_counts.items())),
            "classified_product_master_name_counts": dict(sorted(actual_master_counts.items())),
            "product_master_name_count_diffs": master_count_diffs,
            "limit_applied": limit_applied,
            "discovery_complete_scope": "sitemap_expected_count",
            "discovery_complete": discovery_complete,
            "reasons": reasons,
        }
        if reasons and not limit_applied:
            code = "discovery_count_mismatch" if any("discovery_count_mismatch" in reason for reason in reasons) else "incomplete_product_discovery"
            errors.append(
                {
                    "url": expected.category_url,
                    "phase": "discovery",
                    "error_code": code,
                    "message": f"category_slug={slug} " + "; ".join(reasons),
                    "first_seen_at": now,
                    "last_seen_at": now,
                }
            )
    return completeness, errors


def write_csv_rows(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def expected_count_rows(expected_counts: Iterable[CategoryExpectedCount]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for count in expected_counts:
        rows.append(
            {
                "category_name": count.category_name,
                "category_url": count.category_url,
                "category_slug": count.category_slug,
                "expected_product_count": ""
                if count.expected_product_count is None
                else str(count.expected_product_count),
                "initial_visible_product_count": ""
                if count.initial_visible_product_count is None
                else str(count.initial_visible_product_count),
                "expected_count_status": count.expected_count_status,
                "expected_count_error": count.expected_count_error,
            }
        )
    return rows


def product_master_count_rows(expected_counts: Iterable[CategoryExpectedCount]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for count in expected_counts:
        for product_master_name, expected_count in count.expected_product_master_counts.items():
            rows.append(
                {
                    "category_name": count.category_name,
                    "category_url": count.category_url,
                    "category_slug": count.category_slug,
                    "product_master_name": product_master_name,
                    "expected_count": str(expected_count),
                }
            )
    return rows
