from pathlib import Path
from unittest.mock import Mock, patch
import unittest

from api.index import _sanitize_pilot_metadata, handler


class PilotInstrumentationTests(unittest.TestCase):
    def test_metadata_keeps_only_contract_fields_and_never_raw_capture_text(self):
        sanitized = _sanitize_pilot_metadata(
            "capture_created",
            {
                "source": "dashboard",
                "private": True,
                "original_text": "Pick up the children from school at 3pm",
                "unexpected": "discard me",
            },
        )
        self.assertEqual(sanitized, {"source": "dashboard", "private": True})
        self.assertEqual(_sanitize_pilot_metadata("briefing_acted_on", {"action": "raw household text"}), {})

    def test_record_event_uses_service_role_rpc_and_server_bound_identity(self):
        request = object.__new__(handler)
        with patch("api.index._supabase_admin_request", return_value=[{"id": 1}]) as admin_request:
            request._record_pilot_event(
                "household-id",
                "user-id",
                "task_completed",
                entity_type="task",
                entity_id="2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
                metadata={"source": "dashboard", "title": "Do not store this"},
                dedupe_key="task:2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            )
        self.assertEqual(admin_request.call_args.args[:2], ("POST", "/rest/v1/rpc/record_pilot_event"))
        payload = admin_request.call_args.kwargs["payload"]
        self.assertEqual(payload["p_actor_user_id"], "user-id")
        self.assertEqual(payload["p_household_id"], "household-id")
        self.assertEqual(payload["p_event_name"], "task_completed")
        self.assertEqual(payload["p_metadata"], {"source": "dashboard"})
        self.assertNotIn("title", payload["p_metadata"])

    def test_record_event_never_breaks_a_mutation_on_transient_network_failure(self):
        request = object.__new__(handler)
        with patch("api.index._supabase_admin_request", side_effect=TimeoutError("timed out")):
            request._record_pilot_event("household-id", "user-id", "task_completed", metadata={"source": "dashboard"})

    def test_client_signal_endpoint_rejects_client_entity_ids(self):
        request = object.__new__(handler)
        request._authenticate = lambda: ("user-id", "access-token", {})
        request._context = lambda user_id, token: ("household-id", [])
        request._record_pilot_event = Mock()
        with patch("api.index._json_body", return_value={
            "event_name": "briefing_opened",
            "entity_id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "metadata": {"source": "client"},
        }):
            with self.assertRaises(ValueError):
                request._handle_post("/pilot/events")
        request._record_pilot_event.assert_not_called()

    def test_pilot_migration_is_first_party_and_service_role_write_only(self):
        migration = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260804040000_pilot_instrumentation.sql").read_text()
        self.assertIn("create table if not exists public.pilot_events", migration)
        self.assertIn("alter table public.pilot_events enable row level security", migration)
        self.assertIn("revoke select, insert, update, delete on public.pilot_events from public, anon, authenticated, service_role", migration)
        self.assertIn("create or replace function public.record_pilot_event", migration)
        self.assertIn("event_metadata jsonb", migration)
        self.assertIn("p_event_name in", migration)
        self.assertIn("jsonb_build_object('source'", migration)
        self.assertIn("for update", migration)
        self.assertIn("on conflict (household_id, event_name, dedupe_key)", migration)
        for event_name in ("household_created", "member_invited", "member_active", "capture_created", "capture_converted", "task_completed", "briefing_opened", "briefing_acted_on", "conflict_resolved"):
            self.assertIn(f"'{event_name}'", migration)

    def test_client_signal_endpoint_accepts_only_briefing_and_conflict_events(self):
        request = object.__new__(handler)
        request._authenticate = lambda: ("user-id", "access-token", {})
        request._context = lambda user_id, token: ("household-id", [])
        request._record_pilot_event = patch("api.index.handler._record_pilot_event").start()
        request._respond = patch("api.index.handler._respond").start()
        try:
            with patch("api.index._json_body", return_value={"event_name": "briefing_acted_on", "metadata": {"action": "task_completed", "original_text": "never store"}}):
                request._handle_post("/pilot/events")
            request._record_pilot_event.assert_called_once_with(
                "household-id",
                "user-id",
                "briefing_acted_on",
                entity_type="briefing",
                metadata={"action": "task_completed", "original_text": "never store"},
            )
            request._respond.assert_called_once_with({"recorded": True})
        finally:
            patch.stopall()

    def test_task_completion_emits_a_privacy_safe_event(self):
        request = object.__new__(handler)
        request._authenticate = lambda: ("user-id", "access-token", {})
        request._context = lambda user_id, token: ("household-id", [])
        request._complete_task = lambda *args, **kwargs: {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "status": "done"}
        request._respond = patch("api.index.handler._respond").start()
        request._record_pilot_event = patch("api.index.handler._record_pilot_event").start()
        try:
            with patch("api.index._json_body", return_value={}):
                request._handle_post("/tasks/2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47/complete")
            request._record_pilot_event.assert_called_once_with(
                "household-id",
                "user-id",
                "task_completed",
                entity_type="task",
                entity_id="2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
                metadata={"source": "dashboard"},
                dedupe_key="task:2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            )
        finally:
            patch.stopall()

    def test_household_creation_emits_household_created(self):
        request = object.__new__(handler)
        request._authenticate = lambda: ("user-id", "access-token", {})
        request._respond = Mock()
        request._record_pilot_event = Mock()
        with patch("api.index._json_body", return_value={"name": "The Home"}), patch("api.index._supabase_request", return_value=[{"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47"}]):
            request._handle_post("/households")
        request._record_pilot_event.assert_called_once_with(
            "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "user-id",
            "household_created",
            entity_type="household",
            entity_id="2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            metadata={"source": "setup"},
            dedupe_key="household:2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
        )

    def test_household_creation_still_succeeds_if_event_identifier_is_missing(self):
        request = object.__new__(handler)
        request._authenticate = lambda: ("user-id", "access-token", {})
        request._respond = Mock()
        request._record_pilot_event = Mock()
        with patch("api.index._json_body", return_value={"name": "The Home"}), patch("api.index._supabase_request", return_value=[{}]):
            request._handle_post("/households")
        request._respond.assert_called_once_with({"household": {}}, status=201)
        request._record_pilot_event.assert_not_called()

    def test_dashboard_open_emits_daily_active_and_opened_events(self):
        request = object.__new__(handler)
        request._authenticate = lambda: ("user-id", "access-token", {})
        request._context = lambda user_id, token: ("household-id", [])
        request.path = "/api/index.py?route=/dashboard"
        request._dashboard = Mock(return_value={})
        request._respond = Mock()
        request._record_pilot_event = Mock()
        with patch("api.index._iso_now", return_value="2026-08-04T12:00:00+00:00"):
            request._handle_get("/dashboard")
        self.assertEqual(request._record_pilot_event.call_count, 2)
        self.assertEqual(request._record_pilot_event.call_args_list[0].args[:3], ("household-id", "user-id", "member_active"))
        self.assertEqual(request._record_pilot_event.call_args_list[0].kwargs["dedupe_key"], "active:user-id:2026-08-04")
        self.assertEqual(request._record_pilot_event.call_args_list[1].args[:3], ("household-id", "user-id", "dashboard_opened"))
        self.assertEqual(request._record_pilot_event.call_args_list[1].kwargs["dedupe_key"], "dashboard:user-id:2026-08-04")

    def test_capture_creation_and_conversion_emit_funnel_events_without_text(self):
        request = object.__new__(handler)
        request._authenticate = lambda: ("user-id", "access-token", {})
        request._context = lambda user_id, token: ("household-id", [])
        request._create_inbox_capture = Mock(return_value={"item": {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47"}, "suggestion": {"id": "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48"}})
        request._respond = Mock()
        request._record_pilot_event = Mock()
        with patch("api.index._json_body", return_value={"original_text": "private school note", "source": "dashboard", "private": True}):
            request._handle_post("/inbox")
        request._record_pilot_event.assert_called_once_with(
            "household-id",
            "user-id",
            "capture_created",
            entity_type="capture",
            entity_id="2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            metadata={"source": "dashboard", "private": True},
            dedupe_key="capture:2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
        )
        request._record_pilot_event.reset_mock()
        with patch("api.index._json_body", return_value={
            "suggestion_id": "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48",
            "decision": "accept",
            "suggestion_type": "task",
            "payload": {"title": "School form", "due_at": "2026-08-05T09:00:00+00:00"},
        }), patch("api.index._supabase_request", return_value={"created_type": "task"}):
            request._handle_post("/inbox/2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47/suggestion/review")
        request._record_pilot_event.assert_called_once_with(
            "household-id",
            "user-id",
            "capture_converted",
            entity_type="capture",
            entity_id="2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            metadata={"conversion_type": "task"},
            dedupe_key="conversion:2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
        )

    def test_invitation_creation_emits_member_invited_without_email(self):
        request = object.__new__(handler)
        request._authenticate = lambda: ("user-id", "access-token", {})
        request._context = lambda user_id, token: ("household-id", [])
        request._role = lambda household_id, user_id, token: "owner"
        request._respond = Mock()
        request._record_pilot_event = Mock()
        invitation = {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "email": "member@example.com", "role": "member"}
        with patch("api.index._json_body", return_value={"email": "member@example.com", "role": "member"}), patch("api.index.secrets.token_urlsafe", return_value="raw-token"), patch("api.index._supabase_request", return_value=[invitation]):
            request._handle_post("/auth/invitations")
        request._record_pilot_event.assert_called_once_with(
            "household-id",
            "user-id",
            "member_invited",
            entity_type="invitation",
            entity_id="2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            metadata={"role": "member"},
            dedupe_key="invitation:2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
        )

    def test_data_export_includes_metadata_only_pilot_events(self):
        portability = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260804050000_export_pilot_events.sql").read_text()
        self.assertIn("'pilot_events'", portability)
        self.assertIn("from public.pilot_events", portability)

    def test_data_export_serializes_owner_authorization_with_membership_lock(self):
        portability = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260804050000_export_pilot_events.sql").read_text()
        self.assertIn("owner_membership public.memberships", portability)
        self.assertIn("select * into owner_membership", portability)
        self.assertIn("for update", portability)


if __name__ == "__main__":
    unittest.main()
