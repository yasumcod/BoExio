import tempfile
import unittest
from pathlib import Path

from boexio.phase3_master import (
    CategoryTarget,
    add_category_metadata,
    read_target_categories,
    select_products_by_category,
)


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
            [CategoryTarget("チェア", "https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/")],
            targets,
        )

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
