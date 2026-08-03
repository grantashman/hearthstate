import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api.index import _rows, _uuid, handler


class HostedApiContractTests(unittest.TestCase):
    def test_rewritten_vercel_route_is_normalized(self):
        request = object.__new__(handler)
        request.path = "/api/index.py?route=/dashboard"
        self.assertEqual(request._route(), "/dashboard")

    def test_api_prefix_is_removed_from_direct_function_routes(self):
        request = object.__new__(handler)
        request.path = "/api/index.py?route=/api/dashboard"
        self.assertEqual(request._route(), "/dashboard")

    def test_hosted_session_cookie_is_used_when_authorization_header_is_absent(self):
        request = object.__new__(handler)
        request.headers = SimpleNamespace(get=lambda key, default="": "HearthstateHostedSession=session-token" if key == "Cookie" else default)
        self.assertEqual(request._token(), "session-token")

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
