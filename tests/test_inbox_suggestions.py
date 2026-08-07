import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from api.index import _suggestion_for_capture, handler


CAPTURE_ID = "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47"
SUGGESTION_ID = "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48"
HOUSEHOLD_ID = "4e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf49"
USER_ID = "5e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf40"


class InboxSuggestionTests(unittest.TestCase):
    def test_capture_parser_proposes_a_grocery_without_mutating_state(self):
        suggestion = _suggestion_for_capture("Buy oat milk and bananas")
        self.assertEqual(suggestion["suggestion_type"], "grocery")
        self.assertEqual(suggestion["proposed_payload"]["name"], "oat milk and bananas")
        self.assertEqual(suggestion["status"], "pending")

    def test_capture_parser_defaults_ambiguous_text_to_a_task(self):
        suggestion = _suggestion_for_capture("Remember to call the school")
        self.assertEqual(suggestion["suggestion_type"], "task")
        self.assertEqual(suggestion["proposed_payload"], {"title": "Remember to call the school"})

    def test_capture_uses_atomic_rpc_and_server_bound_identity(self):
        request = object.__new__(handler)
        request._authenticate = lambda: (USER_ID, "access-token", {})
        request._context = lambda user_id, token: (HOUSEHOLD_ID, [])
        request._respond = Mock()
        rpc_result = {
            "item": {"id": CAPTURE_ID, "status": "open"},
            "suggestion": {"id": SUGGESTION_ID, "status": "pending", "suggestion_type": "grocery"},
        }
        with patch("api.index._json_body", return_value={
            "original_text": "Buy oat milk",
            "source": "dashboard",
            "private": True,
            "household_id": "attacker-household",
            "created_by": "attacker",
        }), patch("api.index._supabase_request", return_value=rpc_result) as supabase_request:
            request._handle_post("/inbox")

        supabase_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/create_inbox_capture",
            token="access-token",
            payload={
                "p_household_id": HOUSEHOLD_ID,
                "p_actor_user_id": USER_ID,
                "p_original_text": "Buy oat milk",
                "p_source": "dashboard",
                "p_private": True,
                "p_suggestion_type": "grocery",
                "p_proposed_payload": {"name": "oat milk", "quantity": 1, "unit": "each", "category": "Inbox"},
            },
        )
        request._respond.assert_called_once_with(rpc_result, status=201)

    def test_inbox_read_returns_suggestions_next_to_captures(self):
        request = object.__new__(handler)
        request._authenticate = lambda: (USER_ID, "access-token", {})
        request._context = lambda user_id, token: (HOUSEHOLD_ID, [])
        request.path = "/api/index.py?route=/api/inbox"
        request._inbox_snapshot = Mock(return_value=[
            {"id": CAPTURE_ID, "original_text": "Buy oat milk", "suggestion": {"id": SUGGESTION_ID, "status": "pending"}},
        ])
        request._respond = Mock()

        request._handle_get("/inbox")

        request._inbox_snapshot.assert_called_once_with(HOUSEHOLD_ID, USER_ID, "access-token")
        request._respond.assert_called_once()
        self.assertEqual(request._respond.call_args.args[0]["items"][0]["suggestion"]["id"], SUGGESTION_ID)

    def test_inbox_snapshot_uses_actor_bound_read_rpc(self):
        request = object.__new__(handler)
        snapshot = [{"id": CAPTURE_ID, "private": True, "suggestion": {"id": SUGGESTION_ID}}]
        with patch("api.index._supabase_request", return_value=snapshot) as supabase_request:
            result = request._inbox_snapshot(HOUSEHOLD_ID, USER_ID, "service-role-token")
        self.assertEqual(result, snapshot)
        supabase_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/read_inbox_snapshot",
            token="service-role-token",
            payload={"p_household_id": HOUSEHOLD_ID, "p_actor_user_id": USER_ID},
        )

    def test_capture_rejects_non_string_text_and_source(self):
        request = object.__new__(handler)
        with self.assertRaisesRegex(ValueError, "original_text must be a string"):
            request._create_inbox_capture(HOUSEHOLD_ID, USER_ID, "access-token", {"original_text": ["buy milk"]})
        with self.assertRaisesRegex(ValueError, "source must be a string"):
            request._create_inbox_capture(HOUSEHOLD_ID, USER_ID, "access-token", {"original_text": "buy milk", "source": {"name": "api"}})

    def test_review_accept_uses_transactional_rpc_and_ignores_client_identity(self):
        request = object.__new__(handler)
        request._authenticate = lambda: (USER_ID, "access-token", {})
        request._context = lambda user_id, token: (HOUSEHOLD_ID, [])
        request._respond = Mock()
        request._record_pilot_event = Mock()
        rpc_result = {"decision": "accepted", "suggestion": {"id": SUGGESTION_ID, "status": "accepted"}, "created": {"id": "task-id"}, "created_type": "task"}
        with patch("api.index._json_body", return_value={
            "suggestion_id": SUGGESTION_ID,
            "decision": "accept",
            "suggestion_type": "task",
            "payload": {"title": "Call the school", "due_at": None},
            "household_id": "attacker-household",
            "actor": "attacker",
        }), patch("api.index._supabase_request", return_value=rpc_result) as supabase_request:
            request._handle_post(f"/inbox/{CAPTURE_ID}/suggestion/review")

        supabase_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/review_inbox_suggestion",
            token="access-token",
            payload={
                "p_household_id": HOUSEHOLD_ID,
                "p_actor_user_id": USER_ID,
                "p_inbox_item_id": CAPTURE_ID,
                "p_suggestion_id": SUGGESTION_ID,
                "p_decision": "accept",
                "p_suggestion_type": "task",
                "p_proposed_payload": {"title": "Call the school", "due_at": None},
            },
        )
        request._respond.assert_called_once_with(rpc_result)
        request._record_pilot_event.assert_called_once_with(
            HOUSEHOLD_ID,
            USER_ID,
            "capture_converted",
            entity_type="capture",
            entity_id=CAPTURE_ID,
            metadata={"conversion_type": "task"},
            dedupe_key=f"conversion:{CAPTURE_ID}",
        )

    def test_review_reject_does_not_allow_a_client_to_change_household(self):
        request = object.__new__(handler)
        request._authenticate = lambda: (USER_ID, "access-token", {})
        request._context = lambda user_id, token: (HOUSEHOLD_ID, [])
        request._respond = Mock()
        with patch("api.index._json_body", return_value={"suggestion_id": SUGGESTION_ID, "decision": "reject"}), patch("api.index._supabase_request", return_value={}) as supabase_request:
            request._handle_post(f"/inbox/{CAPTURE_ID}/suggestion/review")
        self.assertEqual(supabase_request.call_args.kwargs["payload"]["p_household_id"], HOUSEHOLD_ID)
        self.assertEqual(supabase_request.call_args.kwargs["payload"]["p_actor_user_id"], USER_ID)
        self.assertIsNone(supabase_request.call_args.kwargs["payload"]["p_proposed_payload"])

    def test_archive_rejects_pending_suggestion_transactionally(self):
        request = object.__new__(handler)
        request._authenticate = lambda: (USER_ID, "access-token", {})
        request._context = lambda user_id, token: (HOUSEHOLD_ID, [])
        request._respond = Mock()
        with patch("api.index._json_body", return_value={}), patch("api.index._supabase_request", return_value={"decision": "rejected"}) as supabase_request:
            request._handle_post(f"/inbox/{CAPTURE_ID}/archive")
        self.assertEqual(supabase_request.call_count, 1)
        self.assertEqual(supabase_request.call_args.args[1], "/rest/v1/rpc/archive_inbox_capture")
        self.assertEqual(supabase_request.call_args.kwargs["payload"]["p_inbox_item_id"], CAPTURE_ID)
        request._respond.assert_called_once_with({"decision": "rejected"})

    def test_photon_capture_and_archive_use_the_same_atomic_inbox_boundary(self):
        request = object.__new__(handler)
        request._channel_integration = Mock(return_value={"id": "integration-id"})
        request._channel_context = Mock(return_value=({"household_id": HOUSEHOLD_ID}, USER_ID, "service-role-token", {}))
        request._create_inbox_capture = Mock(return_value={
            "item": {"id": CAPTURE_ID, "status": "open"},
            "suggestion": {"id": SUGGESTION_ID, "status": "pending"},
        })
        request._archive_inbox_capture = Mock(return_value={"decision": "rejected"})
        request._record_pilot_event = Mock()

        captured = request._photon_command({"action": "capture", "text": "Buy rice", "private": False})
        self.assertEqual(captured["suggestion"]["status"], "pending")
        request._create_inbox_capture.assert_called_once_with(
            HOUSEHOLD_ID,
            USER_ID,
            "service-role-token",
            {"original_text": "Buy rice", "source": "photon", "private": False},
        )

        archived = request._photon_command({"action": "archive_inbox", "item_id": CAPTURE_ID})
        self.assertEqual(archived["decision"], "rejected")
        request._archive_inbox_capture.assert_called_once_with(HOUSEHOLD_ID, USER_ID, "service-role-token", CAPTURE_ID)

    def test_suggestion_migration_has_rls_and_atomic_review_boundary(self):
        migrations = Path(__file__).parents[1] / "supabase" / "migrations"
        migration = next(migrations.glob("*_inbox_suggestions.sql")).read_text()
        self.assertIn("create table if not exists public.inbox_suggestions", migration)
        self.assertIn("alter table public.inbox_suggestions enable row level security", migration)
        self.assertIn("create or replace function public.create_inbox_capture", migration)
        self.assertIn("create or replace function public.review_inbox_suggestion", migration)
        self.assertIn("create or replace function public.archive_inbox_capture", migration)
        self.assertIn("create or replace function public.read_inbox_snapshot", migration)
        self.assertIn("create unique index if not exists inbox_items_household_id_id_key", migration)
        self.assertIn("foreign key (household_id, inbox_item_id)", migration)
        self.assertIn("for update", migration)
        self.assertIn("inbox.suggestion_accepted", migration)
        self.assertIn("inbox.suggestion_rejected", migration)
        self.assertIn("private.is_household_member", migration)
        self.assertIn("grant execute on function public.create_inbox_capture(uuid, uuid, text, text, boolean, text, jsonb) to authenticated, service_role", migration)
        self.assertIn("auth.role()", migration)
        self.assertIn("p_actor_user_id)", migration)
        self.assertIn("public.create_meal", migration)
        self.assertIn("grant execute on function public.review_inbox_suggestion(uuid, uuid, uuid, uuid, text, text, jsonb) to authenticated, service_role", migration)
        self.assertIn("grant execute on function public.archive_inbox_capture(uuid, uuid, uuid) to authenticated, service_role", migration)
        self.assertIn("grant execute on function public.read_inbox_snapshot(uuid, uuid) to authenticated, service_role", migration)
        self.assertIn("where household_id = p_household_id and user_id = p_actor_user_id", migration)
        self.assertIn("not item.private or item.created_by = p_actor_user_id", migration)
        self.assertIn("capture_row.private", migration)
        self.assertIn("capture_row.status <> 'open'", migration)
        self.assertIn("on conflict (inbox_item_id) do nothing", migration)
        self.assertIn("status in ('pending', 'accepted', 'rejected')", migration)

    def test_dashboard_uses_review_endpoint_and_no_longer_posts_direct_conversion(self):
        dashboard = Path(__file__).parents[1] / "hearthstate" / "dashboard"
        app = (dashboard / "app.js").read_text()
        html = (dashboard / "index.html").read_text()
        self.assertIn("/suggestion/review", app)
        self.assertIn("Confirm suggestion", html)
        self.assertIn('/app.js?v=hearthstate-6', html)
        self.assertRegex(html, r'/styles\.css\?v=[^"\']+')
        self.assertNotIn("/convert`,", app)
        self.assertNotIn("Save and clear Inbox item", html)

    def test_legacy_direct_conversion_is_blocked(self):
        request = object.__new__(handler)
        request._authenticate = lambda: (USER_ID, "access-token", {})
        request._context = lambda user_id, token: (HOUSEHOLD_ID, [])
        request._respond = Mock()
        with patch("api.index._json_body", return_value={"type": "task", "title": "Do not bypass review"}):
            request._handle_post(f"/inbox/{CAPTURE_ID}/convert")
        request._respond.assert_called_once_with(
            {"error": "Inbox items must be reviewed through their suggestion before conversion"},
            status=409,
        )


if __name__ == "__main__":
    unittest.main()
