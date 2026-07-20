import csv
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from boexio.phase1_poc import FetchResult, parse_product, request_safe_url
from boexio.phase2_variants import (
    VariantCandidate,
    enrich_row,
    extract_candidates,
    generate_variant_key,
    normalize_attribute,
    resolve_candidate,
    resolved_variant_row,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"
CSV_FIXTURE = FIXTURE_DIR / "phase2_products_fixture.csv"
HTML_FIXTURE = FIXTURE_DIR / "phase2_product_fixture.html"


class Phase2VariantTests(unittest.TestCase):
    def test_request_safe_url_percent_encodes_non_ascii_path(self):
        self.assertEqual(
            "https://www.boconcept.com/ja-jp/p/boucl%C3%A9-single/107_19014480-1:23-2:187/",
            request_safe_url("https://www.boconcept.com/ja-jp/p/bouclé-single/107_19014480-1:23-2:187/"),
        )
        self.assertEqual(
            "https://www.boconcept.com/ja-jp/p/canc%C3%BAn/3000680-2:345-4:0128/",
            request_safe_url("https://www.boconcept.com/ja-jp/p/canc%C3%BAn/3000680-2:345-4:0128/"),
        )

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
        self.assertEqual(
            {"vaMaterialLeg": "0708s", "vaMaterialUpholstery": "2063"},
            json.loads(candidates[0].selected_options_json),
        )

    def test_extract_candidates_supports_all_configuration_attributes(self):
        html = """
        <script>
        {\\"product\\":{\\"superMasterKey\\":\\"4352503\\",
        \\"variantUrlKey\\":\\"4352503-10:435_sofalegs_2-14:2250-21:4\\",
        \\"selectedOptions\\":{\\"vaMaterialLegStyle\\":\\"435_Sofalegs_2\\",
        \\"vaMaterialUpholstery\\":\\"2250\\",\\"vaSofaDirection\\":\\"4\\"}},
        \\"configuration\\":{\\"options\\":[
        {\\"attributeId\\":\\"vaMaterialLegStyle\\",\\"attributeLabel\\":\\"脚のスタイル\\",
        \\"values\\":[{\\"id\\":\\"435_Sofalegs_2\\",\\"name\\":\\"脚\\"}]},
        {\\"attributeId\\":\\"vaSofaDirection\\",\\"attributeLabel\\":\\"向き\\",
        \\"values\\":[{\\"id\\":\\"5\\",\\"name\\":\\"右\\"},{\\"id\\":\\"4\\",\\"name\\":\\"左\\"}]},
        {\\"attributeId\\":\\"vaMaterialUpholstery\\",\\"attributeLabel\\":\\"張地\\",
        \\"values\\":[{\\"id\\":\\"2250\\",\\"name\\":\\"Napoli\\"},{\\"id\\":\\"3252\\",\\"name\\":\\"Avellino\\"}]}
        ]}}
        </script>
        """

        candidates = extract_candidates(
            "https://www.boconcept.com/ja-jp/p/amsterdam/4352503-10:435_sofalegs_2-14:2250-21:4/",
            html,
        )

        self.assertEqual(4, len(candidates))
        self.assertIn(
            "4352503-10:435_sofalegs_2-14:3252-21:5",
            [candidate.variant_url_key for candidate in candidates],
        )
        self.assertTrue(all(key.startswith("4352503-") for key in (c.variant_url_key for c in candidates)))
        self.assertEqual("脚", candidates[0].selected_leg)
        self.assertIn("vaSofaDirection", json.loads(candidates[0].selected_options_json))

    def test_extract_candidates_applies_previous_requirements(self):
        html = """
        <script>
        {\\"product\\":{\\"superMasterKey\\":\\"1\\",\\"variantUrlKey\\":\\"1-1:a-2:x\\",
        \\"selectedOptions\\":{\\"first\\":\\"a\\",\\"second\\":\\"x\\"}},
        \\"configuration\\":{\\"options\\":[
        {\\"attributeId\\":\\"first\\",\\"values\\":[
        {\\"id\\":\\"a\\",\\"name\\":\\"A\\"},{\\"id\\":\\"b\\",\\"name\\":\\"B\\"}]},
        {\\"attributeId\\":\\"second\\",\\"values\\":[
        {\\"id\\":\\"x\\",\\"name\\":\\"X\\",\\"previousRequirements\\":{\\"first\\":[\\"a\\"]}},
        {\\"id\\":\\"y\\",\\"name\\":\\"Y\\",\\"previousRequirements\\":{\\"first\\":[\\"b\\"]}}]}
        ]}}
        </script>
        """

        candidates = extract_candidates("https://www.boconcept.com/ja-jp/p/example/1-1:a-2:x/", html)

        self.assertEqual(["1-1:a-2:x", "1-1:b-2:y"], [candidate.variant_url_key for candidate in candidates])

    def test_extract_candidates_maps_repeated_option_ids_by_attribute_order(self):
        html = """
        <script>
        {\\"product\\":{\\"superMasterKey\\":\\"3707250\\",
        \\"variantUrlKey\\":\\"3707250-2:403-6:0702-9:0702\\",
        \\"selectedOptions\\":{\\"size\\":\\"403\\",\\"cabinet\\":\\"0702\\",\\"leg\\":\\"0702\\"}},
        \\"configuration\\":{\\"options\\":[
        {\\"attributeId\\":\\"size\\",\\"values\\":[{\\"id\\":\\"403\\",\\"name\\":\\"Small\\"}]},
        {\\"attributeId\\":\\"cabinet\\",\\"values\\":[
        {\\"id\\":\\"0702\\",\\"name\\":\\"Dark\\"},{\\"id\\":\\"0708\\",\\"name\\":\\"Natural\\"}]},
        {\\"attributeId\\":\\"leg\\",\\"values\\":[
        {\\"id\\":\\"0702\\",\\"name\\":\\"Dark\\",\\"previousRequirements\\":{\\"cabinet\\":[\\"0702\\"]}},
        {\\"id\\":\\"0708\\",\\"name\\":\\"Natural\\",\\"previousRequirements\\":{\\"cabinet\\":[\\"0708\\"]}}]}
        ]}}
        </script>
        """

        candidates = extract_candidates(
            "https://www.boconcept.com/ja-jp/p/axo-series/3707250-2:403-6:0702-9:0702/",
            html,
        )

        self.assertEqual(
            ["3707250-2:403-6:0702-9:0702", "3707250-2:403-6:0708-9:0708"],
            [candidate.variant_url_key for candidate in candidates],
        )

    def test_resolve_candidate_uses_api_variant_url_key(self):
        candidate = VariantCandidate(
            product_url="https://www.boconcept.com/ja-jp/p/amsterdam/current/",
            variant_url="https://www.boconcept.com/ja-jp/p/amsterdam/guessed/",
            variant_url_key="guessed",
            selected_leg_id="leg",
            selected_leg="Leg",
            selected_upholstery_id="2063",
            selected_upholstery="Fabric",
            selected_options_json='{"direction":"5","upholstery":"2063"}',
            super_master_key="SM43550006",
        )
        response_payload = {
            "status": "ok",
            "data": {
                "variantUrlKey": "4352502-10:leg-14:2063-21:5",
                "variantKey": "sku",
            },
        }

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps(response_payload).encode("utf-8")

        with patch("boexio.phase2_variants.urlopen", return_value=Response()):
            resolved, payload = resolve_candidate(candidate, timeout=10)

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual("4352502-10:leg-14:2063-21:5", resolved.variant_url_key)
        self.assertTrue(resolved.variant_url.endswith("/4352502-10:leg-14:2063-21:5/"))
        self.assertEqual("sku", payload["variantKey"])

    def test_resolve_candidate_treats_api_404_as_unsupported(self):
        candidate = VariantCandidate(
            product_url="https://www.boconcept.com/ja-jp/p/example/current/",
            variant_url="https://www.boconcept.com/ja-jp/p/example/guessed/",
            variant_url_key="guessed",
            selected_leg_id="",
            selected_leg="",
            selected_upholstery_id="",
            selected_upholstery="",
            selected_options_json='{"option":"invalid"}',
            super_master_key="SM1",
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps({"status": "error", "res": {"status": 404}}).encode("utf-8")

        with patch("boexio.phase2_variants.urlopen", return_value=Response()):
            resolved, _payload = resolve_candidate(candidate, timeout=10)

        self.assertIsNone(resolved)

    def test_resolve_candidate_classifies_api_timeout_as_retryable(self):
        candidate = VariantCandidate(
            product_url="https://www.boconcept.com/ja-jp/p/example/current/",
            variant_url="https://www.boconcept.com/ja-jp/p/example/guessed/",
            variant_url_key="guessed",
            selected_leg_id="",
            selected_leg="",
            selected_upholstery_id="",
            selected_upholstery="",
            selected_options_json='{"option":"transient-timeout"}',
            super_master_key="SM1",
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps(
                    {
                        "status": "error",
                        "message": "The operation was aborted due to timeout",
                    }
                ).encode("utf-8")

        with patch("boexio.phase2_variants.urlopen", return_value=Response()):
            with self.assertRaisesRegex(RuntimeError, r"^TIMEOUT_READ: variant options API:"):
                resolve_candidate(candidate, timeout=10)

    def test_resolved_variant_row_maps_api_product_data(self):
        candidate = VariantCandidate(
            product_url="product",
            variant_url="https://www.boconcept.com/ja-jp/p/amsterdam/resolved/",
            variant_url_key="resolved",
            selected_leg_id="leg",
            selected_leg="Dark leg",
            selected_upholstery_id="2063",
            selected_upholstery="Light fabric",
        )

        row = resolved_variant_row(
            candidate,
            {
                "name": "Amsterdam",
                "description": "Amsterdam sofa",
                "productMasterKey": "master",
                "variantUrlKey": "resolved",
                "variantKey": "sku",
                "price": {"formattedPrice": "¥ 100", "currency": "JPY"},
                "attributes": {
                    "width": "100 cm",
                    "depth": "80 cm",
                    "height": "70 cm",
                    "weight": "20 kg",
                    "productSpecification": "material",
                },
                "assets": [{"source": "https://images.example.test/product.jpg"}],
            },
            "raw/variant.json",
            "run",
            "2026-06-14T00:00:00+00:00",
        )

        self.assertEqual("Amsterdam sofa", row["product_name"])
        self.assertEqual("resolved", row["variant_id"])
        self.assertEqual("sku", row["sku"])
        self.assertEqual("¥ 100", row["canonical_price"])
        self.assertEqual("variant_options_api", row["price_from"])


if __name__ == "__main__":
    unittest.main()
