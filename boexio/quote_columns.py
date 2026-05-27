from __future__ import annotations


QUOTE_MASTER_COLUMNS = [
    # Identification
    "variant_key",
    "variant_key_from",
    "sku",
    "item_number",
    # Product
    "brand",
    "category_name",
    "category_url",
    "series",
    "product_name",
    # Configuration
    "selected_size",
    "selected_upholstery",
    "selected_leg",
    # Price
    "price_compare_value",
    "price_compare_from",
    "currency",
    "tax_type",
    "list_price",
    "display_price",
    "canonical_price",
    # State
    "scrape_status",
    "current_state",
    "missing_streak",
    "source_url_review_required",
    # Reference
    "source_url",
    "image_url",
    "raw_data_ref",
    # Audit
    "source_checked_at",
    "run_id",
    "parser_version",
    "schema_version",
]


def quote_master_row(row: dict[str, str]) -> dict[str, str]:
    output = {column: row.get(column, "") for column in QUOTE_MASTER_COLUMNS}
    output["source_url_review_required"] = "yes" if not output["source_url"].strip() else ""
    return output


def quote_master_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [quote_master_row(row) for row in rows]
