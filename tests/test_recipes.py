import unittest
from datetime import date

from family_planner.store import PlannerStore


class RecipeStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_adds_link_recipe_and_lists_filterable_metadata(self):
        recipe_id = self.store.add_recipe(
            source="coles",
            source_policy="link_only",
            title="Roasted veggies",
            source_url="https://www.coles.com.au/recipes-inspiration/recipes/roasted-veggies",
            tags=["healthy", "vegetarian", "simple"],
            cook_minutes=45,
        )

        recipes = self.store.list_recipes(tag="healthy")
        self.assertEqual(recipes[0]["id"], recipe_id)
        self.assertEqual(recipes[0]["source_policy"], "link_only")
        self.assertEqual(recipes[0]["ingredients"], [])
        self.assertEqual(recipes[0]["cook_minutes"], 45)

    def test_saves_recipe_for_household_member_and_can_unsave(self):
        recipe_id = self.store.add_recipe(
            "user_supplied", "user_supplied", "Bean bowl", "https://example.test/bean-bowl",
            tags=["healthy"], ingredients=[{"name": "beans", "quantity": "1", "unit": "can"}],
        )

        self.assertTrue(self.store.set_recipe_saved(recipe_id, "grant", True))
        self.assertEqual(len(self.store.list_recipes(saved_by="grant")), 1)
        self.assertTrue(self.store.set_recipe_saved(recipe_id, "grant", False))
        self.assertEqual(self.store.list_recipes(saved_by="grant"), [])

    def test_sends_saved_recipe_ingredients_directly_to_groceries(self):
        recipe_id = self.store.add_recipe(
            "user_supplied", "user_supplied", "Bean bowl", "https://example.test/direct-bean-bowl",
            ingredients=[{"name": "beans", "quantity": "1", "unit": "can"}],
        )

        self.assertEqual(self.store.add_recipe_ingredients_to_groceries(recipe_id, "grant"), ["1 can beans"])

    def test_plans_recipe_and_sends_imported_ingredients_to_groceries(self):
        recipe_id = self.store.add_recipe(
            "user_supplied", "user_supplied", "Bean bowl", "https://example.test/bean-bowl",
            ingredients=[
                {"name": "beans", "quantity": "1", "unit": "can"},
                {"name": "tomatoes", "quantity": "2", "unit": "medium"},
            ],
        )

        meal_id = self.store.plan_recipe(recipe_id, "2026-08-04", "dinner", "grant", "grant")
        meals = self.store.list_meals(start_date="2026-08-04", end_date="2026-08-04")
        self.assertEqual(meals[0]["id"], meal_id)
        self.assertEqual(meals[0]["title"], "Bean bowl")
        self.assertEqual(meals[0]["ingredients"], ["1 can beans", "2 medium tomatoes"])
        self.assertEqual(self.store.add_meal_ingredients_to_groceries(meal_id, "grant"), ["1 can beans", "2 medium tomatoes"])


if __name__ == "__main__":
    unittest.main()
