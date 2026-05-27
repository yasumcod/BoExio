import argparse
import csv
import json
import tempfile
import unittest
from pathlib import Path

from boexio.phase2_variants import CANDIDATE_COLUMNS, ERROR_COLUMNS, PHASE2_CSV_COLUMNS
from boexio.phase3_matrix import DISCOVERED_COLUMNS
from boexio.phase3_merge import merge_chunks


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def product_row(variant_key: str, source_url: str, category_name: str = "チェア") -> dict[str, str]:
    row = {column: "" for column in PHASE2_CSV_COLUMNS}
    row.update(
        {
            "run_id": "chunk-run",
            "source_url": source_url,
            "scrape_status": "success",
            "category_name": category_name,
            "category_url": "https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/",
            "variant_key": variant_key,
            "price_compare_value": "1000",
        }
    )
    return row


class Phase3MergeTests(unittest.TestCase):
    def test_merge_chunks_combines_csv_and_records_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks_dir = root / "chunks"
            matrix_path = root / "matrix.json"
            discovery_metadata_path = root / "discovery_metadata.json"
            out = root / "data"
            matrix_path.write_text(
                json.dumps(
                    {
                        "include": [
                            {
                                "category_name": "チェア",
                                "category_url": "https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/",
                                "category_slug": "chair",
                                "chunk_index": 1,
                                "chunk_slug": "chair-001",
                                "chunk_product_count": 2,
                                "product_urls_file": "matrix/chair-001-product-urls.txt",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            discovery_metadata_path.write_text(
                json.dumps(
                    {
                        "target_categories": [
                            {
                                "category_name": "チェア",
                                "category_url": "https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/",
                                "category_slug": "chair",
                            }
                        ],
                        "zero_product_categories": [],
                    }
                ),
                encoding="utf-8",
            )
            chunk = chunks_dir / "boexio-weekly-chunk-2026-05-27-chair-001"
            chunk.mkdir(parents=True)
            (chunk / "run_metadata.json").write_text(
                json.dumps(
                    {
                        "run_status": "success",
                        "category_slug": "chair",
                        "category_name": "チェア",
                        "chunk_slug": "chair-001",
                        "chunk_index": 1,
                        "chunk_product_count": 2,
                    }
                ),
                encoding="utf-8",
            )
            write_csv(
                chunk / "products_current.csv",
                PHASE2_CSV_COLUMNS,
                [
                    product_row("vk-1", "https://www.boconcept.com/ja-jp/p/a/1/"),
                    product_row("vk-1", "https://www.boconcept.com/ja-jp/p/b/1/"),
                    product_row("vk-2", "https://www.boconcept.com/ja-jp/p/a/1/"),
                ],
            )
            write_csv(chunk / "variant_candidates.csv", CANDIDATE_COLUMNS, [])
            write_csv(chunk / "discovered_product_urls.csv", DISCOVERED_COLUMNS, [])
            write_csv(chunk / "errors.csv", ERROR_COLUMNS, [])

            exit_code = merge_chunks(
                argparse.Namespace(
                    chunks_dir=str(chunks_dir),
                    matrix_json=str(matrix_path),
                    discovery_metadata=str(discovery_metadata_path),
                    output_dir=str(out),
                    run_id="merged",
                )
            )

            self.assertEqual(0, exit_code)
            run_dir = out / "runs" / "merged"
            with (run_dir / "products_current.csv").open(encoding="utf-8", newline="") as file:
                merged_rows = list(csv.DictReader(file))
            self.assertEqual(["vk-1"], [row["variant_key"] for row in merged_rows])
            with (run_dir / "errors.csv").open(encoding="utf-8", newline="") as file:
                error_rows = list(csv.DictReader(file))
            self.assertEqual(
                ["duplicate_variant_key", "duplicate_source_url"],
                [row["error_code"] for row in error_rows],
            )
            metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual("partial_success", metadata["overall_run_status"])
            self.assertEqual({"チェア": 1}, metadata["category_product_row_counts"])
            self.assertEqual(1, metadata["chunk_product_row_counts"]["chair-001"]["accepted_product_rows"])

    def test_merge_metadata_records_missing_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks_dir = root / "chunks"
            matrix_path = root / "matrix.json"
            discovery_metadata_path = root / "discovery_metadata.json"
            out = root / "data"
            matrix_path.write_text(
                json.dumps(
                    {
                        "include": [
                            {"category_slug": "chair", "chunk_slug": "chair-001", "chunk_product_count": 1},
                            {"category_slug": "chair", "chunk_slug": "chair-002", "chunk_product_count": 1},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            discovery_metadata_path.write_text(
                json.dumps(
                    {
                        "target_categories": [{"category_slug": "chair"}],
                        "zero_product_categories": [],
                    }
                ),
                encoding="utf-8",
            )
            chunk = chunks_dir / "boexio-weekly-chunk-2026-05-27-chair-001"
            chunk.mkdir(parents=True)
            (chunk / "run_metadata.json").write_text(
                json.dumps({"run_status": "success", "chunk_slug": "chair-001"}),
                encoding="utf-8",
            )
            write_csv(chunk / "products_current.csv", PHASE2_CSV_COLUMNS, [product_row("vk-1", "url-1")])
            write_csv(chunk / "variant_candidates.csv", CANDIDATE_COLUMNS, [])
            write_csv(chunk / "discovered_product_urls.csv", DISCOVERED_COLUMNS, [])
            write_csv(chunk / "errors.csv", ERROR_COLUMNS, [])

            exit_code = merge_chunks(
                argparse.Namespace(
                    chunks_dir=str(chunks_dir),
                    matrix_json=str(matrix_path),
                    discovery_metadata=str(discovery_metadata_path),
                    output_dir=str(out),
                    run_id="merged",
                )
            )

            self.assertEqual(1, exit_code)
            metadata = json.loads((out / "runs" / "merged" / "run_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual("failed", metadata["overall_run_status"])
            self.assertEqual(["chair-002"], metadata["missing_chunks"])


if __name__ == "__main__":
    unittest.main()
