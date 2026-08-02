import json
import threading
import unittest
from datetime import datetime
from urllib.request import urlopen

from family_planner.dashboard import DashboardServer, build_dashboard_snapshot
from family_planner.app import FamilyPlanner
from family_planner.store import PlannerStore


class DashboardSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.store = PlannerStore(":memory:")
        self.store.add_task(
            "renew prescription",
            "2026-08-02T10:00:00",
            "you",
            True,
            "you",
        )
        self.store.add_task(
            "school permission form",
            "2026-08-02T09:00:00",
            None,
            False,
            "partner",
        )
        self.store.add_task(
            "partner private note",
            "2026-08-02T09:30:00",
            "partner",
            True,
            "partner",
        )
        self.store.add_event(
            "soccer practice",
            "2026-08-02T17:00:00",
            "Alex",
            "partner",
        )
        self.store.add_grocery_item("oat milk", "you")

    def tearDown(self):
        self.store.close()

    def test_imessage_grocery_capture_is_visible_in_dashboard_snapshot(self):
        response = FamilyPlanner(self.store).handle_message(
            "you",
            "Add bananas to the shopping list",
        )
        snapshot = build_dashboard_snapshot(
            self.store,
            viewer="partner",
            now=datetime(2026, 8, 2, 8, 0),
        )

        self.assertIn("bananas", response)
        self.assertIn("bananas", [item["name"] for item in snapshot["groceries"]])

    def test_snapshot_is_family_state_first_and_hides_other_private_tasks(self):
        snapshot = build_dashboard_snapshot(
            self.store,
            viewer="you",
            now=datetime(2026, 8, 2, 8, 0),
        )

        self.assertEqual(snapshot["counts"], {
            "attention": 2,
            "today_events": 1,
            "groceries": 1,
        })
        self.assertEqual(
            [item["title"] for item in snapshot["attention"]],
            ["school permission form", "renew prescription"],
        )
        self.assertNotIn(
            "partner private note",
            [item["title"] for item in snapshot["attention"]],
        )
        self.assertEqual(snapshot["today"][0]["title"], "soccer practice")
        self.assertEqual(snapshot["groceries"][0]["name"], "oat milk")

    def test_connected_attention_today_and_weekly_planning_read_model(self):
        self.store.add_grocery_item("unpriced pantry item", "you")
        self.store.add_meal(
            "2026-08-02", "dinner", "Coconut lentil curry", "you", ["lentils"], "you",
        )
        self.store.add_meal(
            "2026-08-03", "lunch", "Leftover curry", "partner", ["curry"], "partner",
        )

        snapshot = build_dashboard_snapshot(
            self.store,
            viewer="you",
            now=datetime(2026, 8, 2, 8, 0),
        )

        self.assertTrue(any(item["source_type"] == "task" for item in snapshot["attention_items"]))
        self.assertTrue(any(item["source_type"] == "meal_gap" and item["source_id"] == "2026-08-03" for item in snapshot["attention_items"]))
        self.assertTrue(any(item["source_type"] == "grocery" for item in snapshot["attention_items"]))
        self.assertEqual({item["source_type"] for item in snapshot["today_items"]}, {"event", "task", "meal"})
        self.assertEqual(len(snapshot["planning_week"]), 7)
        self.assertTrue(any(item["source_type"] == "meal" for item in snapshot["calendar"]))
        first_day = snapshot["planning_week"][0]
        self.assertEqual(first_day["date"], "2026-08-02")
        self.assertEqual(first_day["dinner"]["title"], "Coconut lentil curry")
        self.assertEqual(snapshot["planning_week"][1]["meals"][0]["title"], "Leftover curry")


