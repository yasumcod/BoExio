import tempfile
import unittest
from pathlib import Path

from boexio.phase3_master import CategoryTarget
from boexio.phase3_matrix import (
    ProductVariantPlan,
    chunk_product_urls,
    limited_product_urls,
    matrix_for_categories,
    matrix_for_chunks,
    matrix_for_variant_chunks,
    parse_category_slug_filter,
    pack_variant_plans,
    shard_product_variants,
    validate_chunk_matrix,
    variant_request_budget,
)


class Phase3MatrixTests(unittest.TestCase):
    def test_category_slug_filter_accepts_comma_separated_values(self):
        self.assertEqual(
            {"storage", "lamp", "outdoor-furniture"},
            parse_category_slug_filter("storage, lamp, outdoor-furniture"),
        )

    def test_category_slug_filter_ignores_empty_values(self):
        self.assertEqual({"chair"}, parse_category_slug_filter(",chair,, "))

    def test_matrix_for_categories_uses_enabled_category_shape(self):
        matrix = matrix_for_categories(
            [CategoryTarget("チェア", "https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/", "chair")]
        )

        self.assertEqual(
            {
                "include": [
                    {
                        "category_name": "チェア",
                        "category_url": "https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/",
                        "category_slug": "chair",
                    }
                ]
            },
            matrix,
        )

    def test_chunk_product_urls_splits_five_at_a_time(self):
        category = CategoryTarget("チェア", "https://example.test/chair", "chair")
        urls = [f"https://www.boconcept.com/ja-jp/p/item/{index}/" for index in range(12)]

        with tempfile.TemporaryDirectory() as directory:
            chunks = chunk_product_urls(category, urls, chunk_size=5, matrix_dir=Path(directory))

            self.assertEqual(["chair-001", "chair-002", "chair-003"], [chunk.chunk_slug for chunk in chunks])
            self.assertEqual([5, 5, 2], [len(chunk.product_urls) for chunk in chunks])
            self.assertTrue((Path(directory) / "chair-001-product-urls.txt").exists())

    def test_product_limit_zero_keeps_all_discovered_urls(self):
        urls = ["p1", "p2", "p3", "p4", "p5", "p6"]

        self.assertEqual(urls, limited_product_urls(urls, 0))
        self.assertEqual(urls[:3], limited_product_urls(urls, 3))

    def test_matrix_for_chunks_uses_product_urls_file(self):
        category = CategoryTarget("チェア", "https://example.test/chair", "chair")
        chunks = chunk_product_urls(category, ["p1"], chunk_size=5)

        matrix = matrix_for_chunks(chunks)

        self.assertEqual("chair-001", matrix["include"][0]["chunk_slug"])
        self.assertEqual("matrix/chair-001-product-urls.txt", matrix["include"][0]["product_urls_file"])
        self.assertEqual(1, matrix["include"][0]["chunk_product_count"])

    def test_large_product_is_split_by_request_budget(self):
        budget = variant_request_budget(request_interval=5, target_minutes=180)

        plans = shard_product_variants("product", 5016, budget)

        self.assertEqual(2160, budget)
        self.assertEqual([0, 2160, 4320], [plan.variant_offset for plan in plans])
        self.assertEqual([2160, 2160, 696], [plan.variant_limit for plan in plans])

    def test_pack_variant_plans_keeps_chunks_within_budget(self):
        category = CategoryTarget("ベッド", "https://example.test/bed", "bed")
        plans = [
            ProductVariantPlan("p1", 0, 1000, 1000),
            ProductVariantPlan("p2", 0, 900, 900),
            ProductVariantPlan("p3", 0, 500, 500),
        ]

        with tempfile.TemporaryDirectory() as directory:
            chunks = pack_variant_plans(
                category,
                plans,
                chunk_size=5,
                max_requests_per_chunk=2160,
                matrix_dir=Path(directory),
            )

            self.assertEqual([1900, 500], [chunk.estimated_request_count for chunk in chunks])
            self.assertTrue((Path(directory) / "bed-001-product-plan.json").exists())
            matrix = matrix_for_variant_chunks(chunks, request_interval=5)
            self.assertEqual(["p1", "p2"], matrix["include"][0]["product_urls"])
            self.assertEqual(9500, matrix["include"][0]["estimated_minimum_seconds"])

    def test_validate_chunk_matrix_rejects_empty_matrix(self):
        with self.assertRaisesRegex(ValueError, "at least one vector"):
            validate_chunk_matrix({"include": []})

        validate_chunk_matrix({"include": [{"chunk_slug": "bed-001"}]})


if __name__ == "__main__":
    unittest.main()
