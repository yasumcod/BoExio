import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from boexio.phase3_master import (
    CategoryTarget,
    ProductRunPlan,
    RateLimiter,
    add_category_metadata,
    category_slug,
    checkpoint_raw_path,
    product_variant_completeness_entry,
    read_product_plan_file,
    read_target_categories,
    read_product_urls_file,
    resolve_candidate_with_control,
    select_planned_candidates,
    select_products_by_category,
    select_variant_candidates,
)
from boexio.phase2_variants import VariantCandidate


class Phase3MasterTests(unittest.TestCase):
    def test_read_target_categories_supports_csv_and_enabled_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "target_categories.csv"
            path.write_text(
                "category_name,category_url,enabled\n"
                "チェア,https://www.boconcept.com/ja-jp/shop/チェア/,true\n"
                "無効,https://www.boconcept.com/ja-jp/shop/無効/,false\n",
                encoding="utf-8",
            )

            targets = read_target_categories(path)

        self.assertEqual(
            [
                CategoryTarget(
                    "チェア",
                    "https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/",
                    "chair",
                )
            ],
            targets,
        )

    def test_category_slug_is_stable_ascii(self):
        self.assertEqual(
            "chair",
            category_slug("チェア", "https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/"),
        )
        fallback = category_slug("未知カテゴリ", "https://www.boconcept.com/ja-jp/shop/%E6%9C%AA%E7%9F%A5/")
        self.assertRegex(fallback, r"^category-[0-9a-f]{10}$")
        self.assertTrue(fallback.isascii())

    def test_select_products_by_category_takes_limit_per_category(self):
        selected = select_products_by_category(
            {
                "chairs": ["chair-1", "chair-2", "chair-3", "chair-4"],
                "sofas": ["sofa-1", "sofa-2", "sofa-3", "sofa-4"],
            },
            limit_per_category=3,
            global_limit=0,
        )

        self.assertEqual(["chair-1", "chair-2", "chair-3", "sofa-1", "sofa-2", "sofa-3"], selected)

    def test_select_products_by_category_deduplicates_across_categories(self):
        selected = select_products_by_category(
            {
                "chairs": ["shared", "chair-2", "chair-3"],
                "sofas": ["shared", "sofa-2", "sofa-3", "sofa-4"],
            },
            limit_per_category=3,
            global_limit=0,
        )

        self.assertEqual(["shared", "chair-2", "chair-3", "sofa-2", "sofa-3", "sofa-4"], selected)

    def test_product_limit_per_category_zero_selects_all_products(self):
        selected = select_products_by_category(
            {"chairs": ["chair-1", "chair-2", "chair-3"]},
            limit_per_category=0,
            global_limit=0,
        )

        self.assertEqual(["chair-1", "chair-2", "chair-3"], selected)

    def test_read_product_urls_file_uses_only_file_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "product_urls.txt"
            path.write_text(
                "https://www.boconcept.com/ja-jp/p/catskills/4060001-9:0708s-14:3320/\n"
                "\n"
                "# comment\n"
                "https://www.boconcept.com/ja-jp/p/hamilton/123/\n",
                encoding="utf-8",
            )

            urls = read_product_urls_file(path)

        self.assertEqual(
            [
                "https://www.boconcept.com/ja-jp/p/catskills/4060001-9:0708s-14:3320/",
                "https://www.boconcept.com/ja-jp/p/hamilton/123/",
            ],
            urls,
        )

    def test_variant_limit_per_product_zero_selects_all_candidates(self):
        candidates = [
            VariantCandidate("p", "v1", "k1", "", "", "", ""),
            VariantCandidate("p", "v2", "k2", "", "", "", ""),
            VariantCandidate("p", "bad", "k3", "", "", "", "", candidate_status="invalid"),
        ]

        self.assertEqual(candidates[:2], select_variant_candidates(candidates, 0))
        self.assertEqual(candidates[:1], select_variant_candidates(candidates, 1))

    def test_product_plan_selects_deterministic_candidate_range(self):
        candidates = [
            VariantCandidate("p", f"v{index}", f"k{index}", "", "", "", "")
            for index in range(10)
        ]

        selected, offset = select_planned_candidates(
            candidates,
            ProductRunPlan("p", variant_offset=3, variant_limit=4, estimated_variant_count=10),
            limit_per_product=0,
        )

        self.assertEqual(3, offset)
        self.assertEqual(["k3", "k4", "k5", "k6"], [candidate.variant_url_key for candidate in selected])

    def test_variant_option_timeout_is_retried_by_controlled_resolver(self):
        candidate = VariantCandidate("p", "v", "k", "", "", "", "", super_master_key="SM1")

        with patch(
            "boexio.phase3_master.resolve_candidate",
            side_effect=[RuntimeError("TIMEOUT_READ: variant options API: timeout"), (candidate, {"status": "ok"})],
        ) as mocked:
            resolved, payload = resolve_candidate_with_control(
                candidate,
                timeout=10,
                retries=1,
                limiter=RateLimiter(0),
            )

        self.assertEqual(candidate, resolved)
        self.assertEqual({"status": "ok"}, payload)
        self.assertEqual(2, mocked.call_count)

    def test_read_product_plan_file_and_checkpoint_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "plan.json"
            path.write_text(
                '{"products":[{"product_url":"p","variant_offset":2160,'
                '"variant_limit":696,"estimated_variant_count":5016}]}',
                encoding="utf-8",
            )

            plans = read_product_plan_file(path)

            self.assertEqual(ProductRunPlan("p", 2160, 696, 5016), plans[0])
            self.assertEqual(
                root / "variant_002_002161.json",
                checkpoint_raw_path(root, product_index=2, candidate_index=2161),
            )

    def test_product_variant_completeness_marks_complete_attempts(self):
        entry = product_variant_completeness_entry(
            product_url="https://www.boconcept.com/ja-jp/p/example/1/",
            category=CategoryTarget("ソファ", "https://www.boconcept.com/ja-jp/shop/sofa/", "sofa"),
            product_fetch_attempt_count=1,
            product_fetch_success_count=1,
            variant_candidate_count=2,
            unique_variant_candidate_count=2,
            variant_fetch_attempt_count=2,
            variant_success_count=2,
            variant_failure_count=0,
            variant_skipped_count=0,
            variant_limit_per_product=0,
        )

        self.assertTrue(entry["fetch_attempt_complete"])
        self.assertTrue(entry["comparison_complete"])

    def test_product_variant_completeness_keeps_comparison_separate_from_attempts(self):
        entry = product_variant_completeness_entry(
            product_url="https://www.boconcept.com/ja-jp/p/example/1/",
            category=CategoryTarget("ソファ", "https://www.boconcept.com/ja-jp/shop/sofa/", "sofa"),
            product_fetch_attempt_count=1,
            product_fetch_success_count=1,
            variant_candidate_count=2,
            unique_variant_candidate_count=2,
            variant_fetch_attempt_count=2,
            variant_success_count=1,
            variant_failure_count=1,
            variant_skipped_count=0,
            variant_limit_per_product=0,
        )

        self.assertTrue(entry["fetch_attempt_complete"])
        self.assertFalse(entry["comparison_complete"])

    def test_product_variant_completeness_detects_fetch_attempt_mismatch(self):
        entry = product_variant_completeness_entry(
            product_url="https://www.boconcept.com/ja-jp/p/example/1/",
            category=CategoryTarget("ソファ", "https://www.boconcept.com/ja-jp/shop/sofa/", "sofa"),
            product_fetch_attempt_count=1,
            product_fetch_success_count=1,
            variant_candidate_count=2,
            unique_variant_candidate_count=2,
            variant_fetch_attempt_count=1,
            variant_success_count=1,
            variant_failure_count=0,
            variant_skipped_count=0,
            variant_limit_per_product=0,
        )

        self.assertFalse(entry["fetch_attempt_complete"])
        self.assertFalse(entry["candidate_attempt_equation_ok"])

    def test_variant_limit_records_intentionally_skipped_candidates(self):
        entry = product_variant_completeness_entry(
            product_url="https://www.boconcept.com/ja-jp/p/example/1/",
            category=CategoryTarget("ソファ", "https://www.boconcept.com/ja-jp/shop/sofa/", "sofa"),
            product_fetch_attempt_count=1,
            product_fetch_success_count=1,
            variant_candidate_count=4,
            unique_variant_candidate_count=4,
            variant_fetch_attempt_count=1,
            variant_success_count=1,
            variant_failure_count=0,
            variant_skipped_count=3,
            variant_limit_per_product=1,
        )

        self.assertTrue(entry["limit_applied"])
        self.assertEqual(3, entry["variant_skipped_count"])
        self.assertFalse(entry["fetch_attempt_complete"])

    def test_candidate_extraction_failure_is_not_complete(self):
        entry = product_variant_completeness_entry(
            product_url="https://www.boconcept.com/ja-jp/p/example/1/",
            category=CategoryTarget("ソファ", "https://www.boconcept.com/ja-jp/shop/sofa/", "sofa"),
            product_fetch_attempt_count=1,
            product_fetch_success_count=1,
            variant_candidate_count=1,
            unique_variant_candidate_count=1,
            variant_invalid_candidate_count=1,
            variant_fetch_attempt_count=0,
            variant_success_count=0,
            variant_failure_count=0,
            variant_skipped_count=0,
            variant_limit_per_product=0,
            candidate_extraction_success=False,
            candidate_extraction_error="SCHEMA_MISMATCH",
        )

        self.assertFalse(entry["fetch_attempt_complete"])
        self.assertFalse(entry["comparison_complete"])
        self.assertIn("candidate_extraction_failed=SCHEMA_MISMATCH", entry["reasons"])

    def test_planned_candidate_range_drift_does_not_block_completed_fetch(self):
        entry = product_variant_completeness_entry(
            product_url="https://www.boconcept.com/ja-jp/p/example/1/",
            category=CategoryTarget("チェア", "https://www.boconcept.com/ja-jp/shop/chair/", "chair"),
            product_fetch_attempt_count=1,
            product_fetch_success_count=1,
            variant_candidate_count=202,
            unique_variant_candidate_count=202,
            variant_fetch_attempt_count=202,
            variant_success_count=202,
            variant_failure_count=0,
            variant_skipped_count=0,
            variant_limit_per_product=0,
            candidate_extraction_success=False,
            candidate_extraction_error="planned_candidate_range_mismatch offset=0 limit=206 available=202",
        )

        self.assertTrue(entry["candidate_plan_drift"])
        self.assertTrue(entry["fetch_attempt_complete"])
        self.assertTrue(entry["comparison_complete"])
        self.assertIn(
            "candidate_plan_drift=planned_candidate_range_mismatch offset=0 limit=206 available=202",
            entry["reasons"],
        )
        self.assertNotIn(
            "candidate_extraction_failed=planned_candidate_range_mismatch offset=0 limit=206 available=202",
            entry["reasons"],
        )

    def test_add_category_metadata_preserves_source_row(self):
        row = {"source_url": "https://example.test/product"}
        enriched = add_category_metadata(
            row,
            CategoryTarget("ソファ", "https://www.boconcept.com/ja-jp/shop/%E3%82%BD%E3%83%95%E3%82%A1/"),
        )

        self.assertEqual("ソファ", enriched["category_name"])
        self.assertEqual("https://www.boconcept.com/ja-jp/shop/%E3%82%BD%E3%83%95%E3%82%A1/", enriched["category_url"])
        self.assertNotIn("category_name", row)


if __name__ == "__main__":
    unittest.main()
