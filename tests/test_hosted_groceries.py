from pathlib import Path
from unittest.mock import Mock, patch
import unittest

from api.index import handler


class HostedGroceryMatchingTests(unittest.TestCase):
    def test_snapshot_applies_curated_match_and_returns_retailer_comparison(self):
        item = {
            "id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "name": "eggs",
            "quantity": 1,
            "unit": "each",
            "price": None,
            "price_confidence": None,
            "status": "open",
        }
        matched_item = {
            **item,
            "price": 5.70,
            "price_source": "Coles Cage Free Eggs 12 Pack 700g",
            "price_url": "https://www.coles.com.au/product/coles-cage-free-eggs-12-pack-700g-5178633",
            "price_confidence": "curated",
            "price_checked_at": "2026-08-04",
            "price_note": "Coles observed",
        }
        request = object.__new__(handler)
        request._table = Mock(return_value=[item])
        request._patch_record = Mock(return_value=matched_item)

        with patch("api.index._supabase_request", return_value=[]):
            snapshot = request._grocery_snapshot("2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "access-token")

        request._patch_record.assert_called_once()
        self.assertEqual(snapshot["items"][0]["price"], 5.70)
        self.assertEqual(snapshot["priced_count"], 1)
        self.assertEqual(snapshot["comparison"]["coles"]["total"], 5.70)
        self.assertEqual(snapshot["comparison"]["aldi"]["total"], 5.29)
        self.assertEqual(snapshot["comparison"]["woolworths"]["total"], 6.50)
        self.assertEqual(snapshot["recommended_retailer"], "aldi")

    def test_snapshot_does_not_replace_a_manual_price(self):
        item = {
            "id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "name": "eggs",
            "quantity": 1,
            "unit": "each",
            "price": 4.25,
            "price_confidence": "manual",
            "price_source": "Manual entry",
            "status": "open",
        }
        request = object.__new__(handler)
        request._table = Mock(return_value=[item])
        request._patch_record = Mock()

        with patch("api.index._supabase_request", return_value=[]):
            snapshot = request._grocery_snapshot("2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "access-token")

        request._patch_record.assert_not_called()
        self.assertEqual(snapshot["items"][0]["price"], 4.25)

    def test_refresh_coles_is_not_a_no_op(self):
        request = object.__new__(handler)
        request.headers = {"X-Hearthstate-Household": "household-id"}
        request._authenticate = Mock(return_value=("user-id", "access-token", {"email": "person@example.com"}))
        request._context = Mock(return_value=("household-id", []))
        request._grocery_snapshot = Mock(return_value={"auto_updated": ["eggs"]})
        request._respond = Mock()

        with patch("api.index._json_body", return_value={}):
            request._handle_post("/groceries/refresh-coles")

        request._grocery_snapshot.assert_called_once()
        self.assertEqual(request._respond.call_args.args[0]["auto_updated"], ["eggs"])
    def test_grocery_dashboard_exposes_multi_retailer_contract(self):
        html = (Path(__file__).parents[1] / "hearthstate" / "dashboard" / "groceries.html").read_text()
        javascript = (Path(__file__).parents[1] / "hearthstate" / "dashboard" / "groceries.js").read_text()
        self.assertIn('id="retailerComparison"', html)
        self.assertIn('id="comparisonNote"', html)
        self.assertIn("/api/groceries/refresh", javascript)
        self.assertIn("retailer_totals", javascript)
        self.assertIn("recommended_retailer", javascript)

    def test_retailer_quote_migration_has_household_scoped_rls(self):
        migration = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260804010000_grocery_price_quotes.sql").read_text()
        self.assertIn("create table if not exists public.grocery_price_quotes", migration)
        self.assertIn("unique (grocery_item_id, retailer)", migration)
        self.assertIn("check (retailer in ('coles', 'aldi', 'woolworths'))", migration)
        self.assertIn("alter table public.grocery_price_quotes enable row level security", migration)
        self.assertIn("private.is_household_member(household_id)", migration)
        self.assertIn("grant select, insert, update, delete on public.grocery_price_quotes to authenticated", migration)
        self.assertNotIn("service_role", migration)
    def test_refresh_persists_quotes_with_household_scope_and_clears_unmatched(self):
        request = object.__new__(handler)
        comparison = {
            "coles": {
                "lines": [{
                    "item_id": "item-id",
                    "match": {
                        "product_key": "eggs",
                        "title": "Coles Cage Free Eggs 12 Pack 700g",
                        "url": "https://www.coles.com.au/product/eggs",
                        "price": 5.70,
                        "observed_at": "2026-08-04",
                        "confidence": "curated",
                        "match_basis": "exact alias",
                        "note": "Observed",
                    },
                }],
            },
            "aldi": {"lines": [{"item_id": "item-id", "match": None}]},
        }

        with patch("api.index._supabase_request") as supabase_request:
            request._upsert_price_quotes(comparison, "household-id", "access-token")

        self.assertEqual(supabase_request.call_count, 2)
        post_call = supabase_request.call_args_list[0]
        self.assertEqual(post_call.args[:2], ("POST", "/rest/v1/grocery_price_quotes"))
        self.assertEqual(post_call.kwargs["payload"]["household_id"], "household-id")
        self.assertEqual(post_call.kwargs["payload"]["grocery_item_id"], "item-id")
        delete_call = supabase_request.call_args_list[1]
        self.assertEqual(delete_call.args[:2], ("DELETE", "/rest/v1/grocery_price_quotes"))
        self.assertIn(("household_id", "eq.household-id"), delete_call.kwargs["query"])


if __name__ == "__main__":
    unittest.main()
