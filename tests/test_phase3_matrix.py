import tempfile
import unittest
from pathlib import Path

from boexio.phase3_master import CategoryTarget
from boexio.phase3_matrix import chunk_product_urls, limited_product_urls, matrix_for_categories, matrix_for_chunks


class Phase3MatrixTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
