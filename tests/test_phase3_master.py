import tempfile
import unittest
from pathlib import Path

from boexio.phase3_master import (
    CategoryTarget,
    add_category_metadata,
    category_slug,
    read_target_categories,
    read_product_urls_file,
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
