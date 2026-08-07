import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import api.index as hosted_api
from api.index import _channel_token_hash, _inject_viewer_bootstrap, _normalize_channel_identity, _rows, _supabase_admin_request, _supabase_request, _uuid, handler


class HostedApiContractTests(unittest.TestCase):
    def test_inbox_capture_splitter_preserves_conservative_multi_action_boundaries(self):
        self.assertEqual(
            hosted_api._split_inbox_captures("Buy milk\nBook dentist; plan tacos"),
            ["Buy milk", "Book dentist", "plan tacos"],
        )
        self.assertEqual(hosted_api._split_inbox_captures("Remember to bring the red folder and keys"), ["Remember to bring the red folder and keys"])

    @patch("api.index._json_body", return_value={
        "items": ["Buy milk", "Book dentist"],
        "source": "dashboard",
        "private": False,
    })
    def test_inbox_batch_capture_creates_one_reviewable_item_per_action(self, _json_body):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", {}))
        request._create_inbox_captures_batch = Mock(return_value={
            "captures": [
                {"item": {"id": "item-1"}, "suggestion": {"suggestion_type": "grocery"}},
                {"item": {"id": "item-2"}, "suggestion": {"suggestion_type": "task"}},
            ]
        })
        request._record_pilot_event = Mock()
        request._respond = Mock()

        request._handle_post("/inbox/batch")

        request._create_inbox_captures_batch.assert_called_once()
        request._record_pilot_event.assert_not_called()
        self.assertEqual(request._respond.call_args.args[0]["created_count"], 2)
        self.assertEqual(request._respond.call_args.kwargs["status"], 201)

    @patch("api.index._json_body", return_value={"items": ["Buy milk", "x" * 4001]})
    def test_inbox_batch_rejects_invalid_item_before_database_call(self, _json_body):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", {}))
        request._create_inbox_captures_batch = Mock()
        request._json_body = Mock(return_value={"items": ["Buy milk", "x" * 4001]})
        request._respond = Mock()

        with self.assertRaises(ValueError):
            request._handle_post("/inbox/batch")

        request._create_inbox_captures_batch.assert_not_called()

    def test_context_uses_a_valid_household_selection_cookie(self):
        request = object.__new__(handler)
        request.path = "/api/index.py"
        request.headers = {"Cookie": "HearthstateHousehold=3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48"}
        request._memberships = Mock(return_value=[
            {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "name": "First"},
            {"id": "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48", "name": "Second"},
        ])

        household_id, _ = request._context("viewer-id", "session-token")

        self.assertEqual(household_id, "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48")

    @patch("api.index._json_body", return_value={"household_id": "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48"})
    def test_household_selection_sets_a_scoped_cookie_after_membership_check(self, _json_body):
        request = object.__new__(handler)
        request.path = "/api/index.py"
        request.headers = {}
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._memberships = Mock(return_value=[
            {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "name": "First"},
            {"id": "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48", "name": "Second"},
        ])
        request._respond = Mock()

        request._handle_post("/households/select")

        headers = request._respond.call_args.kwargs["headers"]
        self.assertIn("HearthstateHousehold=3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48", headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", headers["Set-Cookie"])

    def test_branded_login_exposes_temporary_password_fallback(self):
        dashboard = Path(__file__).parents[1] / "hearthstate" / "dashboard"
        login_html = (dashboard / "hosted-login.html").read_text()
        login_js = (dashboard / "login.js").read_text()
        self.assertIn('id="passwordPanel"', login_html)
        self.assertNotIn('id="legacyChooser"', login_html)
        self.assertNotIn('/user-images/', login_html)
        self.assertIn('"hosted-login.html"', (Path(__file__).parents[1] / "api" / "index.py").read_text())
        self.assertIn('/auth/v1/token?grant_type=password', login_js)
        self.assertIn('establishHostedSession(session.access_token)', login_js)
        self.assertIn('redirect_to: hostedLoginRedirect()', login_js)
        self.assertIn("new URL('/login', window.location.origin)", login_js)
        self.assertIn('window.location.hash.replace', login_js)
        self.assertIn('establishHostedSession(accessToken)', login_js)
        self.assertNotIn("/api/session", login_js)
        self.assertNotIn("data-user", login_js)

    def test_multi_household_selection_shell_and_invitation_redirect_are_wired(self):
        dashboard = Path(__file__).parents[1] / "hearthstate" / "dashboard"
        selector = (dashboard / "household-select.html").read_text()
        invite_js = (dashboard / "invite.js").read_text()
        api_source = (Path(__file__).parents[1] / "api" / "index.py").read_text()
        vercel = (Path(__file__).parents[1] / "vercel.json").read_text()
        self.assertIn('id="householdList"', selector)
        self.assertIn("/households/select", (dashboard / "household-select.js").read_text())
        self.assertIn("/select-household", invite_js)
        self.assertIn('"household-select.html"', api_source)
        self.assertIn("/select-household", vercel)
        self.assertIn("/household-select.js", vercel)

    def test_root_redirects_to_selection_when_a_multi_household_session_has_no_choice(self):
        request = object.__new__(handler)
        request.path = "/"
        request.headers = {}
        request._token = Mock(return_value="session-token")
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._memberships = Mock(return_value=[{"id": "household-1"}, {"id": "household-2"}])
        request._redirect = Mock()
        request._send_bytes = Mock()

        self.assertTrue(request._handle_asset("/"))

        request._redirect.assert_called_once_with("/select-household")
        request._send_bytes.assert_not_called()

    def test_root_redirects_when_household_selection_cookie_is_stale(self):
        request = object.__new__(handler)
        request.path = "/"
        request.headers = {"Cookie": "HearthstateHousehold=4e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf49"}
        request._token = Mock(return_value="session-token")
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._memberships = Mock(return_value=[{"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47"}])
        request._redirect = Mock()
        request._send_bytes = Mock()

        self.assertTrue(request._handle_asset("/"))

        request._redirect.assert_called_once_with("/select-household")
        request._send_bytes.assert_not_called()

    def test_protected_page_redirects_to_selection_before_serving_shell(self):
        request = object.__new__(handler)
        request.path = "/tasks"
        request.headers = {"Cookie": ""}
        request._token = Mock(return_value="session-token")
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._memberships = Mock(return_value=[{"id": "11111111-1111-4111-8111-111111111111"}, {"id": "22222222-2222-4222-8222-222222222222"}])
        request._redirect = Mock()
        request._send_bytes = Mock()

        request._handle_asset("/tasks")

        request._redirect.assert_called_once_with("/select-household")
        request._send_bytes.assert_not_called()

    @patch("api.index._json_body", return_value={"delivery_date": "2026-08-08"})
    def test_notification_queue_is_idempotent_per_member_and_delivery_date(self, _json_body):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._context = Mock(return_value=("2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", {}))
        request._respond = Mock()
        with patch("api.index._supabase_request", side_effect=[
            [{"enabled": True, "channel": "email", "preferred_time": "07:00"}],
            {"queued": True, "delivery": {"id": "delivery-id", "status": "queued", "idempotency_key": "morning:2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47:viewer-id:2026-08-08"}},
        ]) as supabase_request:
            request._handle_post("/notifications/queue")

        delivery = request._respond.call_args.args[0]["delivery"]
        self.assertEqual(delivery["status"], "queued")
        queue_rpc = supabase_request.call_args_list[1]
        self.assertEqual(queue_rpc.args[1], "/rest/v1/rpc/queue_notification_delivery")
        self.assertEqual(queue_rpc.kwargs["payload"]["p_delivery_date"], "2026-08-08")

    def test_release_two_contract_is_wired_into_hosted_assets(self):
        root = Path(__file__).parents[1]
        dashboard = root / "hearthstate" / "dashboard"
        index_html = (dashboard / "index.html").read_text()
        app_js = (dashboard / "app.js").read_text()
        notifications_html = (dashboard / "notifications.html").read_text()
        notifications_js = (dashboard / "notifications.js").read_text()
        migration = "".join(path.read_text() for path in (root / "supabase" / "migrations").glob("*notification_delivery*.sql"))
        vercel = (root / "vercel.json").read_text()
        dispatch_workflow = (root / ".github" / "workflows" / "notification-dispatch.yml").read_text()
        self.assertIn("data-quick-action=", index_html)
        self.assertIn("completeVisibleAttention", app_js)
        self.assertIn("/api/notifications/queue", notifications_js)
        self.assertIn("id=\"queueBriefing\"", notifications_html)
        self.assertIn("notification_deliveries", migration)
        self.assertIn("idempotency_key", migration)
        self.assertIn("queue_notification_delivery", migration)
        self.assertIn("cancel_notification_deliveries", migration)
        self.assertIn("grant select on public.notification_deliveries to authenticated", migration)
        self.assertNotIn("grant select, insert, update on public.notification_deliveries to authenticated", migration)
        self.assertIn("p.channel = 'email'", migration)
        self.assertIn("quiet_start", migration)
        self.assertIn("for update", migration)
        self.assertNotIn('"crons"', vercel)
        self.assertIn('cron: "*/15 * * * *"', dispatch_workflow)
        self.assertIn("HEARTHSTATE_CRON_SECRET", dispatch_workflow)

    def test_notification_dispatch_claims_and_marks_delivery_sent(self):
        request = object.__new__(handler)
        request.headers = {"Authorization": "Bearer cron-secret"}
        request._respond = Mock()
        delivery = {"id": "delivery-id", "claim_token": "claim-token", "status": "sending", "attempts": 1, "recipient_email": "person@example.com", "subject": "Briefing", "body": "Open Hearthstate"}
        with patch("api.index._json_body", return_value={}), \
             patch.dict("os.environ", {"HEARTHSTATE_CRON_SECRET": "cron-secret", "SUPABASE_SERVICE_ROLE_KEY": "service-key"}, clear=False), \
             patch("api.index._supabase_admin_request", side_effect=[[], [delivery], {}]) as admin_request, \
             patch("api.index._send_notification_email", return_value="provider-message-id"):
            request._handle_post("/notifications/dispatch")

        response = request._respond.call_args.args[0]
        self.assertEqual(response["sent"], 1)
        self.assertEqual(admin_request.call_args_list[-1].kwargs["payload"]["status"], "sent")

    def test_notification_dispatch_rejects_unfenced_claims_without_sending(self):
        request = object.__new__(handler)
        request.headers = {"Authorization": "Bearer cron-secret"}
        request._respond = Mock()
        delivery = {"id": "delivery-id", "status": "sending", "attempts": 1, "recipient_email": "person@example.com", "subject": "Briefing", "body": "Open Hearthstate"}
        with patch("api.index._json_body", return_value={}), patch.dict("os.environ", {"HEARTHSTATE_CRON_SECRET": "cron-secret", "SUPABASE_SERVICE_ROLE_KEY": "service-key"}, clear=False), \
             patch("api.index._supabase_admin_request", side_effect=[[], [delivery]]) as admin_request, \
             patch("api.index._send_notification_email") as send_email:
            with self.assertRaisesRegex(hosted_api.SupabaseHTTPError, "unfenced"):
                request._handle_post("/notifications/dispatch")
        send_email.assert_not_called()
        self.assertEqual(admin_request.call_count, 2)

    def test_notification_dispatch_requires_cron_authentication(self):
        request = object.__new__(handler)
        request.headers = {}
        request._respond = Mock()
        with patch("api.index._json_body", return_value={}), patch.dict("os.environ", {}, clear=False):
            with self.assertRaises(hosted_api.SupabaseHTTPError) as error:
                request._handle_post("/notifications/dispatch")
        self.assertEqual(error.exception.status, 401)

    def test_notification_provider_requires_a_message_id(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"{}"
        with patch.dict("os.environ", {"RESEND_API_KEY": "provider-key", "HEARTHSTATE_NOTIFICATION_FROM": "Hearthstate <briefing@example.com>"}, clear=False), patch("api.index.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "provider response"):
                hosted_api._send_notification_email({"recipient_email": "person@example.com", "subject": "Briefing", "body": "Open Hearthstate"})

    def test_notification_dispatch_skips_malformed_preferences_without_aborting(self):
        request = object.__new__(handler)
        request.headers = {"Authorization": "Bearer cron-secret"}
        request._respond = Mock()
        malformed = {"household_id": "household-id", "user_id": "viewer-id", "preferred_time": "not-a-time", "quiet_start": "21:00", "quiet_end": "07:00", "enabled": True, "channel": "email"}
        with patch("api.index._json_body", return_value={}), \
             patch.dict("os.environ", {"HEARTHSTATE_CRON_SECRET": "cron-secret", "SUPABASE_SERVICE_ROLE_KEY": "service-key"}, clear=False), \
             patch("api.index._supabase_admin_request", side_effect=[[malformed], [{"household_id": "household-id", "user_id": "viewer-id"}], []]):
            request._handle_post("/notifications/dispatch")

        self.assertEqual(request._respond.call_args.args[0]["prepared"], 0)
        self.assertEqual(request._respond.call_args.args[0]["claimed"], 0)

    def test_rewritten_vercel_route_is_normalized(self):
        request = object.__new__(handler)
        request.path = "/api/index.py?route=/dashboard"
        self.assertEqual(request._route(), "/dashboard")

    def test_api_prefix_is_removed_from_direct_function_routes(self):
        request = object.__new__(handler)
        request.path = "/api/index.py?route=/api/dashboard"
        self.assertEqual(request._route(), "/dashboard")

    def test_rewritten_api_route_is_marked_as_api_request(self):
        request = object.__new__(handler)
        request.path = "/api/index.py?route=/api/tasks"
        self.assertTrue(request._is_api_request())
        self.assertEqual(request._route(), "/tasks")

    def test_all_page_api_routes_preserve_the_api_marker(self):
        request = object.__new__(handler)
        for page in ("calendar", "tasks", "meals", "groceries", "recipes", "admin", "notifications"):
            request.path = f"/api/index.py?route=/api/{page}"
            with self.subTest(page=page):
                self.assertTrue(request._is_api_request())
                self.assertEqual(request._route(), f"/{page}")

    def test_rewritten_api_tasks_route_bypasses_html_asset_dispatch(self):
        request = object.__new__(handler)
        request.path = "/api/index.py?route=/api/tasks"
        request._handle_asset = Mock(return_value=True)
        request._authenticate = Mock(return_value=("user-id", "session-token", {"email": "person@example.com"}))
        request._context = Mock(return_value=("household-id", []))
        request._table = Mock(return_value=[])
        request._enrich_rows = Mock(return_value=[])
        request._household_members = Mock(return_value=[])
        request._respond = Mock()

        request._handle_get(request._route())

        request._handle_asset.assert_not_called()
        request._respond.assert_called_once()
        self.assertEqual(request._respond.call_args.args[0]["tasks"], [])

    def test_calendar_and_tasks_return_configured_members_and_filter_by_member_id(self):
        request = object.__new__(handler)
        member_id = "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48"
        members = [{"id": member_id, "display_name": "Configured member", "role": "member"}]
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", {}))
        request._household_members = Mock(return_value=members)
        request._calendar_items = Mock(return_value=[
            {"id": "matching-event", "assignee": member_id},
            {"id": "other-event", "assignee": "other-member"},
        ])
        request._table = Mock(return_value=[
            {"id": "matching-task", "assignee": member_id},
            {"id": "other-task", "assignee": "other-member"},
        ])
        request._visible_tasks = Mock(side_effect=lambda rows, _user_id: rows)
        request._enrich_rows = Mock(side_effect=lambda rows, _token: rows)
        request._respond = Mock()

        request.path = f"/api/index.py?route=/api/calendar&assignee={member_id}"
        request._handle_get("/calendar")
        calendar_payload = request._respond.call_args.args[0]
        self.assertEqual(calendar_payload["members"], members)
        self.assertEqual([item["id"] for item in calendar_payload["calendar"]], ["matching-event"])

        request._respond.reset_mock()
        request.path = "/api/index.py?route=/api/tasks"
        request._handle_get("/tasks")
        tasks_payload = request._respond.call_args.args[0]
        self.assertEqual(tasks_payload["members"], members)
        self.assertEqual({item["id"] for item in tasks_payload["tasks"]}, {"matching-task", "other-task"})

        request.path = "/api/index.py?route=/api/tasks&assignee=foreign-member"
        with self.assertRaisesRegex(ValueError, "household member"):
            request._handle_get("/tasks")

    def test_notification_preferences_validate_authenticated_values_and_audit_update(self):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", {}))
        request._respond = Mock()
        request._log = Mock()
        with patch("api.index._json_body", return_value={
            "briefing_type": "morning",
            "enabled": False,
            "preferred_time": "06:30",
            "quiet_start": "21:00",
            "quiet_end": "07:00",
        }), patch("api.index._supabase_request", side_effect=[
            [{"household_id": "household-id", "user_id": "viewer-id", "briefing_type": "morning", "enabled": True}],
            [{"household_id": "household-id", "user_id": "viewer-id", "briefing_type": "morning", "enabled": False, "preferred_time": "06:30", "quiet_start": "21:00", "quiet_end": "07:00", "channel": "email"}],
            [],
        ]) as supabase_request:
            request._handle_post("/notifications/preferences")

        self.assertEqual(request._respond.call_args.args[0]["preferences"]["enabled"], False)
        self.assertEqual(supabase_request.call_count, 3)
        cancellation = supabase_request.call_args_list[-1]
        self.assertEqual(cancellation.args[1], "/rest/v1/rpc/cancel_notification_deliveries")
        self.assertEqual(cancellation.kwargs["payload"]["p_household_id"], "household-id")
        request._log.assert_called_once()
        self.assertEqual(request._log.call_args.args[:5], ("household-id", "viewer-id", "session-token", "notification_preferences_updated", "notification_preferences"))

    @patch("api.index._json_body", return_value={"briefing_type": "morning", "enabled": True, "preferred_time": "7:00", "quiet_start": "21:00", "quiet_end": "07:00"})
    @patch("api.index._supabase_request")
    def test_notification_preferences_reject_non_canonical_clock_values(self, supabase_request, _json_body):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", {}))
        with self.assertRaisesRegex(ValueError, "HH:MM"):
            request._handle_post("/notifications/preferences")
        supabase_request.assert_not_called()

    def test_notifications_page_redirects_to_administration(self):
        request = object.__new__(handler)
        request._token = Mock(return_value="session-token")
        request._redirect = Mock()
        self.assertTrue(request._handle_asset("/notifications"))
        request._redirect.assert_called_once_with("/admin#notificationSettings")

    def test_non_owner_can_load_administration_shell_without_owner_data(self):
        request = object.__new__(handler)
        request.path = "/api/index.py?route=/api/admin"
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", []))
        request._role = Mock(return_value="member")
        request._respond = Mock()

        request._handle_get("/admin")

        payload = request._respond.call_args.args[0]
        self.assertFalse(payload["is_owner"])
        self.assertEqual(payload["members"], [])
        self.assertEqual(payload["invitations"], [])

    def test_chores_snapshot_includes_members_and_next_rotating_assignee(self):
        request = object.__new__(handler)
        member_id = "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48"
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", {}))
        request._table = Mock(return_value=[{
            "id": "chore-id",
            "title": "Take out bins",
            "cadence": "weekly",
            "participants": [member_id],
            "next_index": 0,
            "next_due_at": "2026-08-10T07:00:00+00:00",
        }])
        request._household_members = Mock(return_value=[{"id": member_id, "display_name": "Billie", "role": "member"}])
        request._respond = Mock()
        request.path = "/api/index.py?route=/api/chores"

        request._handle_get("/chores")

        payload = request._respond.call_args.args[0]
        self.assertEqual(payload["members"][0]["display_name"], "Billie")
        self.assertEqual(payload["chores"][0]["next_assignee"], member_id)
        self.assertEqual(payload["chores"][0]["next_assignee_label"], "Billie")

    @patch("api.index._supabase_request", return_value=[{"id": "chore-id", "title": "Take out bins"}])
    @patch("api.index._json_body", return_value={
        "title": "Take out bins",
        "cadence": "weekly",
        "next_due_at": "2026-08-10T07:00",
        "participants": ["3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48"],
    })
    def test_chore_creation_validates_members_and_persists_schedule(self, _json_body, supabase_request):
        request = object.__new__(handler)
        member_id = "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48"
        request._authenticate = Mock(return_value=("owner-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", {}))
        request._household_members = Mock(return_value=[{"id": member_id, "display_name": "Billie", "role": "member"}])
        request._respond = Mock()

        request._handle_post("/chores")

        supabase_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/create_chore_template",
            token="session-token",
            payload={
                "p_household_id": "household-id",
                "p_actor_user_id": "owner-id",
                "p_title": "Take out bins",
                "p_cadence": "weekly",
                "p_participants": [member_id],
                "p_next_due_at": "2026-08-10T07:00:00+00:00",
            },
        )
        request._respond.assert_called_once_with({"chore": {"id": "chore-id", "title": "Take out bins"}}, status=201)

    @patch("api.index._json_body", return_value={
        "title": "Take out bins",
        "cadence": "weekly",
        "participants": ["3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf49"],
    })
    def test_chore_creation_rejects_a_participant_outside_the_household(self, _json_body):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("owner-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", {}))
        request._household_members = Mock(return_value=[{"id": "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48", "display_name": "Billie"}])
        request._post_record = Mock()
        request._respond = Mock()

        with self.assertRaisesRegex(ValueError, "household member"):
            request._handle_post("/chores")
        request._post_record.assert_not_called()

    @patch("api.index._supabase_request", side_effect=[
        {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "title": "Take out bins"},
        {
            "task": {"id": "task-id", "title": "Take out bins", "assignee": "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48"},
            "chore": {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "next_index": 1},
        },
    ])
    @patch("api.index._json_body", return_value={"due_date": "2026-08-10T07:00"})
    def test_assigning_next_chore_uses_schedule_aware_actor_bound_rpc(self, _json_body, supabase_request):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("owner-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", {}))
        request._respond = Mock()

        request._handle_post("/chores/2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47")

        self.assertEqual(supabase_request.call_args_list[1].args[:2], ("POST", "/rest/v1/rpc/create_chore_task"))
        self.assertEqual(supabase_request.call_args_list[1].kwargs["payload"], {
            "p_household_id": "household-id",
            "p_actor_user_id": "owner-id",
            "p_chore_id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "p_due_at": "2026-08-10T07:00:00+00:00",
        })
        self.assertEqual(request._respond.call_args.kwargs, {"status": 201})
        self.assertEqual(request._respond.call_args.args[0]["chore"]["next_index"], 1)
        self.assertEqual(supabase_request.call_count, 2)

    @patch("api.index._supabase_request", side_effect=[
        {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "title": "Take out bins"},
        {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "title": "Put out bins", "cadence": "fortnightly"},
    ])
    @patch("api.index._json_body", return_value={
        "title": "Put out bins",
        "cadence": "fortnightly",
        "participants": ["3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48"],
    })
    def test_editing_chore_uses_actor_bound_template_update_rpc(self, _json_body, supabase_request):
        request = object.__new__(handler)
        member_id = "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48"
        chore_id = "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47"
        request._authenticate = Mock(return_value=("owner-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", {}))
        request._household_members = Mock(return_value=[{"id": member_id, "display_name": "Billie"}])
        request._respond = Mock()

        request._handle_post(f"/chores/{chore_id}/edit")

        self.assertEqual(supabase_request.call_args_list[1].args[:2], ("POST", "/rest/v1/rpc/update_chore_template"))
        self.assertEqual(supabase_request.call_args_list[1].kwargs["payload"]["p_chore_id"], chore_id)
        self.assertEqual(supabase_request.call_args_list[1].kwargs["payload"]["p_participants"], [member_id])
        request._respond.assert_called_once_with({"chore": {"id": chore_id, "title": "Put out bins", "cadence": "fortnightly"}}, status=200)

    def test_browser_chores_page_and_asset_routes_use_html_asset_dispatch(self):
        for route in ("/chores", "/chores.js"):
            request = object.__new__(handler)
            request.path = f"/api/index.py?route={route}"
            request._handle_asset = Mock(return_value=True)

            request._handle_get(route)

            request._handle_asset.assert_called_once_with(route)

    def test_browser_tasks_route_still_uses_html_asset_dispatch(self):
        request = object.__new__(handler)
        request.path = "/api/index.py?route=/tasks"
        request._handle_asset = Mock(return_value=True)

        request._handle_get(request._route())

        request._handle_asset.assert_called_once_with("/tasks")

    def test_anonymous_setup_redirects_to_canonical_login(self):
        request = object.__new__(handler)
        request.headers = SimpleNamespace(get=lambda key, default="": default)
        request.send_response = Mock()
        request.send_header = Mock()
        request.end_headers = Mock()

        self.assertTrue(request._handle_asset("/setup"))

        request.send_response.assert_called_once_with(302)
        request.send_header.assert_any_call("Location", "/login")

    def test_vercel_api_rewrite_preserves_api_namespace(self):
        config = json.loads((Path(__file__).parents[1] / "vercel.json").read_text())
        rewrite = next(item for item in config["rewrites"] if item["source"] == "/api/:path*")
        self.assertIn("route=/api/:path*", rewrite["destination"])

    def test_pwa_manifest_and_service_worker_are_public_assets(self):
        request = object.__new__(handler)
        request._token = Mock(return_value=None)
        request._send_bytes = Mock()
        rewrites = json.loads((Path(__file__).parents[1] / "vercel.json").read_text())["rewrites"]
        rewrite_sources = {item["source"] for item in rewrites}
        self.assertTrue({"/manifest.webmanifest", "/sw.js", "/brand-mark.svg", "/icons/:path*"}.issubset(rewrite_sources))

        for route, content_type, marker in (
            ("/manifest.webmanifest", "application/manifest+json; charset=utf-8", '"display": "standalone"'),
            ("/sw.js", "text/javascript; charset=utf-8", "hearthstate-static-v"),
            ("/brand-mark.svg", "image/svg+xml", "Hearthstate"),
            ("/icons/icon-192.png", "image/png", None),
            ("/icons/icon-512.png", "image/png", None),
        ):
            with self.subTest(route=route):
                request._send_bytes.reset_mock()
                self.assertTrue(request._handle_asset(route))
                content, returned_type = request._send_bytes.call_args.args[:2]
                self.assertEqual(returned_type, content_type)
                if marker:
                    self.assertIn(marker.encode(), content)

    def test_setup_page_uses_cookie_backed_session_only(self):
        setup = (Path(__file__).parents[1] / "hearthstate" / "dashboard" / "hosted.html").read_text()
        self.assertNotIn("localStorage", setup)
        self.assertNotIn("Authorization", setup)
        self.assertIn("/api/me", setup)
        self.assertIn("/api/households", setup)

    def test_hosted_viewer_bootstrap_injects_owner_navigation_without_leaking_script_markup(self):
        html = '<head></head><body><!-- HEARTHSTATE_ADMIN_NAV --></body>'
        rendered = _inject_viewer_bootstrap(html.encode(), {"household_id": "household-id", "name": "Grant", "role": "Household admin", "is_owner": True})
        text = rendered.decode()
        self.assertIn('window.__HEARTHSTATE_VIEWER__', text)
        self.assertIn('"household_id":"household-id"', text)
        self.assertIn('"name":"Grant"', text)
        self.assertIn('id="administrationNav"', text)
        self.assertNotIn('HEARTHSTATE_ADMIN_NAV', text)

    def test_hosted_session_cookie_is_used_when_authorization_header_is_absent(self):
        request = object.__new__(handler)
        request.headers = SimpleNamespace(get=lambda key, default="": "HearthstateHostedSession=session-token" if key == "Cookie" else default)
        self.assertEqual(request._token(), "session-token")

    def test_setup_redirects_authenticated_member_to_dashboard(self):
        request = object.__new__(handler)
        request.headers = SimpleNamespace(get=lambda key, default="": "HearthstateHostedSession=session-token" if key == "Cookie" else default)
        request._authenticate = Mock(return_value=("user-id", "session-token", {}))
        request._memberships = Mock(return_value=[{"id": "household-id", "name": "Ashman Household"}])
        request.send_response = Mock()
        request.send_header = Mock()
        request.end_headers = Mock()
        self.assertTrue(request._handle_asset("/setup"))
        request.send_response.assert_called_once_with(302)
        request.send_header.assert_any_call("Location", "/")

    @patch("api.index._json_body", return_value={
        "id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
        "meal_date": "2026-08-08",
        "meal_type": "dinner",
        "title": "Tacos",
        "cook": "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48",
        "ingredients": ["tortillas"],
        "created_by": "attacker",
    })
    @patch("api.index._supabase_request", return_value={"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "title": "Tacos"})
    def test_meal_update_uses_membership_checked_rpc_and_server_bound_actor(self, supabase_request, _json_body):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("owner-id", "session-token", {"email": "owner@example.com"}))
        request._context = Mock(return_value=("household-id", []))
        request._respond = Mock()

        request._handle_post("/meals")

        supabase_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/update_meal",
            token="session-token",
            payload={
                "p_household_id": "household-id",
                "p_actor_user_id": "owner-id",
                "p_meal_id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
                "p_patch": {
                    "meal_date": "2026-08-08",
                    "meal_type": "dinner",
                    "title": "Tacos",
                    "cook": "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48",
                    "ingredients": ["tortillas"],
                },
            },
        )
        request._respond.assert_called_once_with({"meal": supabase_request.return_value}, status=200)

    @patch("api.index._supabase_request", return_value={"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "cook": None})
    def test_meal_update_can_clear_the_cook(self, supabase_request):
        request = object.__new__(handler)
        updated = request._update_meal(
            "household-id",
            "owner-id",
            "session-token",
            {
                "id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
                "cook": "",
            },
        )
        self.assertEqual(updated["cook"], None)
        self.assertEqual(supabase_request.call_args.kwargs["payload"]["p_patch"], {"cook": None})

    @patch("api.index._supabase_request")
    def test_meal_cook_display_label_resolves_to_household_member_uuid(self, supabase_request):
        cook_id = "8f8fad5b-d9cb-469f-a165-70867728951f"
        request = object.__new__(handler)

        def response(method, path, **kwargs):
            if path == "/rest/v1/memberships":
                return [{"user_id": cook_id}]
            if path == "/rest/v1/profiles":
                return {"user_id": cook_id, "display_name": "Grant", "email": "grant@example.test"}
            if path == "/rest/v1/rpc/create_meal":
                return {"id": "meal-3"}
            raise AssertionError(f"unexpected request: {method} {path}")

        supabase_request.side_effect = response
        request._create_meal(
            "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "0f8fad5b-d9cb-469f-a165-70867728950e",
            "session-token",
            {"meal_date": "2026-08-08", "title": "Dinner", "cook": "grant"},
        )
        rpc_call = next(call for call in supabase_request.call_args_list if call.args[1] == "/rest/v1/rpc/create_meal")
        self.assertEqual(rpc_call.kwargs["payload"]["p_meal"]["cook"], cook_id)

    @patch("api.index._supabase_request", return_value={"id": "meal-2", "title": "Recipe dinner"})
    def test_meal_creation_normalizes_recipe_ingredient_objects(self, supabase_request):
        request = object.__new__(handler)
        request._post_record(
            "meals",
            "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "0f8fad5b-d9cb-469f-a165-70867728950e",
            "session-token",
            {
                "meal_date": "2026-08-08",
                "title": "Recipe dinner",
                "ingredients": [{"quantity": "2", "unit": "cups", "name": "rice"}],
            },
        )
        self.assertEqual(
            supabase_request.call_args.kwargs["payload"]["p_meal"]["ingredients"],
            ["2 cups rice"],
        )

    @patch("api.index._supabase_request", return_value={"id": "4e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf49", "ingredients": []})
    @patch("api.index._json_body", return_value={"meal_id": "4e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf49"})
    def test_meal_grocery_sync_route_is_not_shadowed_by_delete_route(self, json_body, supabase_request):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=(
            "0f8fad5b-d9cb-469f-a165-70867728950e",
            "session-token",
            {},
        ))
        request._context = Mock(return_value=(
            "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            {},
        ))
        request._respond = Mock()
        request._handle_post("/meals/sync-groceries")
        request._respond.assert_called_once_with({"added": []})

    @patch("api.index._json_body", return_value={})
    def test_meal_delete_route_returns_rpc_result_without_extra_nesting(self, json_body):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=(
            "0f8fad5b-d9cb-469f-a165-70867728950e",
            "session-token",
            {},
        ))
        request._context = Mock(return_value=(
            "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            {},
        ))
        request._delete_meal = Mock(return_value={
            "deleted": True,
            "id": "4e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf49",
        })
        request._respond = Mock()
        request._handle_post(
            "/meals/4e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf49/delete"
        )
        request._respond.assert_called_once_with({
            "deleted": True,
            "id": "4e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf49",
        })

    @patch("api.index._supabase_request")
    @patch("api.index._supabase_admin_request")
    def test_activity_log_uses_trusted_server_channel(self, admin_request, user_request):
        request = object.__new__(handler)
        request._log(
            "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "0f8fad5b-d9cb-469f-a165-70867728950e",
            "session-token",
            "task.completed",
            "task",
            "4e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf49",
        )
        admin_request.assert_called_once()
        user_request.assert_not_called()

    @patch("api.index._supabase_request", return_value={"deleted": True, "id": "4e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf49"})
    def test_meal_delete_uses_membership_checked_rpc_and_server_bound_actor(self, supabase_request):
        request = object.__new__(handler)
        deleted = request._delete_meal(
            "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "0f8fad5b-d9cb-469f-a165-70867728950e",
            "session-token",
            "4e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf49",
        )
        self.assertTrue(deleted["deleted"])
        supabase_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/delete_meal",
            token="session-token",
            payload={
                "p_household_id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
                "p_actor_user_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
                "p_meal_id": "4e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf49",
            },
        )

    def test_meal_update_rejects_oversized_or_malformed_ingredients_before_network_call(self):
        request = object.__new__(handler)
        with self.assertRaisesRegex(ValueError, "ingredients"):
            request._update_meal(
                "household-id",
                "owner-id",
                "session-token",
                {
                    "id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
                    "ingredients": [""],
                },
            )

    def test_meal_mutation_migration_locks_membership_and_validates_cook_scope(self):
        migration = next((Path(__file__).parents[1] / "supabase" / "migrations").glob("*_auditable_meal_updates.sql")).read_text()
        self.assertIn("create or replace function public.create_meal", migration)
        self.assertIn("create or replace function public.delete_meal", migration)
        self.assertIn("meal.deleted", migration)
        self.assertIn("auth.uid() <> p_actor_user_id", migration)
        self.assertIn("from public.memberships", migration)
        self.assertIn("for update", migration)
        self.assertIn("order by user_id", migration.lower())
        self.assertIn("meal cook must belong to household", migration)
        self.assertIn("set search_path = public, pg_temp", migration)
        self.assertIn("meals_household_cook_membership_fkey", migration)
        self.assertIn("on delete set null (cook)", migration.lower())
        self.assertIn("insert into public.activity_log", migration)
        self.assertIn("meal patch must not be empty", migration)
        self.assertIn("revoke insert, update, delete on public.meals from authenticated", migration)
        self.assertIn("revoke insert, update, delete on public.activity_log from authenticated", migration)

    def test_meal_creation_is_database_constrained_to_household_cooks(self):
        migration = next((Path(__file__).parents[1] / "supabase" / "migrations").glob("*_auditable_meal_updates.sql")).read_text()
        self.assertIn("foreign key (household_id, cook)", migration.lower())
        self.assertIn("references public.memberships (household_id, user_id)", migration.lower())
        self.assertIn("on delete set null (cook)", migration.lower())

    def test_invalid_household_context_is_rejected(self):
        with self.assertRaises(ValueError):
            _uuid("not-a-uuid", "household id")

    def test_photon_sender_identity_is_normalized_to_e164(self):
        self.assertEqual(_normalize_channel_identity("+61 (400) 025-889"), "+61400025889")
        self.assertEqual(_normalize_channel_identity("00614000025889"), "+614000025889")

    def test_photon_bridge_token_is_hashed_and_short_tokens_are_rejected(self):
        self.assertEqual(len(_channel_token_hash("x" * 32)), 64)
        with self.assertRaises(Exception):
            _channel_token_hash("too-short")

    @patch.dict("os.environ", {"SUPABASE_SERVICE_ROLE_KEY": "service-role-test-key"})
    @patch("api.index._supabase_request")
    def test_admin_requests_send_service_role_as_bearer_and_api_key(self, supabase_request):
        _supabase_admin_request("GET", "/rest/v1/channel_integrations")
        self.assertEqual(supabase_request.call_args.kwargs["token"], "service-role-test-key")
        self.assertEqual(supabase_request.call_args.kwargs["api_key"], "service-role-test-key")

    def test_photon_bridge_contract_is_server_side_and_phone_bound(self):
        api = (Path(__file__).parents[1] / "api" / "index.py").read_text()
        migration = next((Path(__file__).parents[1] / "supabase" / "migrations").glob("*_photon_hosted_bridge.sql")).read_text()
        self.assertIn("/integrations/photon/state", api)
        self.assertIn("/integrations/photon/command", api)
        self.assertIn("X-Hearthstate-Photon-Key", api)
        self.assertIn("channel_identities", migration)
        self.assertIn("+61400025889", migration)
        self.assertIn("grant@ashman.net.au", migration)
        self.assertIn("service_role", migration)

    @patch("api.index.urlopen")
    @patch("api.index._config", return_value=("https://supabase.example", "publishable-key"))
    def test_supabase_request_honors_prefer_without_request_body(self, _config, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b"[]"
        _supabase_request("DELETE", "/rest/v1/memberships", token="session-token", prefer="return=representation")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Prefer"), "return=representation")

    def test_supabase_rows_accept_object_or_array(self):
        self.assertEqual(_rows({"id": "one"}), [{"id": "one"}])
        self.assertEqual(_rows([{"id": "one"}, "ignored"]), [{"id": "one"}])

    @patch("api.index._supabase_request")
    def test_meal_creation_uses_membership_checked_rpc_and_server_bound_actor(self, supabase_request):
        supabase_request.return_value = {"id": "meal-1", "title": "Tacos"}
        request = object.__new__(handler)
        created = request._post_record(
            "meals",
            "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "0f8fad5b-d9cb-469f-a165-70867728950e",
            "access-token",
            {
                "meal_date": "2026-08-08",
                "meal_type": "dinner",
                "title": "Tacos",
                "cook": "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48",
                "ingredients": ["tortillas"],
                "created_by": "attacker",
                "household_id": "other-household",
            },
        )
        self.assertEqual(created, {"id": "meal-1", "title": "Tacos"})
        supabase_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/create_meal",
            token="access-token",
            payload={
                "p_household_id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
                "p_actor_user_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
                "p_meal": {
                    "meal_date": "2026-08-08",
                    "meal_type": "dinner",
                    "title": "Tacos",
                    "cook": "3e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf48",
                    "ingredients": ["tortillas"],
                },
            },
        )

    @patch("api.index._supabase_request")
    def test_post_record_owns_household_and_actor_fields(self, supabase_request):
        supabase_request.return_value = [{"id": "capture-1"}]
        request = object.__new__(handler)
        created = request._post_record(
            "inbox_items",
            "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "0f8fad5b-d9cb-469f-a165-70867728950e",
            "access-token",
            {"original_text": "buy milk", "private": True, "created_by": "attacker", "household_id": "other"},
        )
        self.assertEqual(created, {"id": "capture-1"})
        call = supabase_request.call_args.kwargs
        self.assertEqual(call["payload"]["household_id"], "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47")
        self.assertEqual(call["payload"]["created_by"], "0f8fad5b-d9cb-469f-a165-70867728950e")
        self.assertNotEqual(call["payload"].get("created_by"), "attacker")
        self.assertNotEqual(call["payload"].get("household_id"), "other")

    @patch("api.index._json_body", return_value={})
    @patch("api.index._supabase_request")
    def test_owner_can_export_household_through_authenticated_rpc(self, supabase_request, _json_body):
        supabase_request.return_value = {"format_version": 1, "household": {"id": "household-id"}}
        request = object.__new__(handler)
        request.headers = {"X-Hearthstate-Household": "household-id"}
        request._authenticate = Mock(return_value=("owner-id", "session-token", {"email": "owner@example.com"}))
        request._context = Mock(return_value=("household-id", {}))
        request._role = Mock(return_value="owner")
        request._respond = Mock()

        request._handle_post("/admin/export")

        supabase_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/export_household",
            token="session-token",
            payload={"target_household_id": "household-id"},
        )
        request._respond.assert_called_once_with(supabase_request.return_value)

    @patch("api.index._json_body", return_value={"confirmation_name": "Ashman Home"})
    @patch("api.index._supabase_request", return_value=True)
    def test_owner_deletion_requires_current_name_and_calls_transactional_rpc(self, supabase_request, _json_body):
        request = object.__new__(handler)
        request.headers = {"X-Hearthstate-Household": "household-id"}
        request._authenticate = Mock(return_value=("owner-id", "session-token", {"email": "owner@example.com"}))
        request._context = Mock(return_value=("household-id", {}))
        request._role = Mock(return_value="owner")
        request._respond = Mock()

        request._handle_post("/admin/delete")

        supabase_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/delete_household",
            token="session-token",
            payload={"target_household_id": "household-id", "confirmation_name": "Ashman Home"},
        )
        request._respond.assert_called_once_with({"deleted": True})

    @patch("api.index._json_body", return_value={})
    @patch("api.index._supabase_request")
    def test_non_owner_cannot_export_or_delete_household(self, supabase_request, _json_body):
        request = object.__new__(handler)
        request.headers = {"X-Hearthstate-Household": "household-id"}
        request._authenticate = Mock(return_value=("member-id", "session-token", {"email": "member@example.com"}))
        request._context = Mock(return_value=("household-id", {}))
        request._role = Mock(return_value="member")
        request._respond = Mock()

        for route in ("/admin/export", "/admin/delete"):
            with self.subTest(route=route), self.assertRaisesRegex(Exception, "owner access required"):
                request._handle_post(route)
        supabase_request.assert_not_called()

    @patch("api.index._json_body", return_value={})
    def test_admin_export_requires_explicit_household_selection(self, _json_body):
        request = object.__new__(handler)
        request.headers = {}
        request._authenticate = Mock(return_value=("owner-id", "session-token", {"email": "owner@example.com"}))
        request._context = Mock()
        request._query = Mock(return_value={})

        with self.assertRaisesRegex(Exception, "explicit household selection required"):
            request._handle_post("/admin/export")
        request._context.assert_not_called()

    def test_admin_data_portability_controls_are_present(self):
        dashboard = Path(__file__).parents[1] / "hearthstate" / "dashboard"
        admin_html = (dashboard / "admin.html").read_text()
        admin_js = (dashboard / "admin.js").read_text()
        nav_js = (dashboard / "nav.js").read_text()
        self.assertIn('id="exportDataButton"', admin_html)
        self.assertIn('id="deleteHouseholdButton"', admin_html)
        self.assertIn("/api/admin/export", admin_js)
        self.assertIn("/api/admin/delete", admin_js)
        self.assertIn("confirmation_name", admin_js)
        self.assertIn("X-Hearthstate-Household", admin_js)
        self.assertIn("X-Hearthstate-Household", nav_js)

    def test_data_portability_migration_is_owner_bound_and_secret_safe(self):
        migrations = Path(__file__).parents[1] / "supabase" / "migrations"
        migration = (migrations / "20260803200000_hosted_data_portability.sql").read_text()
        self.assertIn("create or replace function public.export_household", migration)
        self.assertIn("create or replace function public.delete_household", migration)
        self.assertIn("role = 'owner'", migration)
        self.assertIn("grant execute on function public.export_household(uuid) to authenticated", migration)
        self.assertIn("grant execute on function public.delete_household(uuid, text) to authenticated", migration)
        export_section = migration.split("create or replace function public.export_household", 1)[1].split("revoke all on function public.export_household", 1)[0]
        self.assertNotIn("'token_hash'", export_section)
        self.assertNotIn("'bridge_key'", export_section)
        self.assertNotIn("channel_integrations", export_section)
    def test_private_tasks_are_visible_only_to_owner_or_creator_in_service_role_views(self):
        request = object.__new__(handler)
        viewer = "0f8fad5b-d9cb-469f-a165-70867728950e"
        tasks = [
            {"id": "private-owned", "private": True, "owner": viewer, "created_by": "other"},
            {"id": "private-created", "private": True, "owner": "other", "created_by": viewer},
            {"id": "private-hidden", "private": True, "owner": "other", "created_by": "someone-else"},
            {"id": "shared", "private": False, "owner": "other", "created_by": "someone-else"},
        ]
        self.assertEqual(
            [task["id"] for task in request._visible_tasks(tasks, viewer)],
            ["private-owned", "private-created", "shared"],
        )

    @patch("api.index._supabase_admin_request")
    def test_photon_private_task_completion_uses_actor_bound_rpc(self, admin_request):
        request = object.__new__(handler)
        admin_request.return_value = {"id": "task-id", "private": True, "status": "done"}
        completed = request._complete_task("household-id", "viewer-id", "task-id")
        self.assertEqual(completed["status"], "done")
        admin_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/complete_task",
            payload={
                "p_household_id": "household-id",
                "p_actor_user_id": "viewer-id",
                "p_task_id": "task-id",
            },
        )

    @patch("api.index._json_body", return_value={})
    def test_dashboard_task_completion_route_uses_session_bound_rpc(self, _json_body):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", {}))
        request._complete_task = Mock(return_value={"id": "task-id", "status": "done"})
        request._record_pilot_event = Mock()
        request._respond = Mock()
        request._handle_post("/tasks/2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47/complete")
        request._complete_task.assert_called_once_with(
            "household-id",
            "viewer-id",
            "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            "session-token",
        )

    def test_context_requires_explicit_household_for_multiple_memberships(self):
        request = object.__new__(handler)
        request.headers = {}
        request._query = Mock(return_value={})
        request._memberships = Mock(return_value=[{"id": "household-a"}, {"id": "household-b"}])
        with self.assertRaisesRegex(Exception, "explicit household selection"):
            request._context("viewer-id", "session-token")

    @patch("api.index._supabase_request", return_value=[{"household_id": "household-id", "user_id": "viewer-id", "role": "member"}])
    @patch("api.index._json_body", return_value={"token": "raw-invite", "display_name": "Grant"})
    def test_invitation_acceptance_uses_transactional_session_rpc(self, _json_body, supabase_request):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {"email": "person@example.test"}))
        request._respond = Mock()
        request._handle_post("/auth/invitations/accept")
        supabase_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/accept_invitation",
            token="session-token",
            payload={"raw_token": "raw-invite", "display_name": "Grant"},
        )
        request._respond.assert_called_once_with({"membership": {"household_id": "household-id", "user_id": "viewer-id", "role": "member"}}, status=201)

    @patch("api.index._json_body", return_value={})
    def test_photon_state_command_passes_body_sender(self, _json_body):
        request = object.__new__(handler)
        request._channel_integration = Mock(return_value={"id": "integration-id"})
        request._channel_context = Mock(return_value=({"household_id": "household-id"}, "viewer-id", "service-key", {}))
        request._photon_state = Mock(return_value={"channel": "photon"})
        self.assertEqual(request._photon_command({"action": "state", "sender": "+61400025889"}), {"channel": "photon"})
        request._photon_state.assert_called_once_with("+61400025889")

    @patch("api.index._json_body", return_value={})
    def test_photon_create_actions_use_actor_bound_rpcs(self, _json_body):
        request = object.__new__(handler)
        request._channel_integration = Mock(return_value={"id": "integration-id"})
        request._channel_context = Mock(return_value=({"household_id": "household-id"}, "viewer-id", "service-key", {}))
        request._photon_create_rpc = Mock(side_effect=lambda rpc, payload, label: {"id": rpc})
        for action, payload, rpc_name in (
            ("create_task", {"title": "Lock the door"}, "create_task"),
            ("add_grocery", {"name": "Rice"}, "create_grocery_item"),
            ("create_event", {"title": "Dinner", "starts_at": "2026-08-10T18:00:00Z"}, "create_event"),
        ):
            result = request._photon_command({"action": action, "sender": "sender-id", **payload})
            self.assertEqual(result["action"], action)
            self.assertEqual(request._photon_create_rpc.call_args.args[0], rpc_name)
        self.assertEqual(request._photon_create_rpc.call_count, 3)

    @patch("api.index._supabase_admin_request")
    def test_photon_binding_rejects_ambiguous_household_membership(self, admin_request):
        request = object.__new__(handler)
        request._channel_integration = Mock(return_value={"id": "integration-id", "allowed_email": "person@example.test"})
        admin_request.side_effect = [
            {"user_id": "viewer-id", "email": "person@example.test"},
            [{"household_id": "household-a", "role": "owner"}, {"household_id": "household-b", "role": "member"}],
        ]
        with self.assertRaisesRegex(Exception, "household_id is required"):
            request._bind_photon_identity({"email": "person@example.test", "sender": "+61400025889"})

    @patch("api.index._supabase_request")
    def test_household_member_options_use_profile_labels_and_stable_ids(self, supabase_request):
        member_id = "8f8fad5b-d9cb-469f-a165-70867728951f"
        request = object.__new__(handler)
        request._profile_map = Mock(return_value={member_id: {"display_name": "Grant"}})
        supabase_request.return_value = [{"user_id": member_id, "role": "member"}]
        self.assertEqual(
            request._household_members("household-id", "session-token"),
            [{"id": member_id, "role": "member", "display_name": "Grant"}],
        )

    @patch("api.index._supabase_request", return_value={"household_id": "household-id", "user_id": "member-id", "role": "member"})
    @patch("api.index._json_body", return_value={})
    def test_membership_admin_routes_use_transactional_rpc(self, _json_body, supabase_request):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("owner-id", "session-token", {"email": "owner@example.test"}))
        request._context = Mock(return_value=("household-id", []))
        request._role = Mock(return_value="owner")
        request._respond = Mock()
        request._handle_post("/admin/members/8f8fad5b-d9cb-469f-a165-70867728951f/remove")
        supabase_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/manage_membership",
            token="session-token",
            payload={
                "p_household_id": "household-id",
                "p_actor_user_id": "owner-id",
                "p_member_user_id": "8f8fad5b-d9cb-469f-a165-70867728951f",
                "p_action": "remove",
                "p_role": None,
            },
        )

    @patch("api.index._supabase_request", return_value={"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "status": "open"})
    @patch("api.index._json_body", return_value={})
    def test_task_delete_route_uses_actor_bound_rpc(self, _json_body, supabase_request):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {"email": "viewer@example.test"}))
        request._context = Mock(return_value=("household-id", []))
        request._respond = Mock()
        request._handle_post("/tasks/2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47/delete")
        supabase_request.assert_called_once_with(
            "POST",
            "/rest/v1/rpc/delete_task",
            token="session-token",
            payload={
                "p_household_id": "household-id",
                "p_actor_user_id": "viewer-id",
                "p_task_id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
            },
        )
        request._respond.assert_called_once_with(
            {
                "deleted": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47",
                "task": {"id": "2e3d9d4b-8bc1-4eb4-9f26-4c4f3f66bf47", "status": "open"},
            }
        )

        migration = next((Path(__file__).parents[1] / "supabase" / "migrations").glob("*_auditable_meal_updates.sql")).read_text().lower()
        self.assertIn("create policy memberships_delete_owner", migration)
        self.assertIn("user_id <> (select auth.uid())", migration)

    def test_task_completion_migration_is_actor_bound_and_atomic(self):
        migration = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260804120000_auditable_task_completion.sql").read_text().lower()
        self.assertIn("create or replace function public.complete_task", migration)
        self.assertIn("for update", migration)
        self.assertIn("task_row.private", migration)
        self.assertIn("task_row.status <> 'open'", migration)
        self.assertIn("status = 'open'", migration)
        self.assertIn("drop policy if exists tasks_member_update", migration)
        self.assertIn("status <> 'done'", migration)
        self.assertIn("update public.tasks", migration)
        self.assertIn("insert into public.activity_log", migration)
        self.assertIn("jsonb_build_object('id', p_task_id, 'status', 'done')", migration)
        self.assertIn("grant execute on function public.complete_task(uuid, uuid, uuid) to authenticated, service_role", migration)
        self.assertIn("grant execute on function public.accept_invitation(text, text) to authenticated", migration)
        self.assertIn("create or replace function public.create_task", migration)
        self.assertIn("create or replace function public.create_event", migration)
        self.assertIn("create or replace function public.create_grocery_item", migration)
        self.assertIn("create or replace function public.create_chore_task", migration)
        self.assertIn("chore participant must be a user id", migration)
        self.assertIn("drop policy if exists tasks_member_insert", migration)
        self.assertIn("delete from public.channel_identities", migration)
        inbox_migration = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260804100000_inbox_suggestions.sql").read_text().lower()
        archive_start = inbox_migration.index("create or replace function public.archive_inbox_capture")
        archive_sql = inbox_migration[archive_start:]
        self.assertIn("from public.memberships", archive_sql)
        self.assertIn("for update", archive_sql)


    def test_meal_dashboard_payload_contract_includes_household_members(self):
        request = object.__new__(handler)
        request._authenticate = Mock(return_value=("viewer-id", "session-token", {}))
        request._context = Mock(return_value=("household-id", {}))
        request._table = Mock(return_value=[])
        request._enrich_rows = Mock(return_value=[])
        request._household_members = Mock(return_value=[{"id": "member-id", "display_name": "Grant"}])
        request._respond = Mock()
        request.path = "/api/index.py?route=/api/meals"
        request._handle_get("/meals")
        self.assertEqual(request._respond.call_args.args[0]["members"], [{"id": "member-id", "display_name": "Grant"}])


if __name__ == "__main__":
    unittest.main()
