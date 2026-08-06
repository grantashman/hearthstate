from pathlib import Path
from unittest.mock import Mock, patch
import unittest

from api.index import SupabaseHTTPError, handler


class HostedGroceryMatchingTests(unittest.TestCase):
    def test_size_qualified_existing_row_stays_unresolved_without_an_exact_supported_pack(self):
        item = {
            "id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "name": "Coke Zero",
            "quantity": 600,
            "unit": "ml",
            "price": None,
            "price_confidence": None,
            "status": "open",
        }
        request = object.__new__(handler)
        request._table = Mock(return_value=[item])
        with patch("api.index._supabase_request", return_value=[]):
            snapshot = request._grocery_snapshot("2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "access-token")
        self.assertEqual(snapshot["items"][0]["name"], "Coke Zero")
        self.assertEqual(snapshot["items"][0]["quantity"], 600)
        self.assertEqual(snapshot["items"][0]["unit"], "ml")
        self.assertEqual(set(snapshot["comparison"]), {"coles", "woolworths"})
        self.assertEqual(snapshot["comparison"]["coles"]["total"], 0)
        self.assertEqual(snapshot["comparison"]["woolworths"]["lines"][0]["quantity"], 1)

    def test_refresh_does_not_apply_a_closest_pack_as_an_automatic_price(self):
        item = {
            "id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "name": "Coke Zero",
            "quantity": 600,
            "unit": "ml",
            "price": None,
            "price_confidence": None,
            "status": "open",
        }
        request = object.__new__(handler)
        request._patch_automatic_price = Mock(return_value={**item, "price": 4.00})
        items, updated = request._apply_catalog_matches([item], "household-id", "access-token")
        self.assertEqual(updated, [])
        request._patch_automatic_price.assert_not_called()
        self.assertEqual(items[0]["name"], "Coke Zero")
        self.assertEqual(items[0]["quantity"], 600)
        self.assertEqual(items[0]["unit"], "ml")

    def test_grocery_record_payload_canonicalizes_size_as_one_purchase(self):
        request = object.__new__(handler)
        record = request._record_payload(
            "grocery_items",
            {"name": "Coke Zero", "quantity": 600, "unit": "ml", "category": "Recipe"},
            "user-id",
            "household-id",
        )
        self.assertEqual(record["name"], "Coke Zero")
        self.assertEqual(record["quantity"], 600)
        self.assertEqual(record["unit"], "ml")
        self.assertNotIn("requested_size", record)
        self.assertNotIn("price", record)
        self.assertNotIn("price_source", record)
        self.assertNotIn("price_url", record)
        self.assertNotIn("price_confidence", record)

    def test_record_payload_retains_meal_fields(self):
        request = object.__new__(handler)
        record = request._record_payload("meals", {"meal_date": "2026-08-04", "meal_type": "dinner", "title": "Tacos", "cook": "user-id", "status": "planned", "ingredients": []}, "user-id", "household-id")
        self.assertEqual(record["title"], "Tacos")
        self.assertEqual(record["household_id"], "household-id")

    def test_generic_grocery_patch_rejects_client_provenance_fields(self):
        request = object.__new__(handler)
        item_id = "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47"
        existing = {"id": item_id, "name": "eggs", "quantity": 1, "unit": "each", "category": "Recipe"}
        with patch("api.index._supabase_request", side_effect=[[existing], [{**existing, "quantity": 2}]]) as supabase:
            request._patch_record("grocery_items", item_id, "household-id", "access-token", {"quantity": 2, "price": 1, "price_url": "javascript:alert(1)", "price_source": "Coles fake"})
        payload = supabase.call_args_list[1].kwargs["payload"]
        self.assertNotIn("price", payload)
        self.assertNotIn("price_url", payload)
        self.assertNotIn("price_source", payload)

    def test_manual_price_patch_uses_membership_checked_transactional_rpc(self):
        request = object.__new__(handler)
        item_id = "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47"
        with patch("api.index._supabase_request") as member_request, patch("api.index._supabase_admin_request", return_value=[{"id": item_id}]) as admin_request:
            request._patch_record("grocery_items", item_id, "household-id", "access-token", {"price": 4.25, "price_source": "Manual entry", "price_confidence": "manual"}, allow_price_metadata=True, actor_user_id="user-id")
        self.assertEqual(admin_request.call_args.args[:2], ("POST", "/rest/v1/rpc/set_grocery_manual_price"))
        self.assertEqual(admin_request.call_args.kwargs["payload"]["p_actor_user_id"], "user-id")
        member_request.assert_not_called()


    def test_manual_price_patch_is_the_only_price_metadata_path(self):
        request = object.__new__(handler)
        item_id = "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47"
        existing = {"id": item_id, "name": "eggs", "quantity": 1, "unit": "each", "category": "Recipe"}
        with patch("api.index._supabase_admin_request", return_value=[{**existing, "price": 4.25}]) as admin_request:
            request._patch_record("grocery_items", item_id, "household-id", "access-token", {"price": 4.25, "price_source": "Manual entry", "price_confidence": "manual"}, allow_price_metadata=True, actor_user_id="user-id")
        payload = admin_request.call_args.kwargs["payload"]
        self.assertEqual(payload["p_price"], 4.25)
        self.assertEqual(payload["p_item_id"], item_id)

    def test_quantity_patch_persists_canonical_existing_pack(self):
        item_id = "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47"
        existing = {"id": item_id, "name": "Coke Zero", "quantity": 600, "unit": "ml", "category": "Recipe"}
        patched = {**existing, "quantity": 2, "unit": "ml"}
        request = object.__new__(handler)
        with patch("api.index._supabase_request", side_effect=[[existing], [patched]]) as supabase:
            result = request._patch_record("grocery_items", item_id, "household-id", "access-token", {"quantity": 2})
        payload = supabase.call_args_list[1].kwargs["payload"]
        self.assertEqual(payload["name"], "Coke Zero")
        self.assertEqual(payload["quantity"], 2)
        self.assertEqual(payload["unit"], "ml")
        self.assertNotIn("requested_size", payload)
        self.assertEqual(result["quantity"], 2)

    def test_quantity_patch_uses_compare_and_swap_identity_filters(self):
        item_id = "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47"
        existing = {"id": item_id, "name": "Coke Zero", "quantity": 600, "unit": "ml", "category": "Recipe"}
        request = object.__new__(handler)
        with patch("api.index._supabase_request", side_effect=[[existing], [{**existing, "quantity": 1}]]) as supabase:
            request._patch_record("grocery_items", item_id, "household-id", "access-token", {"quantity": 1})
        patch_query = supabase.call_args_list[1].kwargs["query"]
        self.assertIn(("name", "eq.Coke Zero"), patch_query)
        self.assertIn(("quantity", "eq.600"), patch_query)
        self.assertIn(("unit", "eq.ml"), patch_query)
        self.assertIn(("category", "eq.Recipe"), patch_query)

    def test_quantity_patch_reports_conflict_when_identity_changed(self):
        item_id = "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47"
        existing = {"id": item_id, "name": "Coke Zero", "quantity": 600, "unit": "ml", "category": "Recipe"}
        request = object.__new__(handler)
        with patch("api.index._supabase_request", side_effect=[[existing], []]):
            with self.assertRaises(SupabaseHTTPError) as error:
                request._patch_record("grocery_items", item_id, "household-id", "access-token", {"quantity": 1})
        self.assertEqual(error.exception.status, 409)

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

    def test_snapshot_exposes_both_store_prices_and_cart_totals(self):
        item = {
            "id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "name": "Coke Zero",
            "quantity": 2,
            "unit": "each",
            "price": None,
            "price_confidence": None,
            "status": "open",
        }
        request = object.__new__(handler)
        request._table = Mock(return_value=[item])
        with patch("api.index._supabase_request", return_value=[]):
            snapshot = request._grocery_snapshot("2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "access-token")
        self.assertEqual(set(snapshot["items"][0]["retailer_prices"]), {"coles", "woolworths"})
        self.assertEqual(snapshot["items"][0]["retailer_prices"]["coles"]["line_total"], 8.00)
        self.assertEqual(snapshot["items"][0]["retailer_prices"]["woolworths"]["line_total"], 8.00)
        self.assertEqual(snapshot["retailer_totals"][0]["retailer"], "coles")
        self.assertEqual({row["retailer"] for row in snapshot["retailer_totals"]}, {"coles", "woolworths"})
        self.assertEqual({row["total"] for row in snapshot["retailer_totals"]}, {8.00})

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

    def test_automatic_price_patch_uses_membership_checked_transactional_rpc(self):
        request = object.__new__(handler)
        item = {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "name": "eggs", "quantity": 1, "unit": "each", "category": "Recipe", "price_confidence": None, "price_source": None}
        with patch("api.index._supabase_request", return_value=[item]) as member_request, patch("api.index._supabase_admin_request", return_value=[{**item, "price": 5.70}]) as admin_request:
            result = request._patch_automatic_price(item["id"], "household-id", "access-token", {"price": 5.70}, expected_item=item, actor_user_id="user-id")
        self.assertEqual(result["price"], 5.70)
        self.assertEqual(admin_request.call_args.args[:2], ("POST", "/rest/v1/rpc/apply_grocery_automatic_price"))
        self.assertEqual(admin_request.call_args.kwargs["payload"]["p_actor_user_id"], "user-id")
        member_request.assert_called_once()

    def test_automatic_patch_is_conditional_on_non_manual_current_row(self):
        request = object.__new__(handler)
        item = {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "name": "eggs", "quantity": 1, "unit": "each", "category": "Recipe", "price_confidence": None, "price_source": None}
        with patch("api.index._supabase_request", return_value=[item]) as member_request, patch("api.index._supabase_admin_request", return_value=[]) as admin_request:
            result = request._patch_automatic_price(
                item["id"],
                "household-id",
                "access-token",
                {"price": 5.70},
                expected_item=item,
                actor_user_id="user-id",
            )
        self.assertIsNone(result)
        rpc_payload = admin_request.call_args.kwargs["payload"]
        self.assertIsNone(rpc_payload["p_expected_price_confidence"])
        self.assertIsNone(rpc_payload["p_expected_price_source"])
        self.assertEqual(rpc_payload["p_actor_user_id"], "user-id")

    def test_automatic_patch_uses_exact_metadata_cas_for_whitespace_races(self):
        request = object.__new__(handler)
        current = {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "name": "eggs", "quantity": 1, "unit": "each", "category": "Recipe", "price_confidence": "curated", "price_source": "Catalog title"}
        with patch("api.index._supabase_request", return_value=[current]) as member_request, patch("api.index._supabase_admin_request", return_value=[]) as admin_request:
            request._patch_automatic_price(current["id"], "household-id", "access-token", {"price": 5.70}, expected_item=current, actor_user_id="user-id")
        rpc_payload = admin_request.call_args.kwargs["payload"]
        self.assertEqual(rpc_payload["p_expected_price_confidence"], "curated")
        self.assertEqual(rpc_payload["p_expected_price_source"], "Catalog title")
        self.assertEqual(rpc_payload["p_actor_user_id"], "user-id")

    def test_automatic_patch_checks_current_item_identity_before_pricing(self):
        request = object.__new__(handler)
        expected = {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "name": "eggs", "quantity": 1, "unit": "each", "category": "Recipe"}
        changed = {**expected, "name": "bananas"}
        with patch("api.index._supabase_request", return_value=[changed]) as supabase_request:
            result = request._patch_automatic_price(expected["id"], "household-id", "access-token", {"price": 5.70}, expected_item=expected)
        self.assertIsNone(result)
        self.assertEqual(supabase_request.call_count, 1)

    def test_automatic_patch_uses_case_insensitive_manual_protection(self):
        request = object.__new__(handler)
        current = {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "name": "eggs", "quantity": 1, "unit": "each", "category": "Recipe", "price_confidence": "Manual ", "price_source": None}
        with patch("api.index._supabase_request", return_value=[current]) as supabase_request:
            result = request._patch_automatic_price(current["id"], "household-id", "access-token", {"price": 5.70}, expected_item=current)
        self.assertIsNone(result)
        self.assertEqual(supabase_request.call_count, 1)

    def test_manual_price_endpoint_ignores_client_metadata(self):
        request = object.__new__(handler)
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
        self.assertTrue(request._patch_record.call_args.kwargs["allow_price_metadata"])
        self.assertEqual(request._patch_record.call_args.kwargs["actor_user_id"], "user-id")

    def test_manual_price_endpoint_rejects_invalid_values_as_bad_request(self):
        invalid_values = [None, [], {}, True, -0.01, float("nan"), float("inf")]
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                request = object.__new__(handler)
                request._authenticate = Mock(return_value=("user-id", "access-token", {"email": "person@example.com"}))
                request._context = Mock(return_value=("household-id", []))
                request._patch_record = Mock()
                request._respond = Mock()
                request._route = Mock(return_value="/groceries/price")
                with patch("api.index._json_body", return_value={"item_id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "price": value}):
                    request.do_POST()
                request._respond.assert_called_once()
                self.assertEqual(request._respond.call_args.kwargs["status"], 400)
                request._patch_record.assert_not_called()

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

        request._grocery_snapshot.assert_called_once_with("household-id", "access-token", refresh=True, actor_user_id="user-id")
        response = request._respond.call_args.args[0]
        self.assertEqual(response["auto_updated"], ["eggs"])
        self.assertEqual(response["updated"], 1)
        self.assertEqual(response["updated_items"], ["eggs"])

    def test_quick_add_grocery_uses_authenticated_household_context(self):
        request = object.__new__(handler)
        request.headers = {"X-Hearthstate-Household": "household-id"}
        request._authenticate = Mock(return_value=("user-id", "access-token", {"email": "person@example.com"}))
        request._context = Mock(return_value=("household-id", []))
        request._post_record = Mock(return_value={"id": "item-id", "name": "Milk", "status": "open"})
        request._respond = Mock()

        with patch("api.index._json_body", return_value={"name": "  Milk  "}):
            request._handle_post("/groceries")

        request._post_record.assert_called_once_with(
            "grocery_items",
            "household-id",
            "user-id",
            "access-token",
            {"name": "Milk", "category": "Quick add"},
        )
        self.assertEqual(request._respond.call_args.args[0]["item"]["id"], "item-id")
        self.assertEqual(request._respond.call_args.kwargs["status"], 201)

    def test_quick_add_grocery_rejects_blank_name(self):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("user-id", "access-token", {"email": "person@example.com"}))
        request._context = Mock(return_value=("household-id", []))
        request._post_record = Mock()

        with patch("api.index._json_body", return_value={"name": "  "}):
            with self.assertRaises(ValueError):
                request._handle_post("/groceries")

        request._post_record.assert_not_called()

    def test_grocery_dashboard_exposes_multi_retailer_contract(self):
        html = (Path(__file__).parents[1] / "hearthstate" / "dashboard" / "groceries.html").read_text()
        javascript = (Path(__file__).parents[1] / "hearthstate" / "dashboard" / "groceries.js").read_text()
        self.assertIn('id="retailerComparison"', html)
        self.assertIn('id="comparisonNote"', html)
        self.assertIn('id="bestDeals"', html)
        self.assertIn('id="quickGroceryForm"', html)
        self.assertIn('id="quickGroceryName"', html)
        self.assertIn("/api/groceries/refresh", javascript)
        self.assertIn("/api/groceries", javascript)
        self.assertIn("quickGroceryForm", javascript)
        self.assertIn("retailer_totals", javascript)
        self.assertIn("retailer-price-grid", javascript)
        self.assertIn("best_deals", javascript)
        self.assertIn("recommended_retailer", javascript)
        self.assertIn("comparison_not_comparable_items", javascript)
        self.assertIn("Products compared", javascript)
        self.assertIn("closest pack", javascript)
        self.assertIn("retailer.comparable", javascript)
        self.assertIn("woolworths.com.au", javascript)
        self.assertNotIn("aldi.com.au", javascript)
        self.assertIn("trustedPriceURL", javascript)
        self.assertIn("safePriceURL", javascript)
        self.assertNotIn("source.startsWith(retailer)", javascript)

    def test_quote_refresh_uses_membership_checked_transactional_rpcs(self):
        request = object.__new__(handler)
        comparison = {
            "coles": {"lines": [{"item_id": "item-id", "match": {"product_key": "eggs", "title": "Eggs", "url": "https://www.coles.com.au/product/eggs", "price": 5.70, "observed_at": "2026-08-04", "confidence": "curated", "match_basis": "exact alias", "note": "Observed"}}]},
            "woolworths": {"lines": [{"item_id": "item-id", "match": None}]},
        }
        with patch("api.index._supabase_request") as member_request, patch("api.index._supabase_admin_request") as admin_request:
            request._upsert_price_quotes(comparison, "household-id", "access-token", actor_user_id="user-id")
        self.assertEqual(admin_request.call_args_list[0].args[:2], ("POST", "/rest/v1/rpc/upsert_grocery_price_quote"))
        self.assertEqual(admin_request.call_args_list[1].args[:2], ("POST", "/rest/v1/rpc/delete_grocery_price_quote"))
        self.assertTrue(all(call.kwargs["payload"]["p_actor_user_id"] == "user-id" for call in admin_request.call_args_list))
        member_request.assert_not_called()

    def test_database_migration_removes_direct_grocery_price_writes(self):
        migrations = Path(__file__).parents[1] / "supabase" / "migrations"
        migration = (migrations / "20260804030000_harden_grocery_price_boundaries.sql").read_text()
        self.assertIn("revoke insert, update on public.grocery_items from authenticated", migration)
        self.assertIn("grant insert (household_id, name, quantity, unit, category, status, created_by)", migration)
        self.assertIn("grant update (name, quantity, unit, category, status)", migration)
        self.assertIn("revoke insert, update, delete on public.grocery_price_quotes from authenticated", migration)
        self.assertIn("grant select on public.grocery_price_quotes to authenticated", migration)
        self.assertIn("create or replace function public.set_grocery_manual_price", migration)
        self.assertIn("create or replace function public.apply_grocery_automatic_price", migration)
        self.assertIn("create or replace function public.upsert_grocery_price_quote", migration)
        self.assertIn("create or replace function public.delete_grocery_price_quote", migration)
        for function_name in ("set_grocery_manual_price", "apply_grocery_automatic_price", "upsert_grocery_price_quote", "delete_grocery_price_quote"):
            self.assertIn(f"revoke all on function public.{function_name}", migration)
            self.assertIn(f"grant execute on function public.{function_name}", migration)
        self.assertGreaterEqual(migration.count("from public, authenticated"), 4)
        self.assertGreaterEqual(migration.count("to service_role"), 4)
        self.assertGreaterEqual(migration.count("for update"), 4)
        self.assertGreaterEqual(migration.count("p_actor_user_id"), 4)


        migration = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260804010000_grocery_price_quotes.sql").read_text()
        self.assertIn("create table if not exists public.grocery_price_quotes", migration)
        self.assertIn("unique (grocery_item_id, retailer)", migration)
        self.assertIn("check (retailer in ('coles', 'aldi', 'woolworths'))", migration)
        self.assertIn("alter table public.grocery_price_quotes enable row level security", migration)
        self.assertIn("private.is_household_member(household_id)", migration)
        self.assertIn("grant select, insert, update, delete on public.grocery_price_quotes to authenticated", migration)
        self.assertNotIn("service_role", migration)
        live_migration = (migrations / "20260806010000_coles_woolworths_live_quotes.sql").read_text()
        self.assertIn("delete from public.grocery_price_quotes", live_migration)
        self.assertIn("check (retailer in ('coles', 'woolworths'))", live_migration)
        self.assertIn("comparison_key", live_migration)
        self.assertIn("drop function if exists public.upsert_grocery_price_quote", live_migration)
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
            "woolworths": {"lines": [{"item_id": "item-id", "match": None}]},
        }

        with patch("api.index._supabase_admin_request") as admin_request:
            request._upsert_price_quotes(comparison, "household-id", "access-token", actor_user_id="user-id")

        self.assertEqual(admin_request.call_count, 2)
        post_call = admin_request.call_args_list[0]
        self.assertEqual(post_call.args[:2], ("POST", "/rest/v1/rpc/upsert_grocery_price_quote"))
        self.assertEqual(post_call.kwargs["payload"]["p_household_id"], "household-id")
        self.assertEqual(post_call.kwargs["payload"]["p_grocery_item_id"], "item-id")
        delete_call = admin_request.call_args_list[1]
        self.assertEqual(delete_call.args[:2], ("POST", "/rest/v1/rpc/delete_grocery_price_quote"))
        self.assertEqual(delete_call.kwargs["payload"]["p_household_id"], "household-id")


if __name__ == "__main__":
    unittest.main()
