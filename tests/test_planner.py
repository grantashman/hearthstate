import unittest
from datetime import datetime

from family_planner.app import FamilyPlanner
from family_planner.store import PlannerStore


class FamilyPlannerMessageTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")
        self.planner = FamilyPlanner(
            self.store,
            now=lambda: datetime(2026, 8, 2, 9, 0),
        )

    def tearDown(self):
        self.store.close()

    def test_adds_and_deduplicates_grocery_items(self):
        first = self.planner.handle_message("you", "Add oat milk and bananas to the grocery list")
        second = self.planner.handle_message("partner", "Put oat milk on the grocery list")

        self.assertEqual(first, "Added to groceries: oat milk, bananas.")
        self.assertEqual(second, "Already on groceries: oat milk.")
        self.assertEqual(
            [item["name"] for item in self.store.list_grocery_items()],
            ["oat milk", "bananas"],
        )

    def test_shopping_list_alias_adds_grocery_item(self):
        response = self.planner.handle_message("you", "Add Milk to the shopping list")

        self.assertEqual(response, "Added to groceries: milk.")
        self.assertEqual([item["name"] for item in self.store.list_grocery_items()], ["milk"])

    def test_event_accepts_compact_time_and_venue_in_title(self):
        response = self.planner.handle_message(
            "you", "Add Football @ Croudace Bay on Wednesday 7PM for Grant"
        )

        self.assertEqual(
            response,
            "Added: football @ croudace bay — Wednesday, August 5 at 7:00 PM — Grant.",
        )
        event = self.store.list_events()[0]
        self.assertEqual(event["title"], "football @ croudace bay")
        self.assertEqual(event["person"], "Grant")

    def test_private_reminder_belongs_to_sender(self):
        response = self.planner.handle_message(
            "you", "Remind me to submit the school form tomorrow"
        )

        self.assertEqual(response, "Reminder added for you: submit the school form — Monday, August 3 at 9:00 AM.")
        task = self.store.list_tasks()[0]
        self.assertEqual(task["owner"], "you")
        self.assertTrue(task["private"])

    def test_private_reminder_confirmation_never_echoes_sender_identifier(self):
        response = self.planner.handle_message(
            "+61400000001", "Remind me to call the dentist tomorrow"
        )

        self.assertTrue(response.startswith("Reminder added for you:"))
        self.assertNotIn("+61400000001", response)

    def test_shared_event_is_saved_with_person_and_time(self):
        response = self.planner.handle_message(
            "partner", "Add soccer Thursday at 5 for Alex"
        )

        self.assertEqual(response, "Added: soccer — Thursday, August 6 at 5:00 PM — Alex.")
        event = self.store.list_events()[0]
        self.assertEqual(event["title"], "soccer")
        self.assertEqual(event["person"], "Alex")
        self.assertEqual(event["starts_at"], "2026-08-06T17:00:00")

    def test_family_state_prioritizes_unassigned_and_due_items(self):
        self.planner.handle_message("you", "Add school permission form to the family tasks")
        self.planner.handle_message("partner", "Add call the plumber to the family tasks")

        response = self.planner.handle_message("you", "What needs attention?")

        self.assertIn("Needs attention:", response)
        self.assertIn("school permission form", response)
        self.assertIn("call the plumber", response)
        self.assertLess(response.index("school permission form"), response.index("call the plumber"))

    def test_family_state_does_not_expose_another_persons_private_reminder(self):
        self.planner.handle_message("you", "Remind me to renew my prescription tomorrow")

        response = self.planner.handle_message("partner", "What needs attention?")

        self.assertNotIn("renew my prescription", response)
        self.assertEqual(response, "Nothing urgent. The family is caught up.")

    def test_unknown_message_explains_supported_actions(self):
        response = self.planner.handle_message("you", "Tell me a joke")

        self.assertEqual(
            response,
            "I can add events, reminders, and groceries, or show what needs attention.",
        )


if __name__ == "__main__":
    unittest.main()
