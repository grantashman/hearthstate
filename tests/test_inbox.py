import json
import threading
import unittest
from datetime import datetime
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from family_planner.app import FamilyPlanner
from family_planner.dashboard import DashboardServer
from family_planner.store import PlannerStore


class InboxStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_rejects_blank_or_unbounded_inbox_actor_and_text(self):
        with self.assertRaisesRegex(ValueError, "created_by is required"):
            self.store.add_inbox_item("Something useful", "  ")
        with self.assertRaisesRegex(ValueError, "created_by is too long"):
            self.store.add_inbox_item("Something useful", "x" * 121)
        with self.assertRaisesRegex(ValueError, "original_text is too long"):
            self.store.add_inbox_item("x" * 4001, "you")

    def test_open_inbox_item_preserves_original_text_and_provenance(self):
        item_id = self.store.add_inbox_item(
            "Need to sort dentist and buy dishwasher tablets",
            "you",
            source="imessage",
        )

        items = self.store.list_inbox_items(viewer="you")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], item_id)
        self.assertEqual(items[0]["original_text"], "Need to sort dentist and buy dishwasher tablets")
        self.assertEqual(items[0]["source"], "imessage")
        self.assertEqual(items[0]["created_by"], "you")
        self.assertEqual(items[0]["status"], "open")

    def test_private_inbox_item_is_hidden_from_other_viewer(self):
        self.store.add_inbox_item("Call the doctor", "you", private=True)
        self.store.add_inbox_item("Buy light bulbs", "you", private=False)

        partner_items = self.store.list_inbox_items(viewer="partner")

        self.assertEqual([item["original_text"] for item in partner_items], ["Buy light bulbs"])

    def test_archiving_removes_item_from_open_inbox_but_keeps_history(self):
        item_id = self.store.add_inbox_item("Check the school calendar", "you")

        archived = self.store.archive_inbox_item(item_id)

        self.assertEqual(archived["status"], "archived")
        self.assertEqual(self.store.list_inbox_items(viewer="you"), [])
        history = self.store.get_inbox_item(item_id, viewer="you", include_closed=True)
        self.assertEqual(history["original_text"], "Check the school calendar")

    def test_converting_inbox_item_to_task_marks_it_resolved(self):
        item_id = self.store.add_inbox_item("Book the dentist", "you")

        task = self.store.convert_inbox_item(
            item_id,
            "task",
            {"title": "Book the dentist", "due_at": "2026-08-03T09:00:00"},
            created_by="you",
        )

        self.assertEqual(task["title"], "Book the dentist")
        resolved = self.store.get_inbox_item(item_id, viewer="you", include_closed=True)
        self.assertEqual(resolved["status"], "converted")
        self.assertEqual(resolved["converted_type"], "task")
        self.assertEqual(resolved["converted_id"], task["id"])
        self.assertEqual(self.store.list_inbox_items(viewer="you"), [])


class InboxPlannerTests(unittest.TestCase):
    def test_unknown_message_is_captured_for_later_triage(self):
        store = PlannerStore(":memory:")
        planner = FamilyPlanner(store, now=lambda: datetime(2026, 8, 2, 9, 0))

        response = planner.handle_message("you", "Need to sort dentist and buy dishwasher tablets")

        self.assertIn("Inbox", response)
        items = store.list_inbox_items(viewer="you")
        self.assertEqual(items[0]["original_text"], "Need to sort dentist and buy dishwasher tablets")
        store.close()
class InboxHTTPTests(unittest.TestCase):
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

    def request_json(self, path, payload=None):
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"} if payload is not None else {},
            method="POST" if payload is not None else "GET",
        )
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode())

    def request_error(self, path, payload):
        with self.assertRaises(HTTPError) as context:
            self.request_json(path, payload)
        error = context.exception
        return error.code, json.loads(error.read().decode())

    def test_inbox_api_lists_converts_and_archives_items(self):
        status, created = self.request_json(
            "/api/inbox",
            {"original_text": "Book the dentist", "source": "dashboard", "created_by": "you"},
        )
        self.assertEqual(status, 201)
        item_id = created["item"]["id"]

        status, listed = self.request_json("/api/inbox?viewer=you")
        self.assertEqual(status, 200)
        self.assertEqual(listed["items"][0]["original_text"], "Book the dentist")

        status, converted = self.request_json(
            f"/api/inbox/{item_id}/convert",
            {"type": "task", "title": "Book the dentist", "due_at": "2026-08-03T09:00:00", "created_by": "you"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(converted["task"]["title"], "Book the dentist")

        status, listed = self.request_json("/api/inbox?viewer=you")
        self.assertEqual(status, 200)
        self.assertEqual(listed["items"], [])

        _, created = self.request_json(
            "/api/inbox",
            {"original_text": "Archive this note", "source": "dashboard", "created_by": "you"},
        )
        status, archived = self.request_json(f"/api/inbox/{created['item']['id']}/archive", {})
        self.assertEqual(status, 200)
        self.assertEqual(archived["item"]["status"], "archived")

    def test_inbox_api_rejects_untrusted_or_invalid_mutation_payloads(self):
        status, payload = self.request_error("/api/inbox", {"original_text": "Note", "created_by": ""})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "created_by is required")

        status, payload = self.request_error("/api/inbox", {"original_text": "Note", "created_by": "you", "private": "false"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "private must be a boolean")

        _, created = self.request_json("/api/inbox", {"original_text": "Private note", "created_by": "you", "private": True})
        item_id = created["item"]["id"]
        status, payload = self.request_error(
            f"/api/inbox/{item_id}/archive",
            {"viewer": "partner"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "inbox item not found")

        status, payload = self.request_error(
            f"/api/inbox/{item_id}/convert",
            {"viewer": "you", "created_by": "you", "type": "unknown"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "unsupported inbox conversion")

        self.store.add_inbox_item("Private dentist note", "you", private=True)

        status, listed = self.request_json("/api/inbox?viewer=partner")

        self.assertEqual(status, 200)
        self.assertEqual(listed["items"], [])


if __name__ == "__main__":
    unittest.main()
