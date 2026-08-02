import tempfile
import unittest
from pathlib import Path

from family_planner.store import PlannerStore
from seed_recipes import seed


class SeedRecipeTests(unittest.TestCase):
    def test_seeded_catalogue_has_local_ingredients_for_every_recipe(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "recipes.sqlite3")
            self.assertEqual(seed(database, str(project_root / "recipe_seeds.json")), 22)
            store = PlannerStore(database)
            try:
                recipes = store.list_recipes()
                self.assertEqual(len(recipes), 22)
                self.assertTrue(all(recipe["source_policy"] == "local_original" for recipe in recipes))
                self.assertTrue(all(recipe["ingredients"] for recipe in recipes))
                self.assertEqual(sum(len(recipe["ingredients"]) for recipe in recipes), 189)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
