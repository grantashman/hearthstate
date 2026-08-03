import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hearthstate.accounts import HouseholdDirectory
from hearthstate.dashboard import DashboardServer
from hearthstate.store import PlannerStore


class InvitationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory_context = tempfile.TemporaryDirectory()
        self.directory = HouseholdDirectory(str(Path(self.directory_context.name) / "accounts.db"))
        self.directory.create_account("grant", "Grant Ashman", "grant@example.test")
        self.directory.create_household("home", "Ashman Household", "grant")

    def tearDown(self):
        self.directory.close()
        self.directory_context.cleanup()

    def test_owner_invite_can_be_accepted_once_and_adds_member(self):
        invitation = self.directory.create_invitation(
            "home", "billie@example.test", "member", "grant",
            now=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
        )

        inspected = self.directory.inspect_invitation(invitation["token"])
        self.assertEqual(inspected["email"], "billie@example.test")
        self.assertEqual(inspected["role"], "member")

        accepted = self.directory.accept_invitation(
            invitation["token"], "Billie Ashman",
            now=datetime(2026, 8, 3, 9, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(accepted["household_id"], "home")
        self.assertEqual(accepted["role"], "member")
        self.assertEqual(self.directory.household_for(accepted["account_id"]), "home")
        with self.assertRaisesRegex(ValueError, "already used"):
            self.directory.accept_invitation(invitation["token"], "Billie Ashman")

    def test_expired_invitation_cannot_be_accepted(self):
        invitation = self.directory.create_invitation(
            "home", "billie@example.test", "member", "grant",
            now=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
            expires_in=timedelta(minutes=5),
        )
        with self.assertRaisesRegex(ValueError, "expired"):
            self.directory.inspect_invitation(
                invitation["token"],
                now=datetime(2026, 8, 1, 9, 6, tzinfo=timezone.utc),
            )

    def test_existing_member_can_request_and_consume_sign_in_token(self):
        self.directory.create_account("billie", "Billie Ashman", "billie@example.test")
        self.directory.add_member("home", "billie", "member")
        token = self.directory.create_sign_in_token(
            "billie@example.test",
            now=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
        )

        signed_in = self.directory.consume_sign_in_token(
            token["token"],
            now=datetime(2026, 8, 3, 9, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(signed_in["account_id"], "billie")
        self.assertEqual(signed_in["household_id"], "home")
        with self.assertRaisesRegex(ValueError, "already used"):
            self.directory.consume_sign_in_token(token["token"])

    def test_cross_instance_invitation_claim_is_single_use(self):
        second = HouseholdDirectory(self.directory.database_path)
        invitation = self.directory.create_invitation(
            "home", "billie@example.test", "member", "grant",
            now=datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc),
        )
        barrier = threading.Barrier(2)
        results = []

        def accept(directory):
            try:
                barrier.wait(timeout=2)
                results.append(directory.accept_invitation(invitation["token"], "Billie Ashman"))
            except Exception as exc:  # noqa: BLE001 - capture the losing claim
                results.append(exc)

        threads = [threading.Thread(target=accept, args=(directory,)) for directory in (self.directory, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        second.close()

        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 1)
        members = self.directory.list_members("home")
        self.assertEqual(sum(member["email"] == "billie@example.test" for member in members), 1)

    def test_cross_instance_sign_in_claim_is_single_use(self):
        second = HouseholdDirectory(self.directory.database_path)
        self.directory.create_account("billie", "Billie Ashman", "billie@example.test")
        self.directory.add_member("home", "billie", "member")
        token = self.directory.create_sign_in_token("billie@example.test")
        barrier = threading.Barrier(2)
        results = []

        def consume(directory):
            try:
                barrier.wait(timeout=2)
                results.append(directory.consume_sign_in_token(token["token"]))
            except Exception as exc:  # noqa: BLE001 - capture the losing claim
                results.append(exc)

        threads = [threading.Thread(target=consume, args=(directory,)) for directory in (self.directory, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        second.close()

        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 1)

    def test_sign_in_token_requires_explicit_household_when_account_has_multiple_memberships(self):
        self.directory.create_account("other-owner", "Other Owner", "other@example.test")
        self.directory.create_household("other", "Other Household", "other-owner")
        self.directory.create_account("billie", "Billie Ashman", "billie@example.test")
        self.directory.add_member("home", "billie", "member")
        self.directory.add_member("other", "billie", "member")

        with self.assertRaisesRegex(ValueError, "household selection required"):
            self.directory.create_sign_in_token("billie@example.test")
        token = self.directory.create_sign_in_token("billie@example.test", household_id="other")
        self.assertEqual(self.directory.inspect_sign_in_token(token["token"])["household_id"], "other")

    def test_sign_in_claim_rejects_expired_token_at_the_claim_boundary(self):
        self.directory.create_account("billie", "Billie Ashman", "billie@example.test")
        self.directory.add_member("home", "billie", "member")
        created = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
        token = self.directory.create_sign_in_token(
            "billie@example.test", now=created, expires_in=timedelta(minutes=5),
        )
        with self.assertRaisesRegex(ValueError, "expired"):
            self.directory.consume_sign_in_token(
                token["token"], now=created + timedelta(minutes=5),
            )


class InvitationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.context = tempfile.TemporaryDirectory()
        self.accounts = HouseholdDirectory(str(Path(self.context.name) / "accounts.db"))
        self.accounts.create_account("grant", "Grant Ashman", "grant@example.test")
        self.accounts.create_household("home", "Ashman Household", "grant")
        self.store = PlannerStore(str(Path(self.context.name) / "planner.db"), household_id="home")
        self.server = DashboardServer(("127.0.0.1", 0), store=self.store, accounts=self.accounts)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.store.close()
        self.accounts.close()
        self.thread.join(timeout=2)
        self.context.cleanup()

    def post(self, path, payload, cookie=None):
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return response.status, response.headers, json.loads(response.read().decode())

    def test_authenticated_owner_can_create_invitation_and_invitee_can_sign_in(self):
        login_token = self.accounts.create_sign_in_token("grant@example.test", now=self.server.now())["token"]
        _, login_headers, login_payload = self.post("/api/auth/sign-in", {"token": login_token})
        owner_cookie = login_headers["Set-Cookie"]
        self.assertEqual(login_payload["session"]["household_id"], "home")
        delivered_invitations = []
        self.server.invitation_delivery = delivered_invitations.append

        status, _, invitation_payload = self.post(
            "/api/auth/invitations",
            {"email": "billie@example.test", "role": "member"},
            owner_cookie,
        )
        self.assertEqual(status, 201)
        token = invitation_payload["invitation"]["token"]
        self.assertEqual(delivered_invitations[0]["email"], "billie@example.test")
        self.assertIn("/invite?token=", delivered_invitations[0]["url"])
        self.assertIn("/invite?token=", invitation_payload["invitation"]["url"])

        status, accept_headers, accepted_payload = self.post(
            "/api/auth/invitations/accept",
            {"token": token, "display_name": "Billie Ashman"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(accepted_payload["session"]["role"], "member")
        member_cookie = accept_headers["Set-Cookie"]

        status, _, snapshot_text = self.get("/api/dashboard", member_cookie)
        self.assertEqual(status, 200)
        snapshot = json.loads(snapshot_text)
        self.assertEqual(snapshot["viewer"], accepted_payload["session"]["user"])

    def test_cross_household_tokens_are_rejected_before_state_changes(self):
        self.accounts.create_household("other", "Other Household", "grant")
        other_store = PlannerStore(str(Path(self.context.name) / "planner.db"), household_id="other")
        other_server = DashboardServer(("127.0.0.1", 0), store=other_store, accounts=self.accounts)
        other_thread = threading.Thread(target=other_server.serve_forever, daemon=True)
        other_thread.start()
        other_base = f"http://127.0.0.1:{other_server.server_address[1]}"

        def post_other(path, payload):
            request = Request(
                other_base + path,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            return urlopen(request, timeout=2)

        try:
            invitation = self.accounts.create_invitation("home", "billie@example.test", "member", "grant", now=self.server.now())
            with self.assertRaises(HTTPError) as invitation_error:
                post_other("/api/auth/invitations/accept", {"token": invitation["token"], "display_name": "Billie"})
            self.assertEqual(invitation_error.exception.code, 400)
            self.assertFalse(any(member["email"] == "billie@example.test" for member in self.accounts.list_members("home")))

            self.accounts.create_account("billie", "Billie", "billie@example.test")
            self.accounts.add_member("home", "billie", "member")
            sign_in = self.accounts.create_sign_in_token("billie@example.test", now=self.server.now())
            with self.assertRaises(HTTPError) as sign_in_error:
                post_other("/api/auth/sign-in", {"token": sign_in["token"]})
            self.assertEqual(sign_in_error.exception.code, 400)
            self.assertEqual(self.accounts.consume_sign_in_token(sign_in["token"], now=self.server.now())["account_id"], "billie")
        finally:
            other_server.shutdown()
            other_server.server_close()
            other_store.close()
            other_thread.join(timeout=2)

    def test_account_backed_server_rejects_anonymous_api_access(self):
        with self.assertRaises(HTTPError) as get_error:
            self.get("/api/dashboard")
        self.assertEqual(get_error.exception.code, 401)
        with self.assertRaises(HTTPError) as post_error:
            self.post("/api/inbox", {"original_text": "anonymous"})
        self.assertEqual(post_error.exception.code, 401)

        with self.assertRaises(HTTPError) as context:
            self.post("/api/session", {"user": "grant"})
        self.assertEqual(context.exception.code, 400)

    def test_account_backed_server_rejects_non_member_session(self):
        self.accounts.create_account("outsider", "Outside User", "outsider@example.test")
        cookie = f"HearthstateSession={self.server.create_session('outsider')}"
        with self.assertRaises(HTTPError) as error:
            self.get("/api/dashboard", cookie)
        self.assertEqual(error.exception.code, 401)

    def test_invitation_page_and_sign_in_request_are_available(self):
        invitation = self.accounts.create_invitation("home", "billie@example.test", "member", "grant", now=self.server.now())
        status, _, page = self.get("/invite?token=" + invitation["token"])
        self.assertEqual(status, 200)
        self.assertIn("Join your household", page)
        status, _, inspected_text = self.get("/api/auth/invitations/inspect?token=" + invitation["token"])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(inspected_text)["invitation"]["household_name"], "Ashman Household")

        status, _, payload = self.post(
            "/api/auth/sign-in/request",
            {"email": "unknown@example.test"},
        )
        self.assertEqual(status, 202)
        self.assertEqual(payload, {"sent": True})

    def test_account_backed_login_exposes_magic_link_delivery_boundary(self):
        self.accounts.create_account("billie", "Billie Ashman", "billie@example.test")
        self.accounts.add_member("home", "billie", "member")
        delivered = []
        self.server.sign_in_delivery = delivered.append

        status, _, payload = self.post(
            "/api/auth/sign-in/request",
            {"email": "billie@example.test"},
        )
        self.assertEqual(status, 202)
        self.assertEqual(payload, {"sent": True})
        self.assertEqual(delivered[0]["email"], "billie@example.test")
        self.assertIn("/login?token=", delivered[0]["url"])

        status, _, config_text = self.get("/api/auth/config")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(config_text), {"account_backed": True})

    def get(self, path, cookie=None):
        headers = {"Cookie": cookie} if cookie else {}
        with urlopen(Request(self.base_url + path, headers=headers), timeout=2) as response:
            return response.status, response.headers, response.read().decode()


if __name__ == "__main__":
    unittest.main()
