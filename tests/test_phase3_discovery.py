import unittest

from boexio.phase3_discovery import (
    DedupedProduct,
    ProductClassification,
    classification_slug_for_metadata,
    dedupe_product_classifications,
    discovery_completeness_by_category,
    extract_product_classification,
    parse_category_expected_count,
    parse_product_master_facet_counts,
    product_sitemap_url_from_index,
    product_urls_from_sitemap,
)


PRODUCT_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.boconcept.com/ja-jp/p/reno/123-1:abc/</loc></url>
  <url><loc>https://www.boconcept.com/ja-jp/p/reno/123-1:abc/</loc></url>
  <url><loc>https://www.boconcept.com/ja-jp/p/amsterdam/456-2:def/</loc></url>
  <url><loc>https://www.boconcept.com/ja-jp/p/table/789-3:ghi/print/</loc></url>
  <url><loc>https://www.boconcept.com/en-us/p/not-ja/000/</loc></url>
</urlset>
"""


PRODUCT_HTML = """
<html>
  <head>
    <link rel="canonical" href="https://www.boconcept.com/ja-jp/p/reno/123-1:abc/" />
    <script id="__NEXT_DATA__" type="application/json">
      {"props":{"pageProps":{"product":{
        "productMasterKey":"reno-master",
        "productMasterName":"Reno",
        "superMasterKey":"reno-super",
        "variantUrlKey":"123-1:abc",
        "biProductGroup":"Chairs",
        "biProductType":"Living chair",
        "itemCategory":"Chairs",
        "itemCategory2":"Living chairs",
        "isOutlet":false
      }}}}
    </script>
  </head>
