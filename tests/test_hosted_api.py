import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from api.index import _inject_viewer_bootstrap, _rows, _uuid, handler


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
        rendered = _inject_viewer_bootstrap(html.encode(), {"name": "Grant", "role": "Household admin", "is_owner": True})
        text = rendered.decode()
        self.assertIn('window.__HEARTHSTATE_VIEWER__', text)
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


if __name__ == "__main__":
    unittest.main()
