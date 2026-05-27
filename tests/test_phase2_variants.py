import csv
import unittest
from pathlib import Path

from boexio.phase1_poc import FetchResult, parse_product
from boexio.phase2_variants import enrich_row, generate_variant_key, normalize_attribute
from boexio.phase2_variants import extract_candidates


FIXTURE_DIR = Path(__file__).parent / "fixtures"
CSV_FIXTURE = FIXTURE_DIR / "phase2_products_fixture.csv"
HTML_FIXTURE = FIXTURE_DIR / "phase2_product_fixture.html"


class Phase2VariantTests(unittest.TestCase):
    def test_normalize_attribute_applies_nfkc_synonyms_and_separator_rules(self):
        normalized = normalize_attribute("  Ｆａｂｒｉｃ／自然・無垢材オーク脚  ")

        self.assertEqual("fabric natural solid wood oak脚", normalized)

    def test_generate_variant_key_prefers_variant_id_then_sku(self):
        self.assertEqual(("variant-1", "variant_id", "", ""), generate_variant_key({"variant_id": " variant-1 ", "sku": "sku-1"}))
        self.assertEqual(("sku-1", "sku", "", ""), generate_variant_key({"variant_id": "", "sku": " sku-1 "}))

    def test_generate_variant_key_falls_back_to_normalized_attributes(self):
        key, source, error_type, error_detail = generate_variant_key(
            {
                "item_number": " ITM-001 ",
                "selected_size": "Large",
                "selected_upholstery": "ファブリック／自然",
                "selected_leg": "無垢材オーク脚",
            }
        )

        self.assertEqual("itm 001|large|fabric natural|solid wood oak脚", key)
        self.assertEqual("normalized_attributes", source)
        self.assertEqual("", error_type)
        self.assertEqual("", error_detail)

    def test_generate_variant_key_reports_missing_required_attributes(self):
        key, source, error_type, error_detail = generate_variant_key(
            {
                "item_number": "ITM-001",
                "selected_size": "",
                "selected_upholstery": "fabric",
                "selected_leg": "",
            }
        )

        self.assertEqual("", key)
        self.assertEqual("", source)
        self.assertEqual("missing_required_attribute", error_type)
        self.assertIn("selected_size", error_detail)
        self.assertIn("selected_leg", error_detail)

    def test_enrich_row_from_fixture_generates_comparable_key_and_price(self):
        with CSV_FIXTURE.open(encoding="utf-8", newline="") as file:
            source = next(csv.DictReader(file))

        enriched = enrich_row(source)

        self.assertEqual("itm 001|large|fabric natural|solid wood oak脚", enriched["variant_key"])
        self.assertEqual("normalized_attributes", enriched["variant_key_from"])
        self.assertEqual("1000", enriched["price_compare_value"])
        self.assertEqual("canonical_price", enriched["price_compare_from"])
        self.assertEqual("", enriched["price_normalization_error"])

    def test_parse_product_from_html_fixture(self):
        html = HTML_FIXTURE.read_text(encoding="utf-8")
        row = parse_product(
            FetchResult(
                url="https://www.boconcept.com/ja-jp/p/catskills/4060001-9_0708s-14_2063/",
                html=html,
                checked_at="2026-05-26T00:00:00+00:00",
            ),
            "tests/fixtures/phase2_product_fixture.html",
            "fixture-run",
        )

        self.assertEqual("Catskills チェア", row["product_name"])
        self.assertEqual("Catskills", row["series"])
        self.assertEqual("4060001-9_0708s-14_2063", row["variant_id"])
        self.assertEqual("SKU-2063", row["sku"])
        self.assertEqual("4060001", row["item_number"])
        self.assertEqual("ファブリック 自然", row["selected_upholstery"])
        self.assertEqual("オーク脚", row["selected_leg"])
        self.assertEqual("¥1000", row["canonical_price"])
        self.assertEqual("JPY", row["currency"])
        self.assertEqual("https://images.example.test/catskills.jpg", row["image_url"])
        self.assertEqual("", row["pdf_url"])

    def test_extract_candidates_from_html_fixture(self):
        html = HTML_FIXTURE.read_text(encoding="utf-8")

        candidates = extract_candidates(
            "https://www.boconcept.com/ja-jp/p/catskills/4060001-9_0708s-14_2063/",
            html,
        )

        self.assertEqual(4, len(candidates))
        self.assertEqual(
            "https://www.boconcept.com/ja-jp/p/catskills/4060001-9_0708s-14_2063/",
            candidates[0].variant_url,
        )
        self.assertEqual("オーク脚", candidates[0].selected_leg)
        self.assertEqual("ファブリック 自然", candidates[0].selected_upholstery)
        self.assertEqual("pending", candidates[0].candidate_status)
        self.assertIn("4060001-9_0702s-14_2065", [candidate.variant_url_key for candidate in candidates])


if __name__ == "__main__":
    unittest.main()
