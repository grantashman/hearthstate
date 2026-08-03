import json
import threading
import unittest
from datetime import datetime
from urllib.request import Request, urlopen

from hearthstate.app import Hearthstate
from hearthstate.dashboard import DashboardServer, build_dashboard_snapshot
from hearthstate.store import PlannerStore


def login_cookie(base_url):
    request = Request(
        base_url + "/api/session",
        data=json.dumps({"user": "grant"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        return response.headers["Set-Cookie"]


class PlannerMutationTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")
        self.planner = Hearthstate(self.store, now=lambda: datetime(2026, 8, 2, 8, 0))

    def tearDown(self):
        self.store.close()

    def test_updates_calendar_entry_and_preserves_assignment(self):
        event_id = self.store.add_event(
            "soccer", "2026-08-03T17:00:00", "Skye", "grant", assignee="skye"
        )
        self.store.update_event(event_id, "soccer training", "2026-08-03T18:00:00", "Skye", "skye")

        event = self.store.list_events()[0]
        self.assertEqual(event["title"], "soccer training")
        self.assertEqual(event["starts_at"], "2026-08-03T18:00:00")
        self.assertEqual(event["assignee"], "skye")

    def test_adds_meal_with_ingredients_and_queries_it_by_message(self):
        response = self.planner.handle_message(
            "grant",
            "Add tacos to the meal plan tomorrow for Billie with ingredients tortillas, mince, lettuce",
        )

        self.assertIn("tacos", response.lower())
        meals = self.store.list_meals()
        self.assertEqual(meals[0]["cook"], "billie")
        self.assertEqual(meals[0]["ingredients"], ["tortillas", "mince", "lettuce"])

        query = self.planner.handle_message("grant", "What's for dinner tomorrow?")
        self.assertIn("tacos", query.lower())
        self.assertIn("billie", query.lower())

    def test_syncs_meal_ingredients_to_shared_groceries(self):
        meal_id = self.store.add_meal(
            "2026-08-03", "dinner", "tacos", "billie", ["tortillas", "mince"], "grant"
        )

        added = self.store.add_meal_ingredients_to_groceries(meal_id, "grant")

        self.assertEqual(added, ["tortillas", "mince"])
        self.assertEqual(
            [item["name"] for item in self.store.list_grocery_items()],
            ["tortillas", "mince"],
        )

    def test_updates_existing_meal_without_creating_duplicate(self):
        meal_id = self.store.add_meal(
            "2026-08-03", "dinner", "tacos", "billie", ["tortillas", "mince"], "grant"
        )

        updated = self.store.update_meal(
            meal_id, "2026-08-04", "lunch", "Taco bowls", "skye", ["rice", "beans"],
        )

        self.assertEqual(updated["id"], meal_id)
        self.assertEqual(updated["meal_date"], "2026-08-04")
        self.assertEqual(updated["meal_type"], "lunch")
        self.assertEqual(updated["title"], "Taco bowls")
        self.assertEqual(updated["cook"], "skye")
        self.assertEqual(updated["ingredients"], ["rice", "beans"])
        self.assertEqual(len(self.store.list_meals()), 1)

    def test_deletes_existing_meal_and_its_ingredients(self):
        meal_id = self.store.add_meal(
            "2026-08-03", "dinner", "tacos", "billie", ["tortillas", "mince"], "grant"
        )

        self.store.delete_meal(meal_id)

        self.assertEqual(self.store.list_meals(), [])
        self.assertIsNone(self.store.connection.execute(
            "SELECT id FROM meal_ingredients WHERE meal_id = ?", (meal_id,)
        ).fetchone())
        with self.assertRaises(ValueError):
            self.store.delete_meal(meal_id)


class PlannerMutationHTTPTests(unittest.TestCase):
    def test_post_actions_and_meal_page_are_available(self):
        store = PlannerStore(":memory:")
        event_id = store.add_event("soccer", "2026-08-03T17:00:00", "Skye", "grant", assignee="skye")
        server = DashboardServer(("127.0.0.1", 0), store=store, now=lambda: datetime(2026, 8, 2, 8, 0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            cookie = login_cookie(base)
            with urlopen(Request(base + "/meals", headers={"Cookie": cookie}), timeout=2) as response:
                self.assertEqual(response.status, 200)
                page = response.read().decode()
                self.assertIn("Meal planner", page)
                self.assertIn("mealId", page)
                self.assertIn("mealFormTitle", page)
            with urlopen(base + "/meals.js", timeout=2) as response:
                script = response.read().decode()
                self.assertIn("Edit meal", script)
                self.assertIn("deleteMeal", script)
                self.assertIn("window.confirm", script)

            payload = json.dumps({
                "id": event_id,
                "title": "soccer training",
                "starts_at": "2026-08-03T18:00:00",
                "person": "Skye",
                "assignee": "skye",
            }).encode()
            request = Request(base + "/api/calendar", data=payload, method="POST", headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["event"]["title"], "soccer training")

            payload = json.dumps({"title": "pack lunches", "assignee": "skye", "created_by": "grant"}).encode()
            request = Request(base + "/api/tasks", data=payload, method="POST", headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 201)
                self.assertEqual(json.loads(response.read())["task"]["assignee"], "skye")

            meal_id = store.add_meal("2026-08-04", "dinner", "tacos", "billie", ["tortillas"], "grant")
            payload = json.dumps({
                "id": meal_id,
                "meal_date": "2026-08-05",
                "meal_type": "lunch",
                "title": "Taco bowls",
                "cook": "skye",
                "ingredients": ["rice", "beans"],
                "created_by": "grant",
            }).encode()
            request = Request(base + "/api/meals", data=payload, method="POST", headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 200)
                updated = json.loads(response.read())["meal"]
                self.assertEqual(updated["id"], meal_id)
                self.assertEqual(updated["title"], "Taco bowls")
            self.assertEqual(len(store.list_meals()), 1)

            delete_request = Request(base + f"/api/meals/{meal_id}/delete", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
            with urlopen(delete_request, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["deleted"], meal_id)
            self.assertEqual(store.list_meals(), [])
        finally:
            server.shutdown()
            server.server_close()
            store.close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
