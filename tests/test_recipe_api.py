import json
import threading
import unittest
from datetime import datetime
from urllib.request import Request, urlopen

from family_planner.dashboard import DashboardServer
from family_planner.store import PlannerStore


class RecipeAPIHTTPTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")
        self.recipe_id = self.store.add_recipe(
            "user_supplied", "user_supplied", "Bean bowl", "https://example.test/bean-bowl",
            tags=["healthy", "quick", "protein"],
            ingredients=[{"name": "beans", "quantity": "1", "unit": "can"}],
        )
        self.server = DashboardServer(("127.0.0.1", 0), store=self.store, now=lambda: datetime(2026, 8, 2, 8, 0))
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

    def test_lists_filterable_recipes_and_saves_one(self):
        status, payload = self.request_json("/api/recipes?tag=healthy")
        self.assertEqual(status, 200)
        self.assertEqual(payload["recipes"][0]["title"], "Bean bowl")
        status, payload = self.request_json("/api/recipes?tag=protein")
        self.assertEqual(status, 200)
        self.assertEqual(payload["recipes"][0]["title"], "Bean bowl")

        status, payload = self.request_json(
            f"/api/recipes/{self.recipe_id}/save", {"saved_by": "grant", "saved": True}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["saved"])

    def test_imports_user_recipe_with_ingredients(self):
        status, payload = self.request_json(
            "/api/recipes/import",
            {
                "title": "Friday bean bowl",
                "source_url": "user://friday-bean-bowl",
                "image_url": "https://images.example.test/bean-bowl.jpg",
                "tags": ["quick", "healthy"],
                "ingredients": [{"name": "beans", "quantity": "1", "unit": "can"}],
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["recipe"]["source_policy"], "user_supplied")
        self.assertEqual(payload["recipe"]["image_url"], "https://images.example.test/bean-bowl.jpg")
        self.assertEqual(payload["recipe"]["ingredients"][0]["name"], "beans")

    def test_import_can_skip_owned_ingredients_and_add_missing_ones(self):
        status, payload = self.request_json(
            "/api/recipes/import",
            {
                "title": "Ownership test bowl",
                "source_url": "user://ownership-test-bowl",
                "created_by": "grant",
                "ingredients": [
                    {"name": "beans", "quantity": "1", "unit": "can"},
                    {"name": "carrots", "quantity": "2", "unit": ""},
                ],
                "grocery_ingredient_indexes": [1],
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["added"], ["2 carrots"])
        self.assertEqual([item["name"] for item in self.store.list_grocery_items()], ["2 carrots"])

        status, payload = self.request_json(
            f"/api/recipes/{self.recipe_id}/shopping-list", {"created_by": "grant"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["added"], ["1 can beans"])

    def test_planning_recipe_can_add_only_missing_ingredients(self):
        recipe_id = self.store.add_recipe(
            "user_supplied", "user_supplied", "Planned tofu bowl", "user://planned-tofu-bowl",
            ingredients=[
                {"name": "tofu", "quantity": "1", "unit": "block"},
                {"name": "carrots", "quantity": "2", "unit": ""},
            ],
        )
        status, payload = self.request_json(
            f"/api/recipes/{recipe_id}/plan",
            {
                "meal_date": "2026-08-08",
                "meal_type": "dinner",
                "cook": "billie",
                "created_by": "grant",
                "grocery_ingredient_indexes": [1],
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["meal"]["meal_date"], "2026-08-08")
        self.assertEqual(payload["meal"]["cook"], "billie")
        self.assertEqual(payload["added"], ["2 carrots"])
        self.assertEqual([item["name"] for item in self.store.list_grocery_items()], ["2 carrots"])

        status, payload = self.request_json(
            f"/api/recipes/{self.recipe_id}/plan",
            {"meal_date": "2026-08-04", "meal_type": "dinner", "cook": "grant", "created_by": "grant"},
        )
        self.assertEqual(status, 201)
        meal_id = payload["meal"]["id"]

        status, payload = self.request_json(
            f"/api/recipes/{self.recipe_id}/shopping-list",
            {"meal_id": meal_id, "created_by": "grant"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["added"], ["1 can beans"])


if __name__ == "__main__":
    unittest.main()
