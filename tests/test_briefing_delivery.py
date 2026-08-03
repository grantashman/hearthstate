from __future__ import annotations

import threading
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from hearthstate.briefing_delivery import deliver_briefing
from hearthstate.store import PlannerStore


class BriefingDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_notification_preferences_default_and_update(self):
        defaults = self.store.get_notification_preferences("grant")
        self.assertEqual(defaults["enabled"], True)
        self.assertEqual(defaults["preferred_time"], "07:30")
        self.assertEqual(defaults["quiet_start"], "21:00")
        self.assertEqual(defaults["quiet_end"], "07:00")
        self.assertEqual(defaults["channel"], "email")

        updated = self.store.set_notification_preferences(
            "grant",
            enabled=False,
            preferred_time="08:15",
            quiet_start="20:30",
            quiet_end="07:15",
            channel="email",
            updated_by="grant",
        )
        self.assertEqual(updated["enabled"], False)
        self.assertEqual(updated["preferred_time"], "08:15")
        self.assertEqual(updated["quiet_start"], "20:30")
        self.assertEqual(updated["quiet_end"], "07:15")

    def test_delivery_waits_for_preference_time_and_sends_once(self):
        self.store.add_task("school form", "2026-08-03T09:00:00", None, False, "grant")
        sent = []

        def transport(message):
            sent.append(message)
            return {"message_id": "msg-123"}

        before_time = deliver_briefing(
            self.store,
            "grant",
            "grant@example.test",
            transport,
            now=datetime(2026, 8, 3, 7, 29),
        )
        self.assertEqual(before_time["status"], "skipped")
        self.assertEqual(before_time["reason"], "before_preferred_time")
        self.assertEqual(sent, [])

        delivered = deliver_briefing(
            self.store,
            "grant",
            "grant@example.test",
            transport,
            now=datetime(2026, 8, 3, 7, 30),
        )
        self.assertEqual(delivered["status"], "sent")
        self.assertEqual(delivered["provider_message_id"], "msg-123")
        self.assertEqual(len(sent), 1)
        self.assertIn("school form", sent[0]["text"])
        self.assertEqual(self.store.get_briefing_delivery("grant", "morning", "2026-08-03")["status"], "sent")

        duplicate = deliver_briefing(
            self.store,
            "grant",
            "grant@example.test",
            transport,
            now=datetime(2026, 8, 3, 7, 31),
        )
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertEqual(len(sent), 1)

    def test_disabled_preference_does_not_create_delivery_record(self):
        self.store.set_notification_preferences("grant", enabled=False, updated_by="grant")
        result = deliver_briefing(
            self.store,
            "grant",
            "grant@example.test",
            lambda message: {"message_id": "unused"},
            now=datetime(2026, 8, 3, 7, 30),
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "disabled")
        self.assertIsNone(self.store.get_briefing_delivery("grant", "morning", "2026-08-03"))

    def test_failed_delivery_is_retryable_without_duplicate_concurrent_sends(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "planner.db")
            first_store = PlannerStore(database)
            second_store = PlannerStore(database)
            first_store.add_task("school form", "2026-08-03T09:00:00", None, False, "grant")
            sent = []
            lock = threading.Lock()

            def transport(message):
                with lock:
                    sent.append(message)
                return {"message_id": "msg-concurrent"}

            results = []

            def run(store):
                results.append(
                    deliver_briefing(
                        store,
                        "grant",
                        "grant@example.test",
                        transport,
                        now=datetime(2026, 8, 3, 7, 30),
                    )
                )

            left = threading.Thread(target=run, args=(first_store,))
            right = threading.Thread(target=run, args=(second_store,))
            left.start()
            right.start()
            left.join(timeout=3)
            right.join(timeout=3)
            self.assertEqual(len(results), 2)
            self.assertEqual(sum(result["status"] == "sent" for result in results), 1)
            self.assertEqual(sum(result["status"] == "duplicate" for result in results), 1)
            self.assertEqual(len(sent), 1)

            first_store.close()
            second_store.close()

    def test_failed_provider_call_records_sanitized_failure_and_allows_retry(self):
        attempts = []

        def failing_transport(message):
            attempts.append(message)
            raise RuntimeError("provider leaked recipient grant@example.test")

        failed = deliver_briefing(
            self.store,
            "grant",
            "grant@example.test",
            failing_transport,
            now=datetime(2026, 8, 3, 7, 30),
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["attempt_count"], 1)
        record = self.store.get_briefing_delivery("grant", "morning", "2026-08-03")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["last_error"], "RuntimeError: briefing delivery provider failed")
        self.assertNotIn("grant@example.test", record["last_error"])

        retried = deliver_briefing(
            self.store,
            "grant",
            "grant@example.test",
            lambda message: {"message_id": "msg-retry"},
            now=datetime(2026, 8, 3, 7, 36),
        )
        self.assertEqual(retried["status"], "sent")
        self.assertEqual(retried["attempt_count"], 2)
        self.assertEqual(len(attempts), 1)

    def test_delivery_cli_uses_account_member_email_and_keeps_stdout_sanitized(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        import sys
        from hearthstate.accounts import HouseholdDirectory
        from hearthstate.briefing_delivery import main

        with tempfile.TemporaryDirectory() as directory:
            planner_database = Path(directory) / "planner.db"
            accounts_database = Path(directory) / "accounts.db"
            accounts = HouseholdDirectory(str(accounts_database))
            accounts.create_account("grant", "Grant", "grant@example.test")
            accounts.create_household("home", "Home", "grant")
            accounts.close()
            planner = PlannerStore(str(planner_database), household_id="home")
            planner.add_task("school form", "2026-08-03T09:00:00", None, False, "grant")
            planner.close()
            output = StringIO()
            sent = []
            argv = [
                "briefing-delivery",
                "--database", str(planner_database),
                "--accounts-database", str(accounts_database),
                "--household-id", "home",
                "--viewer", "grant",
                "--agentmail",
            ]
            with patch.object(sys, "argv", argv), \
                    patch("hearthstate.briefings.local_now", return_value=datetime(2026, 8, 3, 7, 30)), \
                    patch("hearthstate.briefing_delivery.local_now", return_value=datetime(2026, 8, 3, 7, 30), create=True), \
                    patch("hearthstate.agentmail.send_briefing_email", side_effect=lambda message: sent.append(message) or {"message_id": "msg-cli"}), \
                    redirect_stdout(output):
                main()

            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0]["to"], "grant@example.test")
            self.assertIn("school form", sent[0]["text"])
            self.assertIn('"status": "sent"', output.getvalue())
            self.assertNotIn("school form", output.getvalue())

    def test_custom_quiet_window_controls_delivery_boundary(self):
        self.store.set_notification_preferences(
            "grant",
            preferred_time="05:30",
            quiet_start="22:00",
            quiet_end="06:00",
            updated_by="grant",
        )
        self.store.add_task("early school run", "2026-08-03T07:00:00", None, False, "grant")
        sent = []
        before_window = deliver_briefing(
            self.store,
            "grant",
            "grant@example.test",
            lambda message: sent.append(message) or {"message_id": "unused"},
            now=datetime(2026, 8, 3, 5, 59),
        )
        self.assertEqual(before_window["status"], "skipped")
        self.assertEqual(before_window["reason"], "quiet_hours")
        delivered = deliver_briefing(
            self.store,
            "grant",
            "grant@example.test",
            lambda message: sent.append(message) or {"message_id": "msg-custom"},
            now=datetime(2026, 8, 3, 6, 30),
        )
        self.assertEqual(delivered["status"], "sent")
        self.assertEqual(len(sent), 1)

    def test_private_task_is_not_in_briefing_delivery(self):
        self.store.add_task("Grant private appointment", "2026-08-03T09:00:00", "grant", True, "grant")
        self.store.add_task("Billie private appointment", "2026-08-03T09:00:00", "billie", True, "billie")
        messages = []
        deliver_briefing(
            self.store,
            "grant",
            "grant@example.test",
            lambda message: messages.append(message) or {"message_id": "msg-private"},
            now=datetime(2026, 8, 3, 7, 30),
        )
        self.assertIn("Grant private appointment", messages[0]["text"])
        self.assertNotIn("Billie private appointment", messages[0]["text"])


if __name__ == "__main__":
    unittest.main()
