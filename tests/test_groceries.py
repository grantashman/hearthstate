import json
import threading
import unittest
from datetime import datetime
from urllib.request import Request, urlopen

from family_planner.dashboard import DashboardServer
from family_planner.pricing import apply_known_coles_prices
from family_planner.store import PlannerStore


class GroceryBudgetStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")
        self.store.add_grocery_item("milk", "grant")
        self.store.add_grocery_item("bananas", "grant")
        self.store.add_grocery_item("mystery item", "grant")

    def tearDown(self):
        self.store.close()

    def test_prices_keep_coles_provenance_and_budget_counts_unknowns(self):
        items = self.store.list_grocery_items()
        milk = next(item for item in items if item["name"] == "milk")
        bananas = next(item for item in items if item["name"] == "bananas")
        self.store.set_grocery_price(
            milk["id"], 3.55, "Coles Full Cream Milk 2L",
            "https://www.coles.com.au/product/coles-full-cream-milk-2l-439693",
            "observed", "2026-08-02", "Location-sensitive online price.",
        )
        self.store.set_grocery_price(
            bananas["id"], 0.83, "Coles Bananas approx. 170g",
            "https://www.coles.com.au/product/coles-bananas-approx.-170g-409499",
            "observed", "2026-08-02", "Final price is based on weight.",
        )
        self.store.set_weekly_budget(35.00, "grant")

        snapshot = self.store.grocery_budget_snapshot()

        self.assertEqual(snapshot["priced_total"], 4.38)
        self.assertEqual(snapshot["unknown_price_count"], 1)
        self.assertEqual(snapshot["budget"], 35.00)
        self.assertEqual(snapshot["remaining"], 30.62)
        self.assertEqual(snapshot["items"][0]["price_source"], "Coles Full Cream Milk 2L")
        self.assertEqual(snapshot["items"][0]["price_confidence"], "observed")

    def test_coles_alias_matching_prefers_requested_coles_products(self):
        self.store.add_grocery_item("cole’s brand white pepper", "grant")
        self.store.add_grocery_item("i'm perfect potatoes", "grant")
        self.store.add_grocery_item("i'm perfect sweet potatoes", "grant")
        self.store.add_grocery_item("i'm perfect carrots", "grant")

        updated = apply_known_coles_prices(self.store, checked_at="2026-08-02")
        self.assertEqual(updated, [])
        items = {item["name"]: item for item in self.store.list_grocery_items()}
        self.assertEqual(items["milk"]["price"], 1.85)
        self.assertEqual(items["milk"]["price_source"], "Coles Australian Full Cream Long Life Milk 1L")
        self.assertEqual(items["cole’s brand white pepper"]["price_source"], "Coles White Pepper 100g")
        self.assertEqual(items["i'm perfect potatoes"]["price_source"], "Coles I'm Perfect Potatoes Imperfect 4kg")
        self.assertEqual(items["i'm perfect sweet potatoes"]["price_source"], "Coles I'm Perfect Sweet Potato 1.5kg")
        self.assertEqual(items["i'm perfect carrots"]["price_source"], "Coles I'm Perfect Carrots Prepacked 1.5kg")

    def test_recipe_style_grocery_names_match_continuously(self):
        names = [
            "coles popping corn kernels 400g",
            "coles simply vegetable oil 4l",
            "coles simply table spread 1kg",
            "500 g beef strips",
            "1 head broccoli",
            "1 brown onion",
            "2 cloves garlic",
            "1 tbsp fresh ginger",
        ]
        for name in names:
            self.store.add_grocery_item(name, "grant")

        first = apply_known_coles_prices(self.store, checked_at="2026-08-02")
        second = apply_known_coles_prices(self.store, checked_at="2026-08-02")
        items = {item["name"]: item for item in self.store.list_grocery_items()}

        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual({name for name in names if items[name]["price"] is not None}, set(names))
        self.assertEqual(items["coles popping corn kernels 400g"]["price_source"], "Coles Popping Corn Kernels 400g")
        self.assertEqual(items["coles simply vegetable oil 4l"]["price_source"], "Coles Simply Vegetable Oil 4L")
        self.assertEqual(items["1 tbsp fresh ginger"]["price_source"], "Coles Australian Ginger Loose approx. 130g")

    def test_common_recipe_items_have_explicit_safe_matches(self):
        names = [
            "500 g chicken breast",
            "1 can cannellini beans",
            "2 stalks celery",
            "400 g diced tomatoes",
            "1 litre chicken stock",
            "100 g kale",
            "1/2 lemon",
        ]
        for name in names:
            self.store.add_grocery_item(name, "grant")

        self.assertEqual(apply_known_coles_prices(self.store, checked_at="2026-08-03"), [])
        items = {item["name"]: item for item in self.store.list_grocery_items()}
        self.assertEqual(items["500 g chicken breast"]["price_source"], "Coles RSPCA Approved Chicken Breast Fillets Small Pack approx. 600g")
        self.assertEqual(items["1 can cannellini beans"]["price_source"], "Coles Simply Cannellini Beans 420g")
        self.assertEqual(items["2 stalks celery"]["price_source"], "Coles Celery Bunch 1 Each")
        self.assertEqual(items["400 g diced tomatoes"]["price_source"], "Coles Australian Diced Tomatoes 400g")
        self.assertEqual(items["1 litre chicken stock"]["price_source"], "Coles Liquid Real Stock Chicken 1L")
        self.assertEqual(items["100 g kale"]["price_source"], "Coles Chopped Kale 140g")
        self.assertEqual(items["1/2 lemon"]["price_source"], "Coles Lemons 1 Each")

    def test_manual_price_is_not_overwritten_by_continuous_matching(self):
        item = next(item for item in self.store.list_grocery_items() if item["name"] == "milk")
        manual_item_id = item["id"]
        self.store.set_grocery_price(manual_item_id, 2.22, "Manual entry", None, "manual", "2026-08-02", "Household price")
        self.assertEqual(apply_known_coles_prices(self.store, checked_at="2026-08-02"), [])
        current = next(item for item in self.store.list_grocery_items() if item["id"] == manual_item_id)
        self.assertEqual(current["price"], 2.22)
        self.assertEqual(current["price_confidence"], "manual")


