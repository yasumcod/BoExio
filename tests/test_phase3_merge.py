import argparse
import csv
import json
import tempfile
import unittest
from pathlib import Path

from boexio.phase2_variants import CANDIDATE_COLUMNS, ERROR_COLUMNS, PHASE2_CSV_COLUMNS
from boexio.phase3_matrix import DISCOVERED_COLUMNS
from boexio.phase3_merge import (
    merge_chunks,
    merge_product_variant_completeness,
    strict_status_from_completeness,
)


CHAIR_URL = "https://www.boconcept.com/ja-jp/shop/%E3%83%81%E3%82%A7%E3%82%A2/"


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
            "category_url": CHAIR_URL,
            "variant_key": variant_key,
            "price_compare_value": "1000",
        }
    )
    return row


def full_discovery_metadata(product_limit_per_category: int = 0, variant_limit_per_product: int = 0) -> dict:
    return {
        "product_limit": 0,
        "product_limit_per_category": product_limit_per_category,
        "variant_limit_per_product": variant_limit_per_product,
        "target_categories": [
            {
                "category_name": "チェア",
                "category_url": CHAIR_URL,
                "category_slug": "chair",
            }
        ],
        "zero_product_categories": [],
        "category_completeness": {
            "chair": {
                "category_name": "チェア",
                "category_url": CHAIR_URL,
                "category_slug": "chair",
                "discovered_product_count": 1,
                "unique_discovered_product_count": 1,
                "chunk_input_product_count": 1,
                "processed_product_count": 0,
                "limit_applied": product_limit_per_category > 0,
                "discovery_complete": product_limit_per_category == 0,
                "reasons": ["product_limit_applied"] if product_limit_per_category > 0 else [],
            }
        },
    }


def chunk_metadata(
    *,
    run_status: str = "success",
    candidate_count: int = 2,
    attempt_count: int = 2,
    success_count: int = 2,
    failure_count: int = 0,
    skipped_count: int = 0,
    fetch_attempt_complete: bool = True,
    comparison_complete: bool = True,
    variant_limit_per_product: int = 0,
) -> dict:
    product_url = "https://www.boconcept.com/ja-jp/p/chair/1/"
    return {
        "run_status": run_status,
        "category_slug": "chair",
        "category_name": "チェア",
        "category_url": CHAIR_URL,
        "chunk_slug": "chair-001",
        "chunk_index": 1,
        "chunk_product_count": 1,
        "variant_limit_per_product": variant_limit_per_product,
        "variant_candidate_count": candidate_count,
        "variant_fetch_attempt_count": attempt_count,
        "variant_success_count": success_count,
        "variant_failure_count": failure_count,
        "variant_skipped_count": skipped_count,
        "product_variant_completeness": {
            product_url: {
                "category_slug": "chair",
                "category_name": "チェア",
                "category_url": CHAIR_URL,
                "product_name": "Chair",
                "product_fetch_attempt_count": 1,
                "product_fetch_success_count": 1,
                "product_fetch_failure_count": 0,
                "variant_candidate_count": candidate_count,
                "unique_variant_candidate_count": candidate_count,
                "variant_fetch_attempt_count": attempt_count,
                "variant_success_count": success_count,
                "variant_failure_count": failure_count,
                "variant_skipped_count": skipped_count,
                "variant_limit_per_product": variant_limit_per_product,
                "limit_applied": variant_limit_per_product > 0,
                "fetch_attempt_complete": fetch_attempt_complete,
                "comparison_complete": comparison_complete,
            }
        },
    }


