import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from api.index import _channel_token_hash, _inject_viewer_bootstrap, _normalize_channel_identity, _rows, _supabase_admin_request, _uuid, handler


class HostedApiContractTests(unittest.TestCase):
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
        request._respond = Mock()

        request._handle_get(request._route())

        request._handle_asset.assert_not_called()
        request._respond.assert_called_once()
        self.assertEqual(request._respond.call_args.args[0]["tasks"], [])

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

    def test_supabase_rows_accept_object_or_array(self):
        self.assertEqual(_rows({"id": "one"}), [{"id": "one"}])
        self.assertEqual(_rows([{"id": "one"}, "ignored"]), [{"id": "one"}])

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


if __name__ == "__main__":
    unittest.main()