class GroceryBudgetHTTPTests(unittest.TestCase):
    def test_groceries_page_api_and_budget_update_exist(self):
        store = PlannerStore(":memory:")
        store.add_grocery_item("milk", "grant")
        store.add_grocery_item("mystery item", "grant")
        server = DashboardServer(("127.0.0.1", 0), store=store, now=lambda: datetime(2026, 8, 2, 8, 0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            with urlopen(base + "/groceries", timeout=2) as response:
                self.assertEqual(response.status, 200)
                page = response.read().decode()
                self.assertIn("Weekly grocery budget", page)

            with urlopen(base + "/groceries.js", timeout=2) as response:
                script = response.read().decode()
            self.assertIn("quantity-form", script)
            self.assertIn("/api/groceries/item", script)
            self.assertIn("window.setInterval(load, 60000)", script)
            with urlopen(base + "/api/groceries", timeout=2) as response:
                payload = json.loads(response.read())
                self.assertEqual(payload["unknown_price_count"], 1)
                milk = next(item for item in payload["items"] if item["name"] == "milk")
                self.assertEqual(milk["quantity"], 1.0)
                self.assertEqual(milk["price"], 1.85)
                self.assertEqual(milk["price_source"], "Coles Australian Full Cream Long Life Milk 1L")

            item_body = json.dumps({"item_id": milk["id"], "quantity": 3}).encode()
            item_request = Request(base + "/api/groceries/item", data=item_body, method="POST", headers={"Content-Type": "application/json"})
            with urlopen(item_request, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["item"]["quantity"], 3.0)

            body = json.dumps({"budget": 42.50, "updated_by": "grant"}).encode()
            request = Request(base + "/api/groceries/budget", data=body, method="POST", headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["budget"], 42.50)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            store.close()


if __name__ == "__main__":
    unittest.main()
