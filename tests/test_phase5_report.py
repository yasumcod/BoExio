import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from boexio.phase5_report import build_worksheets, summary_from_inputs, validate_errors_csv, validate_xlsx
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

    def test_errors_csv_missing_required_columns_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "errors.csv"
            path.write_text("url,phase,error_code\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "missing required columns"):
                validate_errors_csv(path)


if __name__ == "__main__":
    unittest.main()
