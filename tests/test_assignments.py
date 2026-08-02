import json
import threading
import unittest
from datetime import datetime
from urllib.request import urlopen

from family_planner.app import FamilyPlanner
from family_planner.dashboard import DashboardServer, build_dashboard_snapshot
from family_planner.store import PlannerStore


class AssignmentMessageTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")
        self.planner = FamilyPlanner(self.store, now=lambda: datetime(2026, 8, 2, 8, 0))

    def tearDown(self):
        self.store.close()

    def test_adds_task_assigned_to_named_household_member(self):
        response = self.planner.handle_message("+61400000001", "Add pack lunches to tasks for Skye")

        task = self.store.list_tasks()[0]
        self.assertIn("Skye", response)
        self.assertEqual(task["assignee"], "skye")
        self.assertFalse(task["private"])

    def test_adds_event_assigned_to_all(self):
        response = self.planner.handle_message(
            "+61400000001",
            "Add family dinner tomorrow at 6 pm for All",
        )

        event = self.store.list_events()[0]
        self.assertIn("All", response)
        self.assertEqual(event["assignee"], "all")

    def test_queries_tasks_by_assignee(self):
        self.planner.handle_message("+61400000001", "Add pack lunches to tasks for Skye")
        self.planner.handle_message("+61400000001", "Add buy milk to tasks for Grant")

        response = self.planner.handle_message("+61400000001", "What tasks are assigned to Skye?")

        self.assertIn("pack lunches", response)
        self.assertNotIn("buy milk", response)

    def test_queries_calendar_by_assignee(self):
        self.planner.handle_message("+61400000001", "Add family dinner tomorrow at 6 pm for All")

        response = self.planner.handle_message("+61400000001", "What is on the calendar for All?")

        self.assertIn("family dinner", response)
        self.assertIn("tomorrow", response.lower())


class AssignmentDashboardTests(unittest.TestCase):
    def test_snapshot_has_assignments_and_page_routes(self):
        store = PlannerStore(":memory:")
        store.add_task("pack lunches", "2026-08-02T09:00:00", "skye", False, "grant", assignee="skye")
        store.add_event("family dinner", "2026-08-03T18:00:00", None, "grant", assignee="all")
        snapshot = build_dashboard_snapshot(store, viewer="grant", now=datetime(2026, 8, 2, 8, 0))
        self.assertEqual(snapshot["tasks"][0]["assignee_label"], "Skye")
        self.assertEqual(next(item for item in snapshot["calendar"] if item["source_type"] == "event")["assignee_label"], "All")

        server = DashboardServer(("127.0.0.1", 0), store=store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            for path, marker in (("/calendar", "Calendar"), ("/tasks", "Tasks")):
                with urlopen(base_url + path, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(marker, response.read().decode())
            with urlopen(base_url + "/api/calendar", timeout=2) as response:
                self.assertEqual(response.status, 200)
                calendar = json.loads(response.read())["calendar"]
                self.assertEqual(next(item for item in calendar if item["source_type"] == "event")["assignee"], "all")
            with urlopen(base_url + "/api/tasks?assignee=skye", timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(len(json.loads(response.read())["tasks"]), 1)
            with urlopen(base_url + "/section.js", timeout=2) as response:
                self.assertEqual(response.status, 200)
                script = response.read().decode()
                self.assertIn("assigneeSelect", script)
                self.assertIn("hearthstate-theme", script)
                self.assertIn("source_type === 'event'", script)
            with urlopen(base_url + "/meals.js", timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("defaultMealDate", response.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            store.close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