</html>
"""


class Phase3DiscoveryTests(unittest.TestCase):
    def test_product_sitemap_is_found_from_index(self):
        index_xml = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://www.boconcept.com/ja-jp/sitemap/products/</loc></sitemap>
        </sitemapindex>"""

        self.assertEqual(
            "https://www.boconcept.com/ja-jp/sitemap/products/",
            product_sitemap_url_from_index(index_xml),
        )

    def test_product_sitemap_extracts_ja_product_urls_and_dedupes(self):
        urls, rows = product_urls_from_sitemap(PRODUCT_SITEMAP_XML)

        self.assertEqual(
            [
                "https://www.boconcept.com/ja-jp/p/reno/123-1:abc/",
                "https://www.boconcept.com/ja-jp/p/amsterdam/456-2:def/",
            ],
            urls,
        )
        self.assertEqual("duplicate", rows[1]["discovery_status"])
        self.assertIn("ROBOTS_DISALLOWED", {row["discovery_error"] for row in rows})

    def test_category_expected_count_reads_item_and_visible_counts(self):
        count = parse_category_expected_count(
            category_name="チェア",
            category_url="https://www.boconcept.com/ja-jp/shop/チェア/",
            category_slug="chair",
            html="<h1>チェア</h1><span>80アイテム</span><p>24 / 80製品を表示中</p>",
        )

        self.assertEqual(80, count.expected_product_count)
        self.assertEqual(24, count.initial_visible_product_count)
        self.assertEqual("success", count.expected_count_status)

    def test_category_expected_count_unknown_keeps_reason(self):
        count = parse_category_expected_count(
            category_name="チェア",
            category_url="https://www.boconcept.com/ja-jp/shop/チェア/",
            category_slug="chair",
            html="<h1>チェア</h1>",
        )

        self.assertIsNone(count.expected_product_count)
        self.assertEqual("unknown", count.expected_count_status)
        self.assertIn("expected_product_count_missing", count.expected_count_error)

    def test_shop_query_url_is_not_a_sitemap_product_candidate(self):
        xml = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://www.boconcept.com/ja-jp/shop/チェア/?q=page--2</loc></url>
        </urlset>"""

        urls, rows = product_urls_from_sitemap(xml)

        self.assertEqual([], urls)
        self.assertEqual("URL_NOT_ALLOWED", rows[0]["discovery_error"])

    def test_product_metadata_classifier_extracts_keys_and_category(self):
        classification = extract_product_classification(
            "https://www.boconcept.com/ja-jp/p/reno/123-1:abc/",
            PRODUCT_HTML,
        )

        self.assertEqual("reno-master", classification.product_master_key)
        self.assertEqual("Reno", classification.product_master_name)
        self.assertEqual("reno-super", classification.super_master_key)
        self.assertEqual("Chairs", classification.bi_product_group)
        self.assertEqual("Chairs", classification.item_category)
        self.assertEqual("chair", classification.classification_slug)
        self.assertEqual("classified", classification.classification_status)

    def test_group_classifier_maps_target_categories(self):
        self.assertEqual(("sofa", ""), classification_slug_for_metadata("Sofas", ""))
        self.assertEqual(("table", ""), classification_slug_for_metadata("Tables", ""))
        self.assertEqual(("chair", ""), classification_slug_for_metadata("Chairs", ""))
        self.assertEqual(("bed", ""), classification_slug_for_metadata("Beds", ""))

    def test_product_master_dedupe_prefers_default_then_canonical(self):
        first = ProductClassification(
            product_url="https://www.boconcept.com/ja-jp/p/reno/variant-a/",
            product_master_key="master-1",
            bi_product_group="Chairs",
            item_category="Chairs",
            canonical_url="https://www.boconcept.com/ja-jp/p/reno/canonical/",
            classification_slug="chair",
            classification_status="classified",
        )
        second = ProductClassification(
            product_url="https://www.boconcept.com/ja-jp/p/reno/variant-b/",
            product_master_key="master-1",
            bi_product_group="Chairs",
            item_category="Chairs",
            default_variant_url="https://www.boconcept.com/ja-jp/p/reno/default/",
            is_default=True,
            classification_slug="chair",
            classification_status="classified",
        )

        deduped = dedupe_product_classifications([first, second])

        self.assertEqual(1, len(deduped))
        group = deduped["master-1"]
        self.assertIsInstance(group, DedupedProduct)
        self.assertEqual(second.product_url, group.representative.product_url)
        self.assertEqual("default_variant", group.representative_reason)

    def test_discovery_complete_only_when_expected_count_matches_and_no_unknown(self):
        expected = {
            "chair": parse_category_expected_count(
                category_name="チェア",
                category_url="https://www.boconcept.com/ja-jp/shop/チェア/",
                category_slug="chair",
                html="80アイテム 24 / 80製品を表示中",
            )
        }
        deduped = {
            f"chair-{index}": DedupedProduct(
                representative=ProductClassification(
                    product_url=f"https://www.boconcept.com/ja-jp/p/chair/{index}/",
                    product_master_key=f"chair-{index}",
                    classification_slug="chair",
                    classification_status="classified",
                ),
                products=(),
                representative_reason="sitemap_order",
            )
            for index in range(80)
        }

        completeness, errors = discovery_completeness_by_category(
            expected_counts=expected,
            deduped=deduped,
            product_limit_per_category=0,
        )

        self.assertTrue(completeness["chair"]["discovery_complete"])
        self.assertEqual([], errors)

    def test_discovery_incomplete_on_count_mismatch_or_unknown(self):
        expected = {
            "sofa": parse_category_expected_count(
                category_name="ソファ",
                category_url="https://www.boconcept.com/ja-jp/shop/ソファ/",
                category_slug="sofa",
                html="183アイテム 24 / 183製品を表示中",
            )
        }
        deduped = {
            "sofa-1": DedupedProduct(
                representative=ProductClassification(
                    product_url="https://www.boconcept.com/ja-jp/p/sofa/1/",
                    product_master_key="sofa-1",
                    classification_slug="sofa",
                    classification_status="classified",
                ),
                products=(),
                representative_reason="sitemap_order",
            ),
            "unknown-1": DedupedProduct(
                representative=ProductClassification(
                    product_url="https://www.boconcept.com/ja-jp/p/unknown/1/",
                    product_master_key="unknown-1",
                    classification_status="unknown",
                ),
                products=(ProductClassification(product_url="https://www.boconcept.com/ja-jp/p/unknown/1/"),),
                representative_reason="sitemap_order",
            ),
        }

        completeness, errors = discovery_completeness_by_category(
            expected_counts=expected,
            deduped=deduped,
            product_limit_per_category=0,
        )

        self.assertFalse(completeness["sofa"]["discovery_complete"])
        self.assertTrue(errors)
        self.assertIn("expected=183 actual=1", errors[0]["message"])

    def test_product_master_facet_counts_are_compared_to_classified_products(self):
        html = (
            '"key":"product-master-name","title":"product-master-name","options":['
            '{"key":"Reno","displayValue":"Reno","selected":false,"count":2},'
            '{"key":"Osaka","displayValue":"Osaka","selected":false,"count":1},'
            '{"key":"by nendo","displayValue":"by nendo","selected":false,"count":1}'
            "]"
        )
        expected = {
            "chair": parse_category_expected_count(
                category_name="チェア",
                category_url="https://www.boconcept.com/ja-jp/shop/チェア/",
                category_slug="chair",
                html="4アイテム 4 / 4製品を表示中 " + html,
            )
        }
        self.assertEqual({"Osaka": 1, "Reno": 2, "by nendo": 1}, parse_product_master_facet_counts(html))
        deduped = {
            "reno-1": DedupedProduct(
                representative=ProductClassification(
                    product_url="https://www.boconcept.com/ja-jp/p/reno/1/",
                    product_master_key="reno-1",
                    product_master_name="Reno",
                    classification_slug="chair",
                    classification_status="classified",
                ),
                products=(),
                representative_reason="sitemap_order",
            ),
            "osaka-1": DedupedProduct(
                representative=ProductClassification(
                    product_url="https://www.boconcept.com/ja-jp/p/osaka/1/",
                    product_master_key="osaka-1",
                    product_master_name="Osaka",
                    classification_slug="chair",
                    classification_status="classified",
                ),
                products=(),
                representative_reason="sitemap_order",
            ),
            "by-nendo-1": DedupedProduct(
                representative=ProductClassification(
                    product_url="https://www.boconcept.com/ja-jp/p/by-nendo/1/",
                    product_master_key="by-nendo-1",
                    product_master_name="By Nendo",
                    classification_slug="chair",
                    classification_status="classified",
                ),
                products=(),
                representative_reason="sitemap_order",
            ),
        }

        completeness, errors = discovery_completeness_by_category(
            expected_counts=expected,
            deduped=deduped,
            product_limit_per_category=0,
        )

        self.assertFalse(completeness["chair"]["discovery_complete"])
        self.assertEqual(
            [{"product_master_name": "Reno", "expected": 2, "actual": 1, "delta": -1}],
            completeness["chair"]["product_master_name_count_diffs"],
        )
        self.assertIn("Reno expected=2 actual=1", errors[0]["message"])


if __name__ == "__main__":
    unittest.main()
