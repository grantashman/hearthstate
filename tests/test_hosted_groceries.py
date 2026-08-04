from pathlib import Path
from unittest.mock import Mock, patch
import unittest

from api.index import handler


class HostedGroceryMatchingTests(unittest.TestCase):
    def test_snapshot_does_not_mutate_or_recommend_non_equivalent_prices(self):
        item = {
            "id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "name": "eggs",
            "quantity": 1,
            "unit": "each",
            "price": None,
            "price_confidence": None,
            "status": "open",
        }
        request = object.__new__(handler)
        request._table = Mock(return_value=[item])
        request._patch_record = Mock()

        with patch("api.index._supabase_request", return_value=[]):
            snapshot = request._grocery_snapshot("2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "access-token")

        request._patch_record.assert_not_called()
        self.assertIsNone(snapshot["items"][0]["price"])
        self.assertEqual(snapshot["priced_count"], 0)
        self.assertFalse(snapshot["comparison"]["coles"]["comparable"])
        self.assertIsNone(snapshot["recommended_retailer"])

    def test_refresh_applies_curated_match_only_when_explicitly_requested(self):
        item = {
            "id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "name": "eggs",
            "quantity": 1,
            "price": None,
            "price_confidence": None,
            "status": "open",
        }
        matched_item = {**item, "price": 5.70, "price_source": "Coles Cage Free Eggs 12 Pack 700g", "price_confidence": "curated"}
        request = object.__new__(handler)
        request._table = Mock(return_value=[item])
        request._patch_record = Mock(return_value=matched_item)
        request._patch_automatic_price = Mock(return_value=matched_item)
        with patch("api.index._supabase_request", return_value=[]):
            snapshot = request._grocery_snapshot("2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "access-token", refresh=True)
        request._patch_automatic_price.assert_called_once()
        self.assertEqual(snapshot["items"][0]["price"], 5.70)

    def test_automatic_patch_is_conditional_on_non_manual_current_row(self):
        request = object.__new__(handler)
        with patch("api.index._supabase_request", return_value=[]) as supabase_request:
            result = request._patch_automatic_price(
                "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
                "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
                "access-token",
                {"price": 5.70},
            )
        self.assertIsNone(result)
        query = supabase_request.call_args.kwargs["query"]
        self.assertIn(("or", "(price_confidence.is.null,price_confidence.neq.manual)"), query)
        self.assertIn(("or", "(price_source.is.null,price_source.not.ilike.Manual*)"), query)

    def test_manual_price_endpoint_ignores_client_metadata(self):
        request = object.__new__(handler)
        request.headers = {}
        request._authenticate = Mock(return_value=("user-id", "access-token", {"email": "person@example.com"}))
        request._context = Mock(return_value=("household-id", []))
        request._patch_record = Mock(return_value={"id": "item-id"})
        request._respond = Mock()
        payload = {"item_id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "price": 4.25, "confidence": "curated", "source": "Coles fake source"}
        with patch("api.index._json_body", return_value=payload):
            request._handle_post("/groceries/price")
        patch_payload = request._patch_record.call_args.args[4]
        self.assertEqual(patch_payload["price_confidence"], "manual")
        self.assertEqual(patch_payload["price_source"], "Manual entry")
        self.assertIsNone(patch_payload["price_url"])

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

        request._grocery_snapshot.assert_called_once_with("household-id", "access-token", refresh=True)
        response = request._respond.call_args.args[0]
        self.assertEqual(response["auto_updated"], ["eggs"])
        self.assertEqual(response["updated"], 1)
        self.assertEqual(response["updated_items"], ["eggs"])
    def test_grocery_dashboard_exposes_multi_retailer_contract(self):
        html = (Path(__file__).parents[1] / "hearthstate" / "dashboard" / "groceries.html").read_text()
        javascript = (Path(__file__).parents[1] / "hearthstate" / "dashboard" / "groceries.js").read_text()
        self.assertIn('id="retailerComparison"', html)
        self.assertIn('id="comparisonNote"', html)
        self.assertIn("/api/groceries/refresh", javascript)
        self.assertIn("retailer_totals", javascript)
        self.assertIn("recommended_retailer", javascript)
        self.assertIn("comparison_not_comparable_items", javascript)
        self.assertIn("Products compared", javascript)
        self.assertIn("retailer.comparable", javascript)

    def test_retailer_quote_migration_has_household_scoped_rls(self):
        migration = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260804010000_grocery_price_quotes.sql").read_text()
        self.assertIn("create table if not exists public.grocery_price_quotes", migration)
        self.assertIn("unique (grocery_item_id, retailer)", migration)
        self.assertIn("check (retailer in ('coles', 'aldi', 'woolworths'))", migration)
        self.assertIn("alter table public.grocery_price_quotes enable row level security", migration)
        self.assertIn("private.is_household_member(household_id)", migration)
        self.assertIn("grant select, insert, update, delete on public.grocery_price_quotes to authenticated", migration)
        self.assertNotIn("service_role", migration)
        rls_migration = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260804020000_grocery_price_quote_delete_rls.sql").read_text()
        self.assertIn("grocery_price_quotes_member_delete", rls_migration)
        self.assertIn("item.household_id = grocery_price_quotes.household_id", rls_migration)
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
