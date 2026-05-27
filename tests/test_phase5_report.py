import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from boexio.phase5_report import (
    apply_current_master_metadata,
    build_worksheets,
    current_master_columns,
    summary_from_inputs,
    validate_errors_csv,
    validate_xlsx,
)
from boexio.quote_columns import QUOTE_MASTER_COLUMNS
from boexio.xlsx_writer import write_xlsx


class Phase5ReportTests(unittest.TestCase):
    def test_summary_counts_distinct_products_and_variants(self):
        rows = [
            {"series": "A", "product_name": "Chair", "scrape_status": "success"},
            {"series": "A", "product_name": "Chair", "scrape_status": "success"},
            {"series": "B", "product_name": "Stool", "scrape_status": "failed"},
        ]
        diff_summary = {
            "price_change_count": 2,
            "increase_count": 1,
            "decrease_count": 1,
            "added_count": 3,
            "removed_count": 4,
            "revived_count": 1,
            "currency_mismatch_count": 5,
            "comparison_error_count": 6,
        }

        summary = summary_from_inputs(diff_summary, rows, "2026-05-23T00:00:00+00:00")

        self.assertEqual(2, summary["target_product_count"])
        self.assertEqual(2, summary["success_count"])
        self.assertEqual(1, summary["failure_count"])
        self.assertEqual(3, summary["current_row_count"])
        self.assertEqual(5, summary["currency_mismatch_count"])

    def test_workbook_contains_required_sheets(self):
        worksheets = build_worksheets(
            {"generated_at": "2026-05-23T00:00:00+00:00"},
            {},
            [],
            [],
            [],
            [{"series": "A", "product_name": "Chair", "scrape_status": "success"}],
            [],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "report.xlsx"
            write_xlsx(path, worksheets)
            validate_xlsx(path, expected_sheet_count=6)
            with zipfile.ZipFile(path) as archive:
                workbook_xml = archive.read("xl/workbook.xml").decode()

        self.assertEqual(
            ["summary", "price_changes", "added", "removed", "current_master", "errors"],
            re.findall(r'name="([^"]+)"', workbook_xml),
        )

    def test_current_master_uses_phase7_standard_column_order(self):
        self.assertEqual(QUOTE_MASTER_COLUMNS, current_master_columns([]))

    def test_current_master_outputs_missing_standard_columns_as_blank(self):
        worksheets = build_worksheets(
            {"generated_at": "2026-05-23T00:00:00+00:00"},
            {},
            [],
            [],
            [],
            [
                {
                    "variant_key": "variant-1",
                    "sku": "sku-1",
                    "item_number": "item-1",
                    "brand": "BoConcept",
                    "series": "Catskills",
                    "product_name": "Chair",
                    "selected_upholstery": "Fabric",
                    "selected_leg": "Oak",
                    "price_compare_value": "123000",
                    "price_compare_from": "canonical_price",
                    "currency": "JPY",
                    "tax_type": "tax_included",
                    "source_url": "https://www.boconcept.com/ja-jp/p/chair/variant/",
                    "source_checked_at": "2026-05-23T00:00:00+00:00",
                    "run_id": "phase7-test",
                }
            ],
            [],
        )
        current_master = worksheets[4]
        values = dict(zip(current_master.rows[0], current_master.rows[1]))

        self.assertEqual(QUOTE_MASTER_COLUMNS, current_master.rows[0])
        self.assertEqual("", values["current_state"])
        self.assertEqual("", values["missing_streak"])
        self.assertEqual("", values["parser_version"])
        self.assertEqual("", values["schema_version"])

    def test_current_master_keeps_source_url_audit_and_run_tracking_columns(self):
        required = {
            "source_url",
            "run_id",
            "source_checked_at",
            "parser_version",
            "schema_version",
            "price_compare_value",
            "price_compare_from",
            "currency",
            "tax_type",
        }

        self.assertTrue(required.issubset(set(current_master_columns([]))))

    def test_current_master_can_fill_parser_and_schema_from_metadata(self):
        rows = apply_current_master_metadata(
            [{"variant_key": "variant-1", "parser_version": "", "schema_version": ""}],
            {"parser_version": "0.3.0", "schema_version": "0.1.0"},
        )

        self.assertEqual("0.3.0", rows[0]["parser_version"])
        self.assertEqual("0.1.0", rows[0]["schema_version"])

    def test_current_master_marks_blank_source_url_for_manual_review(self):
        worksheets = build_worksheets(
            {"generated_at": "2026-05-23T00:00:00+00:00"},
            {},
            [],
            [],
            [],
            [{"variant_key": "variant-1", "source_url": ""}],
            [],
        )
        current_master = worksheets[4]
        values = dict(zip(current_master.rows[0], current_master.rows[1]))

        self.assertEqual("yes", values["source_url_review_required"])
        self.assertNotIn("pdf_url", current_master.rows[0])

    def test_errors_csv_missing_required_columns_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "errors.csv"
            path.write_text("url,phase,error_code\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "missing required columns"):
                validate_errors_csv(path)


if __name__ == "__main__":
    unittest.main()
