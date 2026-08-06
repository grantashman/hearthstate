import unittest

from api.pricing import catalog_updates, compare_cart, match_item, normalize_grocery_item, normalize_name


class RetailerMatcherTests(unittest.TestCase):
    def test_normalization_handles_apostrophes_and_recipe_measurements(self):
        self.assertEqual(normalize_name("Cole’s  1L Full-Cream Milk"), "coles 1l full cream milk")

    def test_woolworths_coke_zero_alias_uses_linked_product(self):
        match = match_item("Coke Zero", "woolworths")
        self.assertIsNotNone(match)
        self.assertEqual(match["title"], "Coca-Cola Zero Sugar Soft Drink Bottle 2L")
        self.assertEqual(match["price"], 4.00)
        self.assertEqual(match["url"], "https://www.woolworths.com.au/shop/productdetails/672966/coca-cola-zero-sugar-soft-drink-bottle")

    def test_woolworths_coke_zero_can_be_shown_as_closest_pack_for_600ml_request(self):
        match = match_item("Coke Zero 600ml", "woolworths")
        self.assertIsNotNone(match)
        self.assertEqual(match["title"], "Coca-Cola Zero Sugar Soft Drink Bottle 2L")
        self.assertEqual(match["size_match"], "closest")
        self.assertEqual(match["requested_size"], "600ml")

    def test_only_coles_and_woolworths_are_supported(self):
        with self.assertRaises(ValueError):
            match_item("Coke Zero", "aldi")

    def test_size_quantity_becomes_one_purchase_when_it_matches_a_packaged_product(self):
        item = normalize_grocery_item({"name": "Coke Zero", "quantity": 600, "unit": "ml"})
        self.assertEqual(item["name"], "Coke Zero")
        self.assertEqual(item["quantity"], 600)
        self.assertEqual(item["unit"], "ml")

    def test_loose_weighted_product_does_not_become_one_pack(self):
        item = normalize_grocery_item({"name": "bananas", "quantity": 170, "unit": "g"})
        self.assertEqual(item["name"], "bananas")
        self.assertEqual(item["quantity"], 170)
        self.assertEqual(item["unit"], "g")

    def test_size_quantity_only_normalizes_for_an_exact_catalog_pack(self):
        nearest = normalize_grocery_item({"name": "Coke Zero", "quantity": 500, "unit": "ml"})
        self.assertEqual(nearest["name"], "Coke Zero")
        self.assertEqual(nearest["quantity"], 500)
        self.assertEqual(nearest["unit"], "ml")

        item = normalize_grocery_item({"name": "potatoes", "quantity": 2, "unit": "kg"})
        self.assertEqual(item["name"], "potatoes")
        self.assertEqual(item["quantity"], 2)
        self.assertEqual(item["unit"], "kg")

    def test_coles_alias_match_returns_explainable_provenance(self):
        match = match_item("cole’s brand white pepper", "coles")
        self.assertIsNotNone(match)
        self.assertEqual(match["retailer"], "coles")
        self.assertEqual(match["title"], "Coles White Pepper 100g")
        self.assertEqual(match["price"], 5.00)
        self.assertTrue(match["url"].startswith("https://www.coles.com.au/product/"))
        self.assertEqual(match["confidence"], "curated")

    def test_woolworths_catalog_has_traceable_common_products(self):
        woolworths_butter = match_item("butter", "woolworths")
        self.assertEqual(woolworths_butter["price"], 4.50)
        self.assertIn("woolworths.com.au/shop/productdetails/", woolworths_butter["url"])

    def test_explicit_size_does_not_match_a_different_pack(self):
        self.assertIsNotNone(match_item("2L Coke Zero", "coles"))
        self.assertIsNone(match_item("600mL Coke Zero", "coles"))

    def test_invalid_signed_size_fails_closed(self):
        self.assertIsNone(match_item("Coke Zero -600ml", "coles"))

    def test_zero_size_comparison_fails_closed_instead_of_crashing(self):
        comparison = compare_cart([{"name": "Coke Zero 0ml", "quantity": 1, "unit": "each"}])
        self.assertTrue(all(result["unknown_count"] == 1 for result in comparison.values()))
        self.assertTrue(all(result["total"] == 0 for result in comparison.values()))

    def test_explicit_variant_fails_closed_instead_of_substituting_original(self):
        self.assertIsNotNone(match_item("franks hot sauce", "coles"))
        self.assertIsNone(match_item("Frank's Buffalo hot sauce", "coles"))
        self.assertIsNone(match_item("Frank's Xtra Hot hot sauce", "coles"))

    def test_manual_source_is_protected_even_without_confidence_flag(self):
        self.assertEqual(catalog_updates([{"name": "eggs", "price": 4.25, "price_source": "Manual entry"}]), [])

    def test_manual_confidence_is_casefolded_and_trimmed(self):
        self.assertEqual(catalog_updates([{"name": "eggs", "price_confidence": "Manual"}]), [])
        self.assertEqual(catalog_updates([{"name": "eggs", "price_confidence": " manual "}]), [])

    def test_manual_price_source_and_confidence_are_casefolded_and_trimmed(self):
        self.assertEqual(catalog_updates([{"name": "eggs", "price_source": " manual entry "}]), [])
        self.assertEqual(catalog_updates([{"name": "eggs", "price_confidence": "MANUAL "}]), [])

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
        self.assertIsNone(match_item("mystery pantry item", "woolworths"))

    def test_generic_coke_zero_is_equivalent_across_matching_2l_catalogs(self):
        comparison = compare_cart([{"name": "Coke Zero", "quantity": 1}], retailers=("coles", "woolworths"))
        self.assertTrue(comparison["coles"]["comparable"])
        self.assertTrue(comparison["woolworths"]["comparable"])
        self.assertEqual(
            comparison["coles"]["lines"][0]["match"]["comparison_key"],
            comparison["woolworths"]["lines"][0]["match"]["comparison_key"],
        )

    def test_size_qualified_coke_zero_does_not_use_a_different_pack(self):
        comparison = compare_cart([{"name": "Coke Zero", "quantity": 600, "unit": "ml"}])
        self.assertEqual(comparison["coles"]["total"], 0)
        self.assertIsNone(comparison["coles"]["lines"][0]["match"])
        self.assertEqual(comparison["woolworths"]["lines"][0]["match"]["size_match"], "closest")
        self.assertFalse(comparison["woolworths"]["comparable"])

    def test_closest_pack_is_not_automatic_price_update(self):
        item = {"name": "Coke Zero 600ml", "quantity": 1, "unit": "each"}
        self.assertEqual(catalog_updates([item], "woolworths"), [])

    def test_closest_pack_is_not_comparable(self):
        comparison = compare_cart([{"name": "Coke Zero 600ml", "quantity": 1}], retailers=("woolworths",))
        self.assertEqual(comparison["woolworths"]["lines"][0]["match"]["size_match"], "closest")
        self.assertFalse(comparison["woolworths"]["comparable"])

    def test_cart_comparison_returns_each_retailer_total_and_unknown_counts(self):
        comparison = compare_cart(
            [
                {"name": "eggs", "quantity": 1},
                {"name": "bananas", "quantity": 2},
                {"name": "mystery pantry item", "quantity": 1},
            ]
        )

        self.assertEqual(set(comparison), {"coles", "woolworths"})
        self.assertEqual(comparison["coles"]["total"], 7.36)
        self.assertEqual(comparison["woolworths"]["total"], 8.32)
        for retailer in comparison:
            self.assertEqual(comparison[retailer]["priced_count"], 2)
            self.assertEqual(comparison[retailer]["unknown_count"], 1)
            self.assertFalse(comparison[retailer]["complete"])
        self.assertEqual(comparison["woolworths"]["total_status"], "partial")

    def test_live_matches_drive_both_store_totals_and_best_item_savings(self):
        live_matches = {
            "coles": {
                "item-1": {
                    "retailer": "coles", "retailer_label": "Coles", "item_id": "item-1",
                    "product_key": "coles-eggs", "comparison_key": "eggs-700g", "title": "Coles Eggs",
                    "price": 5.70, "url": "https://www.coles.com.au/product/eggs", "confidence": "live",
                    "observed_at": "2026-08-04T00:00:00+00:00", "match_basis": "provider", "note": "",
                    "size_match": "exact", "size_quantity_safe": True,
                },
            },
            "woolworths": {
                "item-1": {
                    "retailer": "woolworths", "retailer_label": "Woolworths", "item_id": "item-1",
                    "product_key": "woolworths-eggs", "comparison_key": "eggs-700g", "title": "Woolworths Eggs",
                    "price": 6.50, "url": "https://www.woolworths.com.au/shop/productdetails/eggs", "confidence": "live",
                    "observed_at": "2026-08-04T00:00:00+00:00", "match_basis": "provider", "note": "",
                    "size_match": "exact", "size_quantity_safe": True,
                },
            },
        }
        comparison = compare_cart([{"id": "item-1", "name": "eggs", "quantity": 2}], live_matches=live_matches)
        self.assertEqual(comparison["coles"]["total"], 11.40)
        self.assertEqual(comparison["woolworths"]["total"], 13.00)
        self.assertEqual(comparison["coles"]["live_count"], 1)
        self.assertEqual(comparison["coles"]["best_deals"][0]["retailer"], "coles")
        self.assertEqual(comparison["coles"]["best_deals"][0]["savings"], 1.60)


if __name__ == "__main__":
    unittest.main()