class DashboardHTTPTests(unittest.TestCase):
    def test_serves_theme_toggle_assets(self):
        store = PlannerStore(":memory:")
        server = DashboardServer(("127.0.0.1", 0), store=store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            with urlopen(base_url + "/", timeout=2) as response:
                page = response.read().decode()
            with urlopen(base_url + "/styles.css", timeout=2) as response:
                stylesheet = response.read().decode()
            with urlopen(base_url + "/app.js", timeout=2) as response:
                script = response.read().decode()
        finally:
            server.shutdown()
            server.server_close()
            store.close()
            thread.join(timeout=2)

        self.assertIn('id="themeToggle"', page)
        self.assertIn('id="greetingEyebrow"', page)
        self.assertIn('id="greetingTitle"', page)
        self.assertIn('id="attentionList"', page)
        self.assertIn('id="todayTimeline"', page)
        self.assertIn('id="planningStrip"', page)
        self.assertIn('href="/favicon.svg?v=hearthstate-1"', page)
        self.assertIn('class="welcome-utility"', page)
        self.assertIn('class="welcome-note-panel note-panel"', page)
        self.assertLess(page.index('class="welcome-note-panel note-panel"'), page.index('id="weeklyPlan"'))
        self.assertNotIn('viewer-control', page)
        self.assertNotIn('viewerSelect', page)
        self.assertNotIn('Viewing', page)
        self.assertIn("attention_items", script)
        self.assertIn("planning_week", script)
        self.assertIn("attention-complete", script)
        self.assertIn("getTimeOfDayGreeting", script)
        self.assertIn("localStorage", script)

    def test_hearthstate_brand_is_available_on_every_page(self):
        store = PlannerStore(":memory:")
        server = DashboardServer(("127.0.0.1", 0), store=store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            pages = "/", "/calendar", "/tasks", "/meals", "/recipes", "/groceries"
            for page_path in pages:
                with urlopen(base_url + page_path, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    html = response.read().decode()
                self.assertIn("Hearthstate", html)
                self.assertIn("hearthstate", html)
                self.assertNotIn("homebase", html.lower())
        finally:
            server.shutdown()
            server.server_close()
            store.close()
            thread.join(timeout=2)

    def test_mobile_navigation_is_available_on_every_page(self):
        store = PlannerStore(":memory:")
        server = DashboardServer(("127.0.0.1", 0), store=store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            pages = "/", "/calendar", "/tasks", "/meals", "/recipes", "/groceries"
            for page_path in pages:
                with urlopen(base_url + page_path, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    html = response.read().decode()
                self.assertIn('class="mobile-nav-toggle"', html)
                self.assertIn('aria-controls="primaryNav"', html)
                self.assertIn('/nav.js?v=hearthstate-1', html)
            with urlopen(base_url + "/nav.js", timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("mobile-nav-toggle", response.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            store.close()
            thread.join(timeout=2)


    def test_serves_recipes_page_and_assets(self):
        store = PlannerStore(":memory:")
        server = DashboardServer(("127.0.0.1", 0), store=store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            with urlopen(base_url + "/recipes", timeout=2) as response:
                page = response.read().decode()
            with urlopen(base_url + "/recipes.js", timeout=2) as response:
                script = response.read().decode()
            with urlopen(base_url + "/styles.css", timeout=2) as response:
                stylesheet = response.read().decode()
            with urlopen(base_url + "/recipe-images/stir-fry.png", timeout=2) as response:
                image = response.read()
        finally:
            server.shutdown()
            server.server_close()
            store.close()
            thread.join(timeout=2)

        self.assertIn("Simple and healthy", page)
        self.assertIn('id="recipeGrid"', page)
        self.assertIn("Protein-forward", page)
        self.assertIn("saveRecipe", script)
        self.assertIn("recipe-image", script)
        self.assertIn("Illustrative photo", script)
        self.assertIn("Showing ${payload.recipes.length} recipes", script)
        self.assertIn("els.tag.addEventListener('input', loadRecipes)", script)
        self.assertIn("ingredientOwnership", page)
        self.assertIn("grocery_ingredient_indexes", script)
        self.assertIn("Ingredient check", page)
        self.assertIn("ingredient-check", stylesheet)
        self.assertIn("planDialog", page)
        self.assertIn("What night?", page)
        self.assertIn("Who will cook?", page)
        self.assertIn("grocery_ingredient_indexes", script)
        self.assertIn("openPlanDialog", script)
        self.assertIn("min-height: 0", stylesheet)
        self.assertTrue(image.startswith(b"\x89PNG"))
        self.assertIn("/api/recipes", script)

    def test_health_endpoint_and_security_headers(self):
        store = PlannerStore(":memory:")
        server = DashboardServer(("127.0.0.1", 0), store=store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            with urlopen(base_url + "/health", timeout=2) as response:
                payload = json.loads(response.read().decode())
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["status"], "ok")
                self.assertEqual(payload["service"], "hearthstate")
                self.assertEqual(payload["database"], "ok")
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        finally:
            server.shutdown()
            server.server_close()
            store.close()
            thread.join(timeout=2)

    def test_serves_dashboard_page_and_json_snapshot(self):
        store = PlannerStore(":memory:")
        store.add_task("pack school bag", "2026-08-02T09:00:00", None, False, "you")
        server = DashboardServer(("127.0.0.1", 0), store=store, now=lambda: datetime(2026, 8, 2, 8, 0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            with urlopen(base_url + "/", timeout=2) as response:
                page = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn("Hearthstate", page)
                self.assertIn("Needs attention", page)
                self.assertIn('href="/recipes"', page)

            with urlopen(base_url + "/api/dashboard?viewer=you", timeout=2) as response:
                payload = json.loads(response.read().decode())
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["attention"][0]["title"], "pack school bag")
        finally:
            server.shutdown()
            server.server_close()
            store.close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
