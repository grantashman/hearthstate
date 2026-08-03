from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from hearthstate.accounts import HouseholdDirectory
from hearthstate.dashboard import DashboardServer
from hearthstate.store import PlannerStore


class AdminHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.context = Path(self.tempdir.name)
        self.accounts = HouseholdDirectory(str(self.context / "accounts.db"))
        self.accounts.create_account("grant", "Grant Ashman", "grant@example.test")
        self.accounts.create_account("billie", "Billie Ashman", "billie@example.test")
        self.accounts.create_household("home", "Ashman Household", "grant")
        self.accounts.add_member("home", "billie", "member")
        self.store = PlannerStore(str(self.context / "planner.db"), household_id="home")
        self.server = DashboardServer(("127.0.0.1", 0), store=self.store, accounts=self.accounts)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.owner_cookie = f"HearthstateSession={self.server.create_session('grant', 'home')}"
        self.member_cookie = f"HearthstateSession={self.server.create_session('billie', 'home')}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.store.close()
        self.accounts.close()
        self.tempdir.cleanup()

    def request(self, method, path, payload=None, cookie=None):
        body = None if payload is None else json.dumps(payload).encode()
        request = Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Content-Type": "application/json",
                **({"Cookie": cookie} if cookie else {}),
            },
        )
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, response.headers, json.loads(response.read().decode())
        except HTTPError as error:
            return error.code, error.headers, json.loads(error.read().decode())

    def test_owner_can_read_settings_members_and_pending_invitations_without_token(self):
        invitation = self.accounts.create_invitation("home", "skye@example.test", "guest", "grant")

        status, _, payload = self.request("GET", "/api/admin", cookie=self.owner_cookie)

        self.assertEqual(status, 200)
        self.assertEqual(payload["household"], {"id": "home", "name": "Ashman Household"})
        self.assertEqual({member["id"] for member in payload["members"]}, {"grant", "billie"})
        self.assertEqual(payload["invitations"][0]["email"], "skye@example.test")
        self.assertEqual(payload["invitations"][0]["status"], "pending")
        self.assertNotIn("token", payload["invitations"][0])
        self.assertNotIn("token_hash", payload["invitations"][0])
        self.assertNotEqual(payload["invitations"][0]["id"], invitation["token"])

    def test_member_cannot_use_admin_read_or_mutations(self):
        self.assertEqual(self.request("GET", "/api/admin")[0], 401)
        self.assertEqual(self.request("GET", "/api/admin", cookie=self.member_cookie)[0], 403)
        self.assertEqual(self.request("POST", "/api/admin/household", {"name": "Nope"}, self.member_cookie)[0], 403)
        self.assertEqual(self.request("POST", "/api/admin/members/billie", {"role": "guest"}, self.member_cookie)[0], 403)
        self.assertEqual(self.request("POST", "/api/auth/invitations", {"email": "skye@example.test", "role": "member"}, self.member_cookie)[0], 400)

    def test_invitation_uses_the_session_household_for_multi_household_owner(self):
        self.accounts.create_household("other", "Other Household", "grant")
        other_store = PlannerStore(str(self.context / "other-planner.db"), household_id="other")
        other_server = DashboardServer(("127.0.0.1", 0), store=other_store, accounts=self.accounts)
        other_thread = threading.Thread(target=other_server.serve_forever, daemon=True)
        other_thread.start()
        try:
            cookie = f"HearthstateSession={other_server.create_session('grant', 'other')}"
            request = Request(
                f"http://127.0.0.1:{other_server.server_address[1]}/api/auth/invitations",
                data=json.dumps({"email": "skye@example.test", "role": "member"}).encode(),
                method="POST",
                headers={"Content-Type": "application/json", "Cookie": cookie},
            )
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode())
            self.assertEqual(payload["invitation"]["household_id"], "other")
        finally:
            other_server.shutdown()
            other_server.server_close()
            other_store.close()

        invitation = self.accounts.create_invitation("home", "skye@example.test", "guest", "grant")

        status, _, payload = self.request("POST", "/api/admin/household", {"name": "The Ashman Home"}, self.owner_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(payload["household"]["name"], "The Ashman Home")

        status, _, payload = self.request("POST", "/api/admin/members/billie", {"role": "child"}, self.owner_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(payload["member"]["role"], "child")
        self.assertEqual(self.accounts.role_for("billie", "home"), "child")

        status, _, payload = self.request("POST", f"/api/admin/invitations/{invitation['id']}/revoke", {}, self.owner_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(payload["invitation"]["status"], "revoked")
        with self.assertRaises(ValueError) as error:
            self.accounts.accept_invitation(invitation["token"], "Skye Ashman")
        self.assertIn("revoked", str(error.exception))

    def test_malformed_admin_payloads_are_client_errors(self):
        self.assertEqual(self.request("POST", "/api/admin/household", [], self.owner_cookie)[0], 400)
        huge_id = "9" * 100
        self.assertEqual(self.request("POST", f"/api/admin/invitations/{huge_id}/revoke", {}, self.owner_cookie)[0], 400)

        status, _, payload = self.request("POST", "/api/admin/members/grant", {"role": "member"}, self.owner_cookie)
        self.assertEqual(status, 400)
        self.assertIn("last owner", payload["error"])

        status, _, payload = self.request("POST", "/api/admin/members/grant/remove", {}, self.owner_cookie)
        self.assertEqual(status, 400)
        self.assertIn("last owner", payload["error"])

    def test_admin_page_requires_owner_and_is_served(self):
        request = Request(self.base_url + "/admin", headers={"Cookie": self.owner_cookie})
        with urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 200)
            page = response.read().decode()
        self.assertIn("Household administration", page)

        class RejectRedirects(HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                return None

        request = Request(self.base_url + "/admin", headers={"Cookie": self.member_cookie})
        with self.assertRaises(HTTPError) as error:
            build_opener(RejectRedirects).open(request, timeout=2)
        self.assertEqual(error.exception.code, 302)
        self.assertEqual(error.exception.headers["Location"], "/")


if __name__ == "__main__":
    unittest.main()
