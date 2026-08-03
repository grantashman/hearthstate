from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any


HOUSEHOLD_MEMBERS = {
    "grant": "Grant",
    "billie": "Billie",
    "skye": "Skye",
    "all": "All",
}

TASK_RECURRENCES = {
    "none": "Does not repeat",
    "daily": "Every day",
    "weekly": "Every week",
    "fortnightly": "Every fortnight",
    "monthly": "Every month",
    "yearly": "Every year",
}


def normalize_assignee(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in HOUSEHOLD_MEMBERS else None


def assignee_label(value: str | None) -> str:
    return HOUSEHOLD_MEMBERS.get(value or "", "Unassigned")


def normalize_recurrence(value: str | None) -> str:
    normalized = (value or "none").strip().lower().replace(" ", "_")
    aliases = {
        "": "none",
        "none": "none",
        "no": "none",
        "never": "none",
        "daily": "daily",
        "every_day": "daily",
        "weekly": "weekly",
        "every_week": "weekly",
        "fortnightly": "fortnightly",
        "biweekly": "fortnightly",
        "every_fortnight": "fortnightly",
        "monthly": "monthly",
        "every_month": "monthly",
        "yearly": "yearly",
        "annually": "yearly",
        "every_year": "yearly",
    }
    if normalized not in aliases:
        raise ValueError("invalid recurrence")
    return aliases[normalized]


class PlannerStore:
    """SQLite persistence layer for the planner's shared primitives."""

    def __init__(self, database: str = "family_planner.db") -> None:
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        with self._lock:
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS grocery_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    quantity REAL NOT NULL DEFAULT 1,
                    unit TEXT NOT NULL DEFAULT 'each',
                    category TEXT NOT NULL DEFAULT 'General',
                    price REAL,
                    price_source TEXT,
                    price_url TEXT,
                    price_checked_at TEXT,
                    price_confidence TEXT,
                    price_note TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS planner_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    due_at TEXT,
                    owner TEXT,
                    assignee TEXT,
                    private INTEGER NOT NULL DEFAULT 0,
                    recurrence TEXT NOT NULL DEFAULT 'none',
                    status TEXT NOT NULL DEFAULT 'open',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    person TEXT,
                    assignee TEXT,
                    status TEXT NOT NULL DEFAULT 'confirmed',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS meals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meal_date TEXT NOT NULL,
                    meal_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    cook TEXT,
                    status TEXT NOT NULL DEFAULT 'planned',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS meal_ingredients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
                    name TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS recipes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    source_policy TEXT NOT NULL DEFAULT 'link_only',
                    title TEXT NOT NULL,
                    source_url TEXT NOT NULL UNIQUE,
                    image_url TEXT,
                    summary TEXT NOT NULL DEFAULT '',
                    prep_minutes INTEGER,
                    cook_minutes INTEGER,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS recipe_ingredients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    quantity TEXT NOT NULL DEFAULT '',
                    unit TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS saved_recipes (
                    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                    saved_by TEXT NOT NULL,
                    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (recipe_id, saved_by)
                );

                CREATE TABLE IF NOT EXISTS inbox_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_text TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'dashboard',
                    private INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'open',
                    converted_type TEXT,
                    converted_id INTEGER,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TEXT
                );
                """
            )
            self._ensure_column("tasks", "assignee", "TEXT")
            self._ensure_column("tasks", "recurrence", "TEXT NOT NULL DEFAULT 'none'")
            self._ensure_column("events", "assignee", "TEXT")
            self._ensure_column("meals", "recipe_id", "INTEGER")
            for column, definition in {
                "quantity": "REAL NOT NULL DEFAULT 1",
                "unit": "TEXT NOT NULL DEFAULT 'each'",
                "category": "TEXT NOT NULL DEFAULT 'General'",
                "price": "REAL",
                "price_source": "TEXT",
                "price_url": "TEXT",
                "price_checked_at": "TEXT",
                "price_confidence": "TEXT",
                "price_note": "TEXT",
            }.items():
                self._ensure_column("grocery_items", column, definition)
            self.connection.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def add_inbox_item(
        self,
        original_text: str,
        created_by: str,
        *,
        source: str = "dashboard",
        private: bool = False,
    ) -> int:
        original_text = str(original_text).strip()
        created_by = str(created_by).strip()
        source = str(source or "dashboard").strip()
        if not original_text:
            raise ValueError("original_text is required")
        if len(original_text) > 4000:
            raise ValueError("original_text is too long")
        if not created_by:
            raise ValueError("created_by is required")
        if len(created_by) > 120:
            raise ValueError("created_by is too long")
        if len(source) > 80:
            raise ValueError("source is too long")
        if not isinstance(private, bool):
            raise ValueError("private must be a boolean")
        with self._lock:
            cursor = self.connection.execute(
                "INSERT INTO inbox_items (original_text, source, private, created_by) VALUES (?, ?, ?, ?)",
                (original_text, source or "dashboard", int(private), created_by),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    def get_inbox_item(
        self,
        item_id: int,
        *,
        viewer: str | None = None,
        include_closed: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            row = self.connection.execute("SELECT * FROM inbox_items WHERE id = ?", (item_id,)).fetchone()
            if row is None or (not include_closed and row["status"] != "open"):
                raise ValueError("inbox item not found")
            if viewer is not None and row["private"] and row["created_by"] != viewer:
                raise ValueError("inbox item not found")
            return dict(row)

    def list_inbox_items(self, *, viewer: str = "you", include_closed: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            status_clause = "" if include_closed else " AND status = 'open'"
            rows = self.connection.execute(
                f"SELECT * FROM inbox_items WHERE (private = 0 OR created_by = ?){status_clause} ORDER BY id DESC",
                (viewer,),
            ).fetchall()
            return [dict(row) for row in rows]

    def archive_inbox_item(self, item_id: int) -> dict[str, Any]:
        with self._lock:
            cursor = self.connection.execute(
                "UPDATE inbox_items SET status = 'archived', resolved_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'open'",
                (item_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("inbox item not found")
            self.connection.commit()
            return dict(self.connection.execute("SELECT * FROM inbox_items WHERE id = ?", (item_id,)).fetchone())

    def convert_inbox_item(
        self,
        item_id: int,
        converted_type: str,
        payload: dict[str, Any],
        *,
        created_by: str,
    ) -> dict[str, Any]:
        converted_type = str(converted_type).strip().lower()
        if converted_type not in {"task", "event", "meal", "grocery"}:
            raise ValueError("unsupported inbox conversion")
        self.get_inbox_item(item_id)
        payload = payload or {}
        if converted_type == "task":
            title = str(payload.get("title", "")).strip()
            if not title:
                raise ValueError("title is required")
            new_id = self.add_task(
                title,
                str(payload.get("due_at", "")).strip() or None,
                str(created_by) if payload.get("private") else None,
                bool(payload.get("private")),
                str(created_by),
                assignee=payload.get("assignee"),
                recurrence=payload.get("recurrence", "none"),
            )
            result = next(task for task in self.list_tasks() if task["id"] == new_id)
        elif converted_type == "event":
            title = str(payload.get("title", "")).strip()
            starts_at = str(payload.get("starts_at", "")).strip()
            if not title or not starts_at:
                raise ValueError("title and starts_at are required")
            new_id = self.add_event(
                title, starts_at, payload.get("person") or None, str(created_by),
                assignee=payload.get("assignee"),
            )
            result = next(event for event in self.list_events() if event["id"] == new_id)
        elif converted_type == "meal":
            title = str(payload.get("title", "")).strip()
            meal_date = str(payload.get("meal_date", "")).strip()
            if not title or not meal_date:
                raise ValueError("title and meal_date are required")
            ingredients = [str(item).strip().lower() for item in payload.get("ingredients", []) if str(item).strip()]
            new_id = self.add_meal(
                meal_date,
                str(payload.get("meal_type", "dinner")),
                title,
                payload.get("cook") or None,
                ingredients,
                str(created_by),
            )
            result = next(meal for meal in self.list_meals() if meal["id"] == new_id)
        else:
            name = str(payload.get("name", payload.get("title", ""))).strip()
            if not name:
                raise ValueError("name is required")
            self.add_grocery_item(name, str(created_by))
            result = next(item for item in self.list_grocery_items() if item["name"].lower() == name.lower())
            new_id = result["id"]

        with self._lock:
            cursor = self.connection.execute(
                "UPDATE inbox_items SET status = 'converted', converted_type = ?, converted_id = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'open'",
                (converted_type, new_id, item_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("inbox item not found")
            self.connection.commit()
        return result

    def health_check(self) -> dict[str, str]:
        with self._lock:
            self.connection.execute("SELECT 1").fetchone()
            integrity = str(self.connection.execute("PRAGMA quick_check").fetchone()[0])
        return {"database": "ok" if integrity == "ok" else "degraded", "integrity": integrity}

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def add_grocery_item(self, name: str, created_by: str) -> bool:
        with self._lock:
            existing = self.connection.execute(
                "SELECT 1 FROM grocery_items WHERE lower(name) = lower(?) AND status = 'open'",
                (name,),
            ).fetchone()
            if existing:
                return False
            self.connection.execute(
                "INSERT INTO grocery_items (name, created_by) VALUES (?, ?)",
                (name, created_by),
            )
            self.connection.commit()
        # Match immediately on every successful grocery capture so callers never
        # have to wait for a page refresh or press a separate retailer button.
        from .pricing import apply_known_coles_prices
        apply_known_coles_prices(self)
        return True

    def list_grocery_items(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM grocery_items WHERE status = 'open' ORDER BY category COLLATE NOCASE, id"
            ).fetchall()
            return [dict(row) for row in rows]

    def update_grocery_item(
        self,
        item_id: int,
        *,
        quantity: float | None = None,
        unit: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            current = self.connection.execute("SELECT * FROM grocery_items WHERE id = ?", (item_id,)).fetchone()
            if current is None:
                raise ValueError("grocery item not found")
            self.connection.execute(
                "UPDATE grocery_items SET quantity = ?, unit = ?, category = ? WHERE id = ?",
                (
                    float(quantity) if quantity is not None else current["quantity"],
                    (unit or current["unit"]).strip(),
                    (category or current["category"]).strip(),
                    item_id,
                ),
            )
            self.connection.commit()
            return dict(self.connection.execute("SELECT * FROM grocery_items WHERE id = ?", (item_id,)).fetchone())

    def set_grocery_price(
        self,
        item_id: int,
        price: float,
        source: str,
        url: str | None,
        confidence: str,
        checked_at: str,
        note: str = "",
    ) -> dict[str, Any]:
        if price < 0:
            raise ValueError("price cannot be negative")
        with self._lock:
            if not self.connection.execute("SELECT 1 FROM grocery_items WHERE id = ?", (item_id,)).fetchone():
                raise ValueError("grocery item not found")
            self.connection.execute(
                """UPDATE grocery_items
                   SET price = ?, price_source = ?, price_url = ?, price_confidence = ?,
                       price_checked_at = ?, price_note = ?
                   WHERE id = ?""",
                (round(float(price), 2), source.strip(), url, confidence.strip(), checked_at.strip(), note.strip(), item_id),
            )
            self.connection.commit()
            return dict(self.connection.execute("SELECT * FROM grocery_items WHERE id = ?", (item_id,)).fetchone())

    def set_weekly_budget(self, amount: float, updated_by: str) -> float:
        if amount < 0:
            raise ValueError("budget cannot be negative")
        with self._lock:
            self.connection.execute(
                "INSERT INTO planner_settings (key, value, updated_by) VALUES ('weekly_grocery_budget', ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by, updated_at = CURRENT_TIMESTAMP",
                (f"{float(amount):.2f}", updated_by),
            )
            self.connection.commit()
            return float(amount)

    def get_weekly_budget(self) -> float | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT value FROM planner_settings WHERE key = 'weekly_grocery_budget'"
            ).fetchone()
            return float(row["value"]) if row else None

    def grocery_budget_snapshot(self) -> dict[str, Any]:
        with self._lock:
            items = [dict(row) for row in self.connection.execute(
                "SELECT * FROM grocery_items WHERE status = 'open' ORDER BY category COLLATE NOCASE, id"
            ).fetchall()]
            priced_total = 0.0
            unknown_price_count = 0
            for item in items:
                item["quantity"] = float(item["quantity"] or 1)
                item["line_total"] = round(item["price"] * item["quantity"], 2) if item["price"] is not None else None
                if item["line_total"] is None:
                    unknown_price_count += 1
                else:
                    priced_total += item["line_total"]
            priced_total = round(priced_total, 2)
            budget = self.get_weekly_budget()
            return {
                "items": items,
                "total_count": len(items),
                "priced_count": len(items) - unknown_price_count,
                "unknown_price_count": unknown_price_count,
                "priced_total": priced_total,
                "budget": budget,
                "remaining": round(budget - priced_total, 2) if budget is not None else None,
                "over_budget": budget is not None and priced_total > budget,
            }

    def add_task(
        self,
        title: str,
        due_at: str | None,
        owner: str | None,
        private: bool,
        created_by: str,
        assignee: str | None = None,
        recurrence: str = "none",
    ) -> int:
        normalized_recurrence = normalize_recurrence(recurrence)
        if normalized_recurrence != "none" and not due_at:
            raise ValueError("recurrence requires a due date")
        with self._lock:
            cursor = self.connection.execute(
                """
                INSERT INTO tasks (title, due_at, owner, assignee, private, recurrence, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (title, due_at, owner, normalize_assignee(assignee), int(private), normalized_recurrence, created_by),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    def list_tasks(self, assignee: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            query = "SELECT * FROM tasks WHERE status = 'open'"
            params: tuple[str, ...] = ()
            normalized = normalize_assignee(assignee)
            if normalized:
                query += " AND assignee = ?"
                params = (normalized,)
            query += " ORDER BY due_at IS NULL, due_at, id"
            rows = self.connection.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def update_task(
        self,
        task_id: int,
        title: str,
        due_at: str | None,
        assignee: str | None,
        recurrence: str = "none",
    ) -> dict[str, Any]:
        normalized_recurrence = normalize_recurrence(recurrence)
        if normalized_recurrence != "none" and not due_at:
            raise ValueError("recurrence requires a due date")
        with self._lock:
            cursor = self.connection.execute(
                """
                UPDATE tasks
                SET title = ?, due_at = ?, assignee = ?, recurrence = ?
                WHERE id = ? AND status = 'open'
                """,
                (title, due_at, normalize_assignee(assignee), normalized_recurrence, task_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("task not found")
            self.connection.commit()
            row = self.connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row)

    def complete_task(self, task_id: int) -> dict[str, Any]:
        with self._lock:
            cursor = self.connection.execute(
                "UPDATE tasks SET status = 'done' WHERE id = ? AND status = 'open'",
                (task_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("task not found")
            self.connection.commit()
            row = self.connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row)

    def delete_task(self, task_id: int) -> None:
        with self._lock:
            cursor = self.connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            if cursor.rowcount != 1:
                raise ValueError("task not found")
            self.connection.commit()

    def add_event(
        self,
        title: str,
        starts_at: str,
        person: str | None,
        created_by: str,
        assignee: str | None = None,
    ) -> int:
        with self._lock:
            cursor = self.connection.execute(
                """
                INSERT INTO events (title, starts_at, person, assignee, created_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                (title, starts_at, person, normalize_assignee(assignee), created_by),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    def update_event(
        self,
        event_id: int,
        title: str,
        starts_at: str,
        person: str | None,
        assignee: str | None,
    ) -> dict[str, Any]:
        with self._lock:
            self.connection.execute(
                "UPDATE events SET title = ?, starts_at = ?, person = ?, assignee = ? WHERE id = ?",
                (title, starts_at, person, normalize_assignee(assignee), event_id),
            )
            self.connection.commit()
            row = self.connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            if row is None:
                raise ValueError("event not found")
            return dict(row)

    def add_meal(
        self,
        meal_date: str,
        meal_type: str,
        title: str,
        cook: str | None,
        ingredients: list[str],
        created_by: str,
        recipe_id: int | None = None,
    ) -> int:
        with self._lock:
            cursor = self.connection.execute(
                "INSERT INTO meals (meal_date, meal_type, title, cook, created_by, recipe_id) VALUES (?, ?, ?, ?, ?, ?)",
                (meal_date, meal_type.lower(), title, normalize_assignee(cook), created_by, recipe_id),
            )
            meal_id = int(cursor.lastrowid)
            for ingredient in ingredients:
                self.connection.execute(
                    "INSERT INTO meal_ingredients (meal_id, name) VALUES (?, ?)",
                    (meal_id, ingredient),
                )
            self.connection.commit()
            return meal_id

    def update_meal(
        self,
        meal_id: int,
        meal_date: str,
        meal_type: str,
        title: str,
        cook: str | None,
        ingredients: list[str],
    ) -> dict[str, Any]:
        with self._lock:
            if not self.connection.execute("SELECT 1 FROM meals WHERE id = ?", (meal_id,)).fetchone():
                raise ValueError("meal not found")
            self.connection.execute(
                "UPDATE meals SET meal_date = ?, meal_type = ?, title = ?, cook = ? WHERE id = ?",
                (meal_date, meal_type.lower(), title, normalize_assignee(cook), meal_id),
            )
            self.connection.execute("DELETE FROM meal_ingredients WHERE meal_id = ?", (meal_id,))
            for ingredient in ingredients:
                self.connection.execute(
                    "INSERT INTO meal_ingredients (meal_id, name) VALUES (?, ?)",
                    (meal_id, ingredient),
                )
            self.connection.commit()
            meal = dict(self.connection.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone())
            meal["ingredients"] = [
                row["name"]
                for row in self.connection.execute(
                    "SELECT name FROM meal_ingredients WHERE meal_id = ? ORDER BY id",
                    (meal_id,),
                ).fetchall()
            ]
            return meal

    def delete_meal(self, meal_id: int) -> None:
        with self._lock:
            cursor = self.connection.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
            if cursor.rowcount != 1:
                raise ValueError("meal not found")
            self.connection.commit()

    def add_recipe(
        self,
        source: str,
        source_policy: str,
        title: str,
        source_url: str,
        *,
        image_url: str | None = None,
        summary: str = "",
        tags: list[str] | None = None,
        prep_minutes: int | None = None,
        cook_minutes: int | None = None,
        ingredients: list[dict[str, str]] | None = None,
    ) -> int:
        """Store recipe metadata; full instructions are intentionally not copied."""
        with self._lock:
            existing = self.connection.execute(
                "SELECT id FROM recipes WHERE source_url = ?", (source_url,)
            ).fetchone()
            if existing:
                recipe_id = int(existing["id"])
                self.connection.execute(
                    "UPDATE recipes SET source = ?, source_policy = ?, title = ?, image_url = ?, summary = ?, prep_minutes = ?, cook_minutes = ?, tags_json = ? WHERE id = ?",
                    (source, source_policy, title, image_url, summary, prep_minutes, cook_minutes, json.dumps(tags or []), recipe_id),
                )
                self.connection.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (recipe_id,))
            else:
                cursor = self.connection.execute(
                    "INSERT INTO recipes (source, source_policy, title, source_url, image_url, summary, prep_minutes, cook_minutes, tags_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (source, source_policy, title, source_url, image_url, summary, prep_minutes, cook_minutes, json.dumps(tags or [])),
                )
                recipe_id = int(cursor.lastrowid)
            for ingredient in ingredients or []:
                self.connection.execute(
                    "INSERT INTO recipe_ingredients (recipe_id, name, quantity, unit) VALUES (?, ?, ?, ?)",
                    (recipe_id, ingredient.get("name", "").strip(), ingredient.get("quantity", "").strip(), ingredient.get("unit", "").strip()),
                )
            self.connection.commit()
            return recipe_id

    def list_recipes(
        self,
        *,
        search: str | None = None,
        tag: str | None = None,
        saved_by: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            query = "SELECT * FROM recipes"
            clauses: list[str] = []
            params: list[str] = []
            if search:
                clauses.append("(lower(title) LIKE ? OR lower(summary) LIKE ?)")
                needle = f"%{search.lower()}%"
                params.extend([needle, needle])
            if saved_by:
                clauses.append("EXISTS (SELECT 1 FROM saved_recipes saved WHERE saved.recipe_id = recipes.id AND saved.saved_by = ?)")
                params.append(saved_by)
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY title COLLATE NOCASE, id"
            rows = self.connection.execute(query, params).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["tags"] = json.loads(item.pop("tags_json") or "[]")
                if tag and tag.lower() not in {value.lower() for value in item["tags"]}:
                    continue
                item["ingredients"] = [
                    dict(ingredient)
                    for ingredient in self.connection.execute(
                        "SELECT name, quantity, unit FROM recipe_ingredients WHERE recipe_id = ? ORDER BY id",
                        (item["id"],),
                    ).fetchall()
                ]
                item["saved"] = bool(self.connection.execute(
                    "SELECT 1 FROM saved_recipes WHERE recipe_id = ? LIMIT 1", (item["id"],)
                ).fetchone())
                result.append(item)
            return result

    def set_recipe_saved(self, recipe_id: int, saved_by: str, saved: bool) -> bool:
        with self._lock:
            if not self.connection.execute("SELECT 1 FROM recipes WHERE id = ?", (recipe_id,)).fetchone():
                raise ValueError("recipe not found")
            if saved:
                self.connection.execute("INSERT OR IGNORE INTO saved_recipes (recipe_id, saved_by) VALUES (?, ?)", (recipe_id, saved_by))
            else:
                self.connection.execute("DELETE FROM saved_recipes WHERE recipe_id = ? AND saved_by = ?", (recipe_id, saved_by))
            self.connection.commit()
            return True

    def plan_recipe(
        self,
        recipe_id: int,
        meal_date: str,
        meal_type: str,
        cook: str | None,
        created_by: str,
    ) -> int:
        recipe = next((item for item in self.list_recipes() if item["id"] == recipe_id), None)
        if recipe is None:
            raise ValueError("recipe not found")
        ingredients = []
        for ingredient in recipe["ingredients"]:
            parts = [ingredient["quantity"], ingredient["unit"], ingredient["name"]]
            ingredients.append(" ".join(part for part in parts if part).strip())
        return self.add_meal(meal_date, meal_type, recipe["title"], cook, ingredients, created_by, recipe_id=recipe_id)

    def list_meals(self, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            query = "SELECT * FROM meals WHERE status = 'planned'"
            params: list[str] = []
            if start_date:
                query += " AND meal_date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND meal_date <= ?"
                params.append(end_date)
            query += " ORDER BY meal_date, CASE meal_type WHEN 'breakfast' THEN 1 WHEN 'lunch' THEN 2 WHEN 'dinner' THEN 3 ELSE 4 END, id"
            meals = [dict(row) for row in self.connection.execute(query, params).fetchall()]
            for meal in meals:
                meal["ingredients"] = [
                    row["name"]
                    for row in self.connection.execute(
                        "SELECT name FROM meal_ingredients WHERE meal_id = ? ORDER BY id",
                        (meal["id"],),
                    ).fetchall()
                ]
            return meals

    def add_meal_ingredients_to_groceries(self, meal_id: int, created_by: str) -> list[str]:
        with self._lock:
            names = [
                row["name"]
                for row in self.connection.execute(
                    "SELECT name FROM meal_ingredients WHERE meal_id = ? ORDER BY id",
                    (meal_id,),
                ).fetchall()
            ]
            added = [name for name in names if self.add_grocery_item(name, created_by)]
            return added

    def add_recipe_ingredients_to_groceries(
        self,
        recipe_id: int,
        created_by: str,
        ingredient_indexes: list[int] | None = None,
    ) -> list[str]:
        with self._lock:
            recipe = self.connection.execute("SELECT 1 FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
            if recipe is None:
                raise ValueError("recipe not found")
            ingredients = self.connection.execute(
                "SELECT name, quantity, unit FROM recipe_ingredients WHERE recipe_id = ? ORDER BY id",
                (recipe_id,),
            ).fetchall()
            if ingredient_indexes is None:
                selected = range(len(ingredients))
            else:
                selected_indexes = {int(index) for index in ingredient_indexes}
                if any(index < 0 or index >= len(ingredients) for index in selected_indexes):
                    raise ValueError("ingredient index is out of range")
                selected = sorted(selected_indexes)
            names = [
                " ".join(part for part in (ingredients[index]["quantity"], ingredients[index]["unit"], ingredients[index]["name"]) if part).strip()
                for index in selected
            ]
            return [name for name in names if self.add_grocery_item(name, created_by)]

    def list_events(self, assignee: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            query = "SELECT * FROM events WHERE status != 'cancelled'"
            params: tuple[str, ...] = ()
            normalized = normalize_assignee(assignee)
            if normalized:
                query += " AND assignee = ?"
                params = (normalized,)
            query += " ORDER BY starts_at, id"
            rows = self.connection.execute(query, params).fetchall()
            return [dict(row) for row in rows]
