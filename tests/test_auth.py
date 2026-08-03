import json
import threading
import unittest
from urllib.request import Request, urlopen

from hearthstate.dashboard import DashboardServer
from hearthstate.store import PlannerStore


class PasswordlessLoginHTTPTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")
        self.server = DashboardServer(("127.0.0.1", 0), store=self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.store.close()
        self.thread.join(timeout=2)

    def get(self, path, cookie=None):
        headers = {"Cookie": cookie} if cookie else {}
        with urlopen(Request(self.base_url + path, headers=headers), timeout=2) as response:
            return response.status, response.headers, response.read().decode()

    def login(self, user):
        request = Request(
            self.base_url + "/api/session",
            data=json.dumps({"user": user}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return response.headers["Set-Cookie"], json.loads(response.read().decode())

    def test_anonymous_overview_shows_passwordless_household_user_chooser(self):
        status, _, page = self.get("/")

        self.assertEqual(status, 200)
        self.assertIn("Who is home?", page)
        self.assertIn('data-user="grant"', page)
        self.assertIn('data-user="billie"', page)
        self.assertIn('data-user="skye"', page)
        self.assertIn("/user-images/grant.png", page)
        self.assertIn("/user-images/billie.png", page)
        self.assertIn("/user-images/skye.png", page)
        self.assertNotIn('id="greetingTitle"', page)

    def test_selecting_user_sets_session_and_personalizes_overview(self):
        cookie, session = self.login("billie")

        self.assertEqual(session, {"user": "billie", "name": "Billie"})
        self.assertIn("HearthstateSession=", cookie)

        status, _, page = self.get("/", cookie)
        self.assertEqual(status, 200)
        self.assertIn('id="greetingTitle"', page)
        self.assertNotIn("Who is home?", page)

        _, _, snapshot_text = self.get("/api/dashboard", cookie)
        snapshot = json.loads(snapshot_text)
        self.assertEqual(snapshot["viewer"], "billie")
        self.assertEqual(snapshot["viewer_name"], "Billie")

    def test_rejects_unknown_household_user(self):
        request = Request(
            self.base_url + "/api/session",
            data=json.dumps({"user": "unknown"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(Exception) as context:
            urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 400)

    def test_authenticated_mutations_use_selected_user_not_client_supplied_actor(self):
        cookie, _ = self.login("billie")
        request = Request(
            self.base_url + "/api/inbox",
            data=json.dumps({"original_text": "Billie note", "created_by": "grant"}).encode(),
            headers={"Content-Type": "application/json", "Cookie": cookie},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            item = json.loads(response.read().decode())["item"]
        self.assertEqual(item["created_by"], "billie")


if __name__ == "__main__":
    unittest.main()
