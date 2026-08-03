import json
import unittest
from datetime import datetime

from hearthstate.app import Hearthstate
from hearthstate.dashboard import build_dashboard_snapshot
from hearthstate.store import PlannerStore


class ActivityHistoryTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_mutations_are_audited_and_last_change_can_be_undone(self):
        task_id = self.store.add_task("pack school bag", None, None, False, "grant", actor="grant")
        self.store.update_task(task_id, "pack school bag tonight", None, "skye", actor="billie")

        history = self.store.list_activity()
        self.assertEqual([item["action"] for item in history], ["task.updated", "task.created"])
        self.assertEqual(history[0]["actor"], "billie")
        self.assertEqual(history[0]["before"]["title"], "pack school bag")
        self.assertEqual(history[0]["after"]["title"], "pack school bag tonight")

        undone = self.store.undo_last("billie")
        self.assertEqual(undone["entity_type"], "task")
        task = next(item for item in self.store.list_tasks() if item["id"] == task_id)
        self.assertEqual(task["title"], "pack school bag")
        self.assertIsNone(task["assignee"])

        meal_id = self.store.add_meal("2026-08-03", "dinner", "Tacos", "grant", ["beans", "rice"], "grant", actor="grant")
        self.store.update_meal(meal_id, "2026-08-03", "dinner", "Curry", "grant", ["rice", "lentils"], actor="grant")
        self.store.undo_last("grant")
        restored_meal = self.store.list_meals()[0]
        self.assertEqual(restored_meal["title"], "Tacos")
        self.assertEqual(restored_meal["ingredients"], ["beans", "rice"])

    def test_delete_is_reversible_and_hidden_from_open_reads(self):
        task_id = self.store.add_task("delete me", None, None, False, "grant", actor="grant")
        self.store.delete_task(task_id, actor="grant")

        self.assertEqual(self.store.list_tasks(), [])
        history = self.store.list_activity()
        self.assertEqual(history[0]["action"], "task.archived")
        self.store.undo_last("grant")
        self.assertEqual(self.store.list_tasks()[0]["title"], "delete me")


class ConversationMutationTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")
        self.planner = Hearthstate(self.store, now=lambda: datetime(2026, 8, 2, 9, 0))

    def tearDown(self):
        self.store.close()

    def test_can_edit_tasks_and_events_and_read_activity(self):
        self.planner.handle_message("grant", "Add school form to the family tasks")
        self.assertIn("Renamed", self.planner.handle_message("grant", "Rename task school form to submit school form"))
        self.assertIn("submit school form", self.planner.handle_message("grant", "What changed?"))
        self.planner.handle_message("grant", "Add dentist Monday at 5 for Grant")
        moved = self.planner.handle_message("grant", "Move dentist to Tuesday at 4")
        self.assertIn("Moved", moved)
        self.assertEqual(self.store.list_events()[0]["starts_at"], "2026-08-04T16:00:00")

    def test_can_complete_remove_and_undo_from_messages(self):
        self.planner.handle_message("grant", "Add school form to the family tasks")
        self.assertIn("Completed", self.planner.handle_message("grant", "Mark school form done"))
        self.assertEqual(self.store.list_tasks(), [])
        self.assertIn("Restored", self.planner.handle_message("grant", "Undo that"))
        self.assertEqual(self.store.list_tasks()[0]["title"], "school form")

        self.planner.handle_message("grant", "Add oat milk to the grocery list")
        self.assertIn("Removed", self.planner.handle_message("grant", "Remove oat milk from groceries"))
        self.assertEqual(self.store.list_grocery_items(), [])


class BriefingTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_briefing_is_quiet_at_night_and_deduplicated(self):
        from hearthstate.briefings import build_briefing, claim_briefing

        self.store.add_task("school form", "2026-08-03T09:00:00", None, False, "grant")
        quiet = build_briefing(self.store, "grant", datetime(2026, 8, 2, 22, 0))
        self.assertIsNone(quiet)
        message = build_briefing(self.store, "grant", datetime(2026, 8, 3, 7, 30))
        self.assertIn("school form", message)
        self.assertTrue(claim_briefing(self.store, "grant", "morning", datetime(2026, 8, 3, 7, 30)))
        self.assertIsNone(build_briefing(self.store, "grant", datetime(2026, 8, 3, 8, 0)))

    def test_scheduler_runner_claims_before_emitting(self):
        from hearthstate.briefings import run_briefing

        self.store.add_task("school form", "2026-08-03T09:00:00", None, False, "grant")
        first = run_briefing(self.store, "grant", datetime(2026, 8, 3, 7, 30))
        second = run_briefing(self.store, "grant", datetime(2026, 8, 3, 7, 31))

        self.assertIn("school form", first)
        self.assertIsNone(second)
        self.assertTrue(self.store.briefing_claimed("grant", "morning", "2026-08-03"))

    def test_briefing_cli_uses_named_household_database(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        import sys
        import tempfile
        from pathlib import Path

        from hearthstate.briefings import main

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "hearthstate.db"
            named_store = PlannerStore(str(database), household_id="home")
            named_store.add_task("school form", "2026-08-03T09:00:00", None, False, "grant")
            named_store.close()
            output = StringIO()
            argv = ["briefings", "--database", str(database), "--household-id", "home"]
            with patch.object(sys, "argv", argv), patch("hearthstate.briefings.local_now", return_value=datetime(2026, 8, 3, 7, 30)), redirect_stdout(output):
                main()

        self.assertIn("school form", output.getvalue())


class ChoreRotationTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_round_robin_chore_assignment_advances_after_completion(self):
        chore_id = self.store.add_chore("rubbish duty", "weekly", ["grant", "billie"], "grant")
        first = self.store.assign_next_chore(chore_id, "2026-08-02", "grant")
        self.assertEqual(first["assignee"], "grant")
        self.store.complete_task(first["id"], actor="grant")
        second = self.store.assign_next_chore(chore_id, "2026-08-09", "grant")
        self.assertEqual(second["assignee"], "billie")


class ConflictTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_snapshot_reports_overlapping_events_and_task_deadline(self):
        self.store.add_event("dentist", "2026-08-03T17:00:00", "Grant", "grant", assignee="grant")
        self.store.add_event("soccer", "2026-08-03T17:30:00", "Skye", "grant", assignee="grant")
        self.store.add_task("leave for dentist", "2026-08-03T17:15:00", None, False, "grant", assignee="grant")

        snapshot = build_dashboard_snapshot(self.store, viewer="grant", now=datetime(2026, 8, 2, 8, 0))
        self.assertEqual(len(snapshot["conflicts"]), 2)
        self.assertTrue(any(item["kind"] == "event_overlap" for item in snapshot["conflicts"]))
        self.assertTrue(any(item["kind"] == "task_during_event" for item in snapshot["conflicts"]))

    def test_conflicts_can_be_queried_in_conversation(self):
        self.store.add_event("dentist", "2026-08-03T17:00:00", "Grant", "grant", assignee="grant")
        self.store.add_event("soccer", "2026-08-03T17:30:00", "Skye", "grant", assignee="grant")
        response = Hearthstate(self.store, now=lambda: datetime(2026, 8, 2, 8, 0)).handle_message("grant", "What conflicts are there?")
        self.assertIn("dentist", response)
        self.assertIn("soccer", response)


class IntelligenceHTTPTests(unittest.TestCase):
    def test_activity_conflict_chore_and_undo_endpoints(self):
        from hearthstate.dashboard import DashboardServer
        from urllib.request import Request, urlopen
        import threading

        server = DashboardServer(("127.0.0.1", 0), store=PlannerStore(":memory:"), now=lambda: datetime(2026, 8, 2, 8, 0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            chore_payload = json.dumps({"title": "rubbish duty", "cadence": "weekly", "participants": ["grant", "billie"]}).encode()
            with urlopen(Request(base + "/api/chores", data=chore_payload, method="POST", headers={"Content-Type": "application/json"})) as response:
                self.assertEqual(response.status, 201)
            with urlopen(base + "/api/chores") as response:
                self.assertEqual(len(json.loads(response.read())["chores"]), 1)
            with urlopen(base + "/api/activity?viewer=grant") as response:
                self.assertIn("activity", json.loads(response.read()))
            with urlopen(base + "/api/conflicts") as response:
                self.assertEqual(json.loads(response.read())["conflicts"], [])
        finally:
            server.shutdown()
            server.server_close()
            server.store.close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
