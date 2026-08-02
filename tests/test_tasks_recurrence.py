import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from family_planner.dashboard import DashboardServer, build_dashboard_snapshot
from family_planner.store import PlannerStore


class TaskRecurrenceStoreTests(unittest.TestCase):
    def test_old_tasks_table_migrates_and_supports_optional_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "planner.sqlite3")
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, due_at TEXT, owner TEXT, assignee TEXT, private INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'open', created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.commit()
            connection.close()

            store = PlannerStore(database)
            try:
                task_id = store.add_task("undated task", None, None, False, "grant")
                task = store.list_tasks()[0]
                self.assertEqual(task["id"], task_id)
                self.assertEqual(task["recurrence"], "none")
                self.assertEqual(store.update_task(task_id, "renamed task", None, "skye")["title"], "renamed task")
            finally:
                store.close()

    def test_recurring_task_requires_date_and_updates_fields(self):
        store = PlannerStore(":memory:")
        try:
            with self.assertRaisesRegex(ValueError, "recurrence requires"):
                store.add_task("daily", None, None, False, "grant", recurrence="daily")
            task_id = store.add_task("weekly bins", "2026-08-02T08:00", None, False, "grant", recurrence="weekly")
            task = store.update_task(task_id, "weekly recycling", "2026-08-03T09:30", "billie", "fortnightly")
            self.assertEqual(task["title"], "weekly recycling")
            self.assertEqual(task["assignee"], "billie")
            self.assertEqual(task["recurrence"], "fortnightly")
        finally:
            store.close()


class TaskCalendarProjectionTests(unittest.TestCase):
    def test_dated_tasks_project_and_undated_tasks_do_not(self):
        store = PlannerStore(":memory:")
        try:
            store.add_task("undated", None, None, False, "grant")
            store.add_task("one-off", "2026-08-04T10:00", None, False, "grant")
            store.add_task("weekly chore", "2026-08-02T09:00", None, False, "grant", recurrence="weekly")
            snapshot = build_dashboard_snapshot(store, viewer="you", now=datetime(2026, 8, 2, 8, 0))
            task_items = [item for item in snapshot["calendar"] if item["source_type"] == "task"]
            self.assertTrue(any(item["title"] == "one-off" for item in task_items))
            self.assertTrue(any(item["title"] == "weekly chore" and item["recurrence"] == "weekly" for item in task_items))
            self.assertFalse(any(item["title"] == "undated" for item in task_items))
            self.assertGreaterEqual(sum(item["title"] == "weekly chore" for item in task_items), 52)
        finally:
            store.close()


class TaskDashboardHTTPTests(unittest.TestCase):
    def test_create_update_and_calendar_endpoint(self):
        store = PlannerStore(":memory:")
        server = DashboardServer(("127.0.0.1", 0), store=store, now=lambda: datetime(2026, 8, 2, 8, 0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            create = json.dumps({
                "title": "Take bins out",
                "due_at": "2026-08-02T09:00",
                "assignee": "skye",
                "recurrence": "weekly",
                "created_by": "grant",
            }).encode()
            with urlopen(Request(base + "/api/tasks", data=create, method="POST", headers={"Content-Type": "application/json"})) as response:
                self.assertEqual(response.status, 201)
                task = json.loads(response.read())["task"]
            self.assertEqual(task["recurrence"], "weekly")

            update = json.dumps({
                "id": task["id"],
                "title": "Take recycling out",
                "due_at": "2026-08-03T09:30",
                "assignee": "billie",
                "recurrence": "fortnightly",
            }).encode()
            with urlopen(Request(base + "/api/tasks", data=update, method="POST", headers={"Content-Type": "application/json"})) as response:
                self.assertEqual(response.status, 200)
                updated = json.loads(response.read())["task"]
            self.assertEqual(updated["title"], "Take recycling out")
            self.assertEqual(updated["recurrence"], "fortnightly")
            self.assertEqual(updated["assignee"], "billie")

            with urlopen(base + "/api/calendar") as response:
                calendar_items = json.loads(response.read())["calendar"]
            self.assertTrue(any(item["source_type"] == "task" and item["title"] == "Take recycling out" for item in calendar_items))

            complete_request = Request(base + f"/api/tasks/{task['id']}/complete", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
            with urlopen(complete_request) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["task"]["status"], "done")
            with urlopen(base + "/api/tasks") as response:
                self.assertFalse(any(item["id"] == task["id"] for item in json.loads(response.read())["tasks"]))
            with urlopen(base + "/api/calendar") as response:
                self.assertFalse(any(item.get("source_id") == task["id"] for item in json.loads(response.read())["calendar"]))

            delete_payload = json.dumps({"title": "Delete me", "created_by": "grant"}).encode()
            with urlopen(Request(base + "/api/tasks", data=delete_payload, method="POST", headers={"Content-Type": "application/json"})) as response:
                delete_id = json.loads(response.read())["task"]["id"]
            delete_request = Request(base + f"/api/tasks/{delete_id}/delete", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
            with urlopen(delete_request) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["deleted"], delete_id)
            self.assertIsNone(store.connection.execute("SELECT id FROM tasks WHERE id = ?", (delete_id,)).fetchone())
        finally:
            server.shutdown()
            server.server_close()
            store.close()


if __name__ == "__main__":
    unittest.main()
