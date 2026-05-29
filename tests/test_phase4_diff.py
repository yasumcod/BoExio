import unittest

from boexio.phase2_variants import PHASE2_CSV_COLUMNS
from boexio.phase4_diff import diff_rows, ensure_schema_compatible, validate_columns


def row(variant_key: str, price: str = "1000", **overrides):
    data = {column: "" for column in PHASE2_CSV_COLUMNS}
    data.update(
        {
            "source_url": f"https://www.boconcept.com/ja-jp/p/test/{variant_key}/",
            "source_checked_at": "2026-05-23T00:00:00+00:00",
            "scrape_status": "success",
            "product_name": "Test Chair",
            "item_number": variant_key,
            "variant_key": variant_key,
            "price_compare_value": price,
            "currency": "JPY",
            "tax_type": "tax_included",
            "price_compare_from": "canonical_price",
        }
    )
    data.update(overrides)
    return data


class Phase4DiffTests(unittest.TestCase):
    def test_detects_price_change(self):
        price_changes, added, removed, errors = diff_rows(
            "test-run",
            [row("a", "1000")],
            [row("a", "1250")],
            "2026-05-23T01:00:00+00:00",
        )

        self.assertEqual(1, len(price_changes))
        self.assertEqual("250", price_changes[0]["price_delta"])
        self.assertEqual("increase", price_changes[0]["change_direction"])
        self.assertEqual([], added)
        self.assertEqual([], removed)
        self.assertEqual([], errors)

    def test_detects_added_and_removed(self):
        price_changes, added, removed, errors = diff_rows(
            "test-run",
            [row("a"), row("b")],
            [row("a"), row("c")],
            "2026-05-23T01:00:00+00:00",
        )

        self.assertEqual([], price_changes)
        self.assertEqual(["c"], [item["variant_key"] for item in added])
        self.assertEqual(["b"], [item["variant_key"] for item in removed])
        self.assertEqual("missing_candidate", removed[0]["current_state"])
        self.assertEqual("1", removed[0]["missing_streak"])
        self.assertEqual([], errors)

    def test_marks_discontinued_after_four_missing_runs(self):
        previous = row("b", missing_streak="3", first_missing_at="2026-05-01T00:00:00+00:00")
        _price_changes, _added, removed, _errors = diff_rows(
            "test-run",
            [previous],
            [],
            "2026-05-23T01:00:00+00:00",
        )

        self.assertEqual("discontinued", removed[0]["current_state"])
        self.assertEqual("4", removed[0]["missing_streak"])
        self.assertEqual("4", removed[0]["missing_streak_at_discontinue"])
        self.assertEqual("2026-05-23T01:00:00+00:00", removed[0]["discontinued_at"])

    def test_marks_revived_discontinued_row(self):
        previous = row("a", current_state="discontinued", discontinued_at="2026-05-01T00:00:00+00:00")
        _price_changes, added, _removed, _errors = diff_rows(
            "test-run",
            [previous],
            [row("a", "1200")],
            "2026-05-23T01:00:00+00:00",
        )

        self.assertEqual("revived", added[0]["current_state"])
        self.assertEqual("1200", added[0]["revived_price"])

    def test_comparison_error_is_not_price_change(self):
        price_changes, _added, _removed, errors = diff_rows(
            "test-run",
            [row("a", currency="JPY")],
            [row("a", currency="USD")],
            "2026-05-23T01:00:00+00:00",
        )

        self.assertEqual([], price_changes)
        self.assertEqual("currency_mismatch", errors[0]["error_code"])

    def test_schema_mismatch_is_not_compatible(self):
        ok, message = ensure_schema_compatible(
            {"schema_version": "0.1.0"},
            {"schema_version": "0.2.0"},
        )

        self.assertFalse(ok)
        self.assertIn("schema_version mismatch", message)

    def test_category_columns_are_backward_compatible(self):
        legacy_row = row("a")
        legacy_row.pop("category_name")
        legacy_row.pop("category_url")

        self.assertEqual([], validate_columns([legacy_row], "previous.csv"))

    def test_legacy_run_id_column_is_backward_compatible(self):
        legacy_row = row("a")
        legacy_row.pop("run_id")

        self.assertEqual([], validate_columns([legacy_row], "previous.csv"))


if __name__ == "__main__":
    unittest.main()
