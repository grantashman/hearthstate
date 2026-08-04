import unittest

from api.pricing import catalog_updates, compare_cart, match_item, normalize_name


class RetailerMatcherTests(unittest.TestCase):
    def test_normalization_handles_apostrophes_and_recipe_measurements(self):
        self.assertEqual(normalize_name("Cole’s  1L Full-Cream Milk"), "coles 1l full cream milk")

    def test_coles_alias_match_returns_explainable_provenance(self):
        match = match_item("cole’s brand white pepper", "coles")

        self.assertIsNotNone(match)
        self.assertEqual(match["retailer"], "coles")
        self.assertEqual(match["title"], "Coles White Pepper 100g")
        self.assertEqual(match["price"], 5.00)
        self.assertTrue(match["url"].startswith("https://www.coles.com.au/product/"))
        self.assertEqual(match["confidence"], "curated")

    def test_each_non_coles_catalog_has_traceable_common_products(self):
        aldi_bread = match_item("bread", "aldi")
        woolworths_butter = match_item("butter", "woolworths")
        self.assertEqual(aldi_bread["price"], 2.59)
        self.assertIn("aldi.com.au/product/", aldi_bread["url"])
        self.assertEqual(woolworths_butter["price"], 4.50)
        self.assertIn("woolworths.com.au/shop/productdetails/", woolworths_butter["url"])

    def test_explicit_size_does_not_match_a_different_pack(self):
        self.assertIsNotNone(match_item("2L Coke Zero", "coles"))
        self.assertIsNone(match_item("600mL Coke Zero", "coles"))

    def test_explicit_variant_fails_closed_instead_of_substituting_original(self):
        self.assertIsNotNone(match_item("franks hot sauce", "coles"))
        self.assertIsNone(match_item("Frank's Buffalo hot sauce", "coles"))
        self.assertIsNone(match_item("Frank's Xtra Hot hot sauce", "coles"))

    def test_manual_source_is_protected_even_without_confidence_flag(self):
        self.assertEqual(catalog_updates([{"name": "eggs", "price": 4.25, "price_source": "Manual entry"}]), [])

    def test_unknown_product_variant_is_not_inherited_from_generic_alias(self):
        self.assertIsNone(match_item("milk powder", "coles"))
        self.assertIsNotNone(match_item("coles brand white pepper", "coles"))

    def test_non_count_units_fail_closed_instead_of_treating_pack_price_as_weight_price(self):
        comparison = compare_cart([{"name": "potatoes", "quantity": 2, "unit": "kg"}])
        self.assertTrue(all(result["unknown_count"] == 1 for result in comparison.values()))
        self.assertTrue(all(result["total"] == 0 for result in comparison.values()))

    def test_cart_with_non_equivalent_products_is_not_recommended(self):
        comparison = compare_cart([{"name": "eggs", "quantity": 1}])
        self.assertTrue(all(result["complete"] for result in comparison.values()))
        self.assertFalse(any(result["comparable"] for result in comparison.values()))
        self.assertEqual(comparison["coles"]["not_comparable_items"], ["eggs"])

    def test_cart_line_includes_equivalence_key_and_title(self):
        comparison = compare_cart([{"name": "eggs", "quantity": 1}])
        match = comparison["coles"]["lines"][0]["match"]
        self.assertIn("comparison_key", match)
        self.assertIn("title", match)

    def test_catalog_match_is_idempotent_after_supabase_timestamp_round_trip(self):
        item = {
            "name": "eggs",
            "price": 5.70,
            "price_source": "Coles Cage Free Eggs 12 Pack 700g",
            "price_url": "https://www.coles.com.au/product/coles-cage-free-eggs-12-pack-700g-5178633",
            "price_confidence": "curated",
            "price_checked_at": "2026-08-04T00:00:00+00:00",
            "price_note": "Coles brand selected: 12-pack; online price observed and location-sensitive.",
        }
        self.assertEqual(catalog_updates([item]), [])

    def test_unknown_item_is_not_guessed(self):
        self.assertIsNone(match_item("mystery pantry item", "aldi"))

    def test_cart_comparison_returns_each_retailer_total_and_unknown_counts(self):
        comparison = compare_cart(
            [
                {"name": "eggs", "quantity": 1},
                {"name": "bananas", "quantity": 2},
                {"name": "mystery pantry item", "quantity": 1},
            ]
        )

        self.assertEqual(set(comparison), {"coles", "aldi", "woolworths"})
        self.assertEqual(comparison["coles"]["total"], 7.36)
        self.assertEqual(comparison["aldi"]["total"], 6.91)
        self.assertEqual(comparison["woolworths"]["total"], 8.32)
        for retailer in comparison:
            self.assertEqual(comparison[retailer]["priced_count"], 2)
            self.assertEqual(comparison[retailer]["unknown_count"], 1)
            self.assertFalse(comparison[retailer]["complete"])
        self.assertEqual(comparison["aldi"]["total_status"], "partial")


if __name__ == "__main__":
    unittest.main()
