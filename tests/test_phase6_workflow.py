import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from boexio.phase2_variants import PHASE2_CSV_COLUMNS
from boexio.phase6_workflow import (
    PhaseResult,
    copy_if_exists,
    overall_run_status,
    prepare_previous,
    release_body,
    release_name_for_date,
    release_tag_for_date,
    stage_phase_outputs,
    write_empty_previous_csv,
)


class Phase6WorkflowTests(unittest.TestCase):
    def test_release_names_use_weekly_date(self):
        run_date = date(2026, 5, 24)

        self.assertEqual("weekly-2026-05-24", release_tag_for_date(run_date))
        self.assertEqual("BoExio Weekly Report 2026-05-24", release_name_for_date(run_date))

    def test_empty_previous_csv_uses_phase2_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "previous.csv"

            write_empty_previous_csv(path)

            with path.open(encoding="utf-8", newline="") as file:
                reader = csv.DictReader(file)
                self.assertEqual(PHASE2_CSV_COLUMNS, reader.fieldnames)
                self.assertEqual([], list(reader))

    def test_prepare_previous_copies_downloaded_csv_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloaded_csv = root / "downloaded.csv"
            downloaded_metadata = root / "downloaded.json"
            output_csv = root / "out" / "previous.csv"
            output_metadata = root / "out" / "previous.json"
            downloaded_csv.write_text("a,b\n1,2\n", encoding="utf-8")
            downloaded_metadata.write_text('{"schema_version":"0.1.0"}\n', encoding="utf-8")

            prepare_previous(downloaded_csv, output_csv, downloaded_metadata, output_metadata)

            self.assertEqual(downloaded_csv.read_text(encoding="utf-8"), output_csv.read_text(encoding="utf-8"))
            self.assertEqual(
                downloaded_metadata.read_text(encoding="utf-8"),
                output_metadata.read_text(encoding="utf-8"),
            )

    def test_overall_status_fails_on_validation_or_phase_failure(self):
        result = PhaseResult("phase3", Path("x"), 0, "success", Path("x/run_metadata.json"))

        self.assertEqual("success", overall_run_status([result], {"tests": 0}))
        self.assertEqual("failed", overall_run_status([result], {"tests": 1}))
        self.assertEqual(
            "failed",
            overall_run_status([PhaseResult("phase3", Path("x"), 0, "failed", None)], {"tests": 0}),
        )
        self.assertEqual(
            "partial_success",
            overall_run_status([PhaseResult("phase3", Path("x"), 0, "partial_success", None)], {"tests": 0}),
        )

    def test_workflow_final_gate_allows_partial_success(self):
        repo_root = Path(__file__).resolve().parents[1]
        workflow = (repo_root / ".github/workflows/boexio-weekly.yml").read_text(encoding="utf-8")

        self.assertIn("success|partial_success", workflow)

    def test_workflow_has_chair_full_profile_before_all_full(self):
        repo_root = Path(__file__).resolve().parents[1]
        workflow = (repo_root / ".github/workflows/boexio-weekly.yml").read_text(encoding="utf-8")

        self.assertIn('default: "chair-full"', workflow)
        self.assertIn("chair-full)", workflow)
        self.assertIn('category_slug="chair"', workflow)
        self.assertIn("all-full)", workflow)
        self.assertIn('discovery_mode="sitemap"', workflow)

    def test_release_body_lists_comparison_incomplete_categories(self):
        body = release_body(
            {
                "release_name": "BoExio Weekly Report 2026-05-24",
                "overall_run_status": "partial_success",
                "run_id": "weekly-2026-05-24-1",
                "previous_release_tag": "",
                "phase_results": [],
                "missing_categories": [],
                "missing_chunks": [],
                "failed_chunks": [],
                "comparison_incomplete_categories": ["sofa"],
            }
        )

        self.assertIn("comparison_complete_false_categories: `sofa`", body)

    def test_stage_phase_outputs_copies_stable_asset_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            phase3 = root / "phase3"
            phase4 = root / "phase4"
            phase5 = root / "phase5"
            logs = root / "logs"
            out = root / "artifacts"
            for path in (phase3, phase4, phase5, logs):
                path.mkdir()
            (phase3 / "products_current.csv").write_text("current\n", encoding="utf-8")
            (phase3 / "products_2026-05-24_run.csv").write_text("snapshot\n", encoding="utf-8")
            (phase3 / "run_metadata.json").write_text(json.dumps({"run_status": "success"}), encoding="utf-8")
            (phase4 / "diff_summary.json").write_text("{}\n", encoding="utf-8")
            (phase5 / "weekly_report_2026-05-24_run.xlsx").write_bytes(b"fake")
            (logs / "phase3.log").write_text("log\n", encoding="utf-8")

            copied = stage_phase_outputs(phase3, phase4, phase5, logs, out)

            self.assertIn("phase3_products_current.csv", copied)
            self.assertIn("phase3_products_snapshot.csv", copied)
            self.assertIn("phase4_diff_summary.json", copied)
            self.assertIn("phase5_weekly_report.xlsx", copied)
            self.assertIn("workflow_phase3.log", copied)

    def test_copy_if_exists_replaces_empty_files_with_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "empty.log"
            destination = root / "out" / "empty.log"
            source.write_text("", encoding="utf-8")

            self.assertTrue(copy_if_exists(source, destination))

            self.assertGreater(destination.stat().st_size, 0)
            self.assertIn("was generated but empty", destination.read_text(encoding="utf-8"))

    def test_copy_if_exists_writes_csv_with_utf8_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            destination = root / "out" / "phase4_price_changes.csv"
            source.write_text("product_name\n日本語の商品\n", encoding="utf-8")

            self.assertTrue(copy_if_exists(source, destination))

            self.assertTrue(destination.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertIn("日本語の商品", destination.read_text(encoding="utf-8-sig"))

    def test_copy_if_exists_preserves_existing_utf8_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            destination = root / "out" / "phase3_products_current.csv"
            source.write_text("product_name\n日本語の商品\n", encoding="utf-8-sig")

            self.assertTrue(copy_if_exists(source, destination))

            self.assertEqual(1, destination.read_bytes().count(b"\xef\xbb\xbf"))


if __name__ == "__main__":
    unittest.main()