class Phase3MergeTests(unittest.TestCase):
    def test_strict_status_fails_on_discovery_incomplete(self):
        status, reasons = strict_status_from_completeness(
            {
                "chair": {
                    "discovery_complete": False,
                    "fetch_attempt_complete": True,
                    "comparison_complete": True,
                }
            }
        )

        self.assertEqual("failed", status)
        self.assertEqual(["discovery_complete=false categories=chair"], reasons)

    def test_strict_status_still_fails_on_incomplete_fetch(self):
        status, reasons = strict_status_from_completeness(
            {
                "chair": {
                    "discovery_complete": False,
                    "fetch_attempt_complete": False,
                    "comparison_complete": True,
                }
            }
        )

        self.assertEqual("failed", status)
        self.assertEqual(
            [
                "discovery_complete=false categories=chair",
                "fetch_attempt_complete=false categories=chair",
            ],
            reasons,
        )

    def test_merge_aggregates_variant_shards_for_same_product(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks_dir = root / "chunks"
            matrix_path = root / "matrix.json"
            discovery_metadata_path = root / "discovery_metadata.json"
            out = root / "data"
            product_url = "https://www.boconcept.com/ja-jp/p/chair/1/"
            matrix_path.write_text(
                json.dumps(
                    {
                        "include": [
                            {
                                "category_name": "チェア",
                                "category_url": CHAIR_URL,
                                "category_slug": "chair",
                                "chunk_slug": "chair-001",
                                "chunk_product_count": 1,
                                "product_urls": [product_url],
                            },
                            {
                                "category_name": "チェア",
                                "category_url": CHAIR_URL,
                                "category_slug": "chair",
                                "chunk_slug": "chair-002",
                                "chunk_product_count": 1,
                                "product_urls": [product_url],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            discovery_metadata_path.write_text(json.dumps(full_discovery_metadata()), encoding="utf-8")

            for index in (1, 2):
                slug = f"chair-{index:03d}"
                chunk = chunks_dir / f"boexio-weekly-chunk-2026-05-27-{slug}"
                chunk.mkdir(parents=True)
                metadata = chunk_metadata(candidate_count=1, attempt_count=1, success_count=1)
                metadata["chunk_slug"] = slug
                metadata["product_variant_completeness"][product_url]["variant_offset"] = index - 1
                metadata["product_variant_completeness"][product_url]["variant_plan_limit"] = 1
                metadata["product_variant_completeness"][product_url]["estimated_variant_count"] = 2
                (chunk / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
                write_csv(
                    chunk / "products_current.csv",
                    PHASE2_CSV_COLUMNS,
                    [product_row(f"vk-{index}", f"url-{index}")],
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
            metadata = json.loads((out / "runs" / "merged" / "run_metadata.json").read_text(encoding="utf-8"))
            product = metadata["product_variant_completeness"][product_url]
            self.assertEqual(2, product["variant_candidate_count"])
            self.assertEqual(2, product["variant_success_count"])
            self.assertEqual(2, len(product["variant_shards"]))
            self.assertTrue(product["variant_shard_coverage_complete"])
            self.assertTrue(product["fetch_attempt_complete"])
            self.assertTrue(product["comparison_complete"])
            self.assertEqual(1, metadata["category_completeness"]["chair"]["chunk_input_product_count"])

    def test_merge_marks_missing_variant_shard_as_incomplete(self):
        product_url = "https://www.boconcept.com/ja-jp/p/chair/1/"
        completeness: dict[str, dict[str, object]] = {}
        metadata = chunk_metadata(candidate_count=1, attempt_count=1, success_count=1)
        metadata["chunk_slug"] = "chair-001"
        product = metadata["product_variant_completeness"][product_url]
        product["variant_offset"] = 0
        product["variant_plan_limit"] = 1
        product["estimated_variant_count"] = 2

        merge_product_variant_completeness(completeness, metadata)

        merged = completeness[product_url]
        self.assertFalse(merged["variant_shard_coverage_complete"])
        self.assertFalse(merged["fetch_attempt_complete"])
        self.assertIn("variant_shard_coverage_incomplete", merged["reasons"][0])

    def test_merge_keeps_plan_drift_separate_from_fetch_incomplete(self):
        product_url = "https://www.boconcept.com/ja-jp/p/chair/1/"
        completeness: dict[str, dict[str, object]] = {}
        metadata = chunk_metadata(candidate_count=202, attempt_count=202, success_count=202)
        product = metadata["product_variant_completeness"][product_url]
        product["candidate_extraction_success"] = False
        product["candidate_extraction_error"] = (
            "planned_candidate_range_mismatch offset=0 limit=206 available=202"
        )

        merge_product_variant_completeness(completeness, metadata)

        merged = completeness[product_url]
        self.assertTrue(merged["candidate_plan_drift"])
        self.assertTrue(merged["fetch_attempt_complete"])
        self.assertTrue(merged["comparison_complete"])
        self.assertIn("candidate_plan_drift=planned_candidate_range_mismatch", merged["reasons"][0])

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
            self.assertFalse(metadata["category_completeness"]["chair"]["fetch_attempt_complete"])

    def test_full_run_fetch_attempt_incomplete_fails(self):
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
                                "category_url": CHAIR_URL,
                                "category_slug": "chair",
                                "chunk_slug": "chair-001",
                                "chunk_product_count": 1,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            discovery_metadata_path.write_text(json.dumps(full_discovery_metadata()), encoding="utf-8")
            chunk = chunks_dir / "boexio-weekly-chunk-2026-05-27-chair-001"
            chunk.mkdir(parents=True)
            (chunk / "run_metadata.json").write_text(
                json.dumps(
                    chunk_metadata(
                        candidate_count=2,
                        attempt_count=1,
                        success_count=1,
                        failure_count=0,
                        fetch_attempt_complete=False,
                        comparison_complete=False,
                    )
                ),
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
            self.assertIn("chair", metadata["fetch_incomplete_categories"])

    def test_full_run_fetch_complete_with_failures_is_partial_success(self):
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
                                "category_url": CHAIR_URL,
                                "category_slug": "chair",
                                "chunk_slug": "chair-001",
                                "chunk_product_count": 1,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            discovery_metadata_path.write_text(json.dumps(full_discovery_metadata()), encoding="utf-8")
            chunk = chunks_dir / "boexio-weekly-chunk-2026-05-27-chair-001"
            chunk.mkdir(parents=True)
            (chunk / "run_metadata.json").write_text(
                json.dumps(
                    chunk_metadata(
                        run_status="partial_success",
                        candidate_count=2,
                        attempt_count=2,
                        success_count=1,
                        failure_count=1,
                        fetch_attempt_complete=True,
                        comparison_complete=False,
                    )
                ),
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

            self.assertEqual(0, exit_code)
            metadata = json.loads((out / "runs" / "merged" / "run_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual("partial_success", metadata["overall_run_status"])
            self.assertIn("chair", metadata["comparison_incomplete_categories"])
            self.assertNotIn("chair-001", metadata["failed_chunks"])

    def test_limited_run_does_not_apply_strict_full_gate(self):
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
                                "category_url": CHAIR_URL,
                                "category_slug": "chair",
                                "chunk_slug": "chair-001",
                                "chunk_product_count": 1,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            discovery_metadata_path.write_text(
                json.dumps(full_discovery_metadata(product_limit_per_category=1, variant_limit_per_product=1)),
                encoding="utf-8",
            )
            chunk = chunks_dir / "boexio-weekly-chunk-2026-05-27-chair-001"
            chunk.mkdir(parents=True)
            (chunk / "run_metadata.json").write_text(
                json.dumps(
                    chunk_metadata(
                        candidate_count=4,
                        attempt_count=1,
                        success_count=1,
                        failure_count=0,
                        skipped_count=3,
                        fetch_attempt_complete=False,
                        comparison_complete=False,
                        variant_limit_per_product=1,
                    )
                ),
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

            self.assertEqual(0, exit_code)
            metadata = json.loads((out / "runs" / "merged" / "run_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual("success", metadata["overall_run_status"])
            self.assertFalse(metadata["full_run_completeness_gate"])


if __name__ == "__main__":
    unittest.main()
