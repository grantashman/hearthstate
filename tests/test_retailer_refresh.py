import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from api.retailer_refresh import (
    LIVE_ENDPOINT_ENV,
    LIVE_RETAILERS,
    LiveRetailerRefreshError,
    cached_live_match,
    normalize_live_match,
    refresh_live_retailers,
)
import api.retailer_refresh as retailer_refresh


class LiveRetailerRefreshTests(unittest.TestCase):
    def setUp(self):
        retailer_refresh._LAST_REFRESH_BY_KEY.clear()

    def _payload(self, item_id="item-1"):
        checked_at = datetime.now(timezone.utc).isoformat()
        return {
            "checked_at": checked_at,
            "retailers": {
                "coles": {
                    "matches": [{
                        "item_id": item_id,
                        "observed_at": checked_at,
                        "product_key": "coles-eggs-700g",
                        "comparison_key": "eggs-12-pack-700g",
                        "title": "Coles Cage Free Eggs 12 Pack 700g",
                        "price": 5.70,
                        "url": "https://www.coles.com.au/product/eggs",
                        "confidence": "live",
                        "match_basis": "approved provider exact match",
                        "size_match": "exact",
                        "size_quantity_safe": True,
                    }],
                },
                "woolworths": {
                    "matches": [{
                        "item_id": item_id,
                        "observed_at": checked_at,
                        "product_key": "woolworths-eggs-700g",
                        "comparison_key": "eggs-12-pack-700g",
                        "title": "Woolworths Free Range Eggs 12 Pack 700g",
                        "price": 6.50,
                        "url": "https://www.woolworths.com.au/shop/productdetails/eggs",
                        "confidence": "live",
                        "match_basis": "approved provider exact match",
                        "size_match": "exact",
                        "size_quantity_safe": True,
                    }],
                },
            },
        }

    def test_unconfigured_provider_is_a_curated_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            result = refresh_live_retailers([{"id": "item-1", "name": "eggs"}], rate_key="household-1")
        self.assertFalse(result.enabled)
        self.assertEqual(result.statuses, {"coles": "curated", "woolworths": "curated"})
        self.assertEqual(result.matches, {})

    def test_provider_returns_safe_matches_for_both_supported_retailers(self):
        items = [{"id": "item-1", "name": "eggs", "quantity": 1, "unit": "each"}]
        with patch.dict(os.environ, {LIVE_ENDPOINT_ENV: "https://provider.example.test/refresh"}, clear=True), patch("api.retailer_refresh._fetch", return_value=self._payload()) as fetch:
            result = refresh_live_retailers(items, rate_key="household-1")
        self.assertEqual(set(result.matches), set(LIVE_RETAILERS))
        self.assertEqual(result.statuses, {"coles": "live", "woolworths": "live"})
        self.assertEqual(result.matches["coles"]["item-1"]["confidence"], "live")
        self.assertEqual(result.matches["woolworths"]["item-1"]["comparison_key"], "eggs-12-pack-700g")
        request_payload = fetch.call_args.args[1]
        self.assertEqual(request_payload["retailers"], ["coles", "woolworths"])
        self.assertEqual(request_payload["items"][0]["item_id"], "item-1")

    def test_request_payload_preserves_user_query_and_own_brand_policy(self):
        payload = retailer_refresh._request_payload([{
            "id": "item-1",
            "name": "Coles 1L full-cream long-life milk",
            "quantity": 1,
            "unit": "each",
        }])

        self.assertEqual(payload["items"][0]["query"], "Coles 1L full-cream long-life milk")
        self.assertEqual(payload["search_policy"], {
            "mode": "live",
            "preserve_user_query": True,
            "preserve_explicit_constraints": True,
            "prefer_retailer_own_brand_when_generic": True,
            "retailer_brands": {"coles": ["Coles"], "woolworths": ["Woolworths"]},
        })

    def test_invalid_provider_data_fails_closed_to_curated(self):
        payload = self._payload()
        payload["retailers"]["woolworths"]["matches"][0]["url"] = "https://malicious.example.test/eggs"
        with patch.dict(os.environ, {LIVE_ENDPOINT_ENV: "https://provider.example.test/refresh"}, clear=True), patch("api.retailer_refresh._fetch", return_value=payload):
            result = refresh_live_retailers([{"id": "item-1", "name": "eggs"}], rate_key="household-2")
        self.assertEqual(result.matches, {})
        self.assertEqual(result.statuses, {"coles": "curated", "woolworths": "curated"})
        self.assertIn("retailer domain", result.error)

    def test_non_boolean_size_safety_flag_fails_closed(self):
        payload = self._payload()
        payload["retailers"]["coles"]["matches"][0]["size_quantity_safe"] = "true"
        with patch.dict(os.environ, {LIVE_ENDPOINT_ENV: "https://provider.example.test/refresh"}, clear=True), patch("api.retailer_refresh._fetch", return_value=payload):
            result = refresh_live_retailers([{"id": "item-1", "name": "eggs"}], rate_key="household-bool")
        self.assertEqual(result.matches, {})
        self.assertIn("size safety", result.error)

    def test_household_refresh_is_rate_limited(self):
        with patch.dict(os.environ, {LIVE_ENDPOINT_ENV: "https://provider.example.test/refresh"}, clear=True), patch("api.retailer_refresh._fetch", return_value=self._payload()) as fetch:
            first = refresh_live_retailers([{"id": "item-1", "name": "eggs"}], rate_key="household-3")
            second = refresh_live_retailers([{"id": "item-1", "name": "eggs"}], rate_key="household-3")
        self.assertEqual(first.statuses["coles"], "live")
        self.assertEqual(second.statuses["coles"], "rate-limited")
        self.assertEqual(fetch.call_count, 1)

    def test_cached_live_quote_is_marked_stale_without_being_deleted(self):
        old_time = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        row = {
            "grocery_item_id": "item-1",
            "retailer": "coles",
            "product_key": "coles-eggs-700g",
            "comparison_key": "eggs-12-pack-700g",
            "product_title": "Coles Cage Free Eggs 12 Pack 700g",
            "price": 5.70,
            "product_url": "https://www.coles.com.au/product/eggs",
            "observed_at": old_time,
            "confidence": "live",
            "match_basis": "approved provider exact match",
            "note": "",
            "size_match": "exact",
            "size_quantity_safe": True,
        }
        match = cached_live_match(row, expected_item_ids={"item-1"})
        self.assertIsNotNone(match)
        self.assertTrue(match["stale"])
        self.assertEqual(match["price"], 5.70)

    def test_aldi_is_not_a_live_retailer(self):
        with self.assertRaises(LiveRetailerRefreshError):
            normalize_live_match("aldi", {}, {"item-1"})


if __name__ == "__main__":
    unittest.main()
