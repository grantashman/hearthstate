from __future__ import annotations

import argparse
import calendar
import json
import os
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .pricing import apply_known_coles_prices
from .store import TASK_RECURRENCES, PlannerStore, assignee_label, normalize_assignee, normalize_recurrence
from .timezone import local_now


_DASHBOARD_DIR = Path(__file__).with_name("dashboard")


def _format_time(value: datetime) -> str:
    return value.strftime("%-I:%M %p").replace(":00", "")


def _format_day(value: datetime, now: datetime) -> str:
    if value.date() == now.date():
        return "Today"
    if value.date() == (now + timedelta(days=1)).date():
        return "Tomorrow"
    return value.strftime("%a, %b %-d")


def _format_due(value: datetime, now: datetime) -> str:
    if value <= now:
        return "Due now"
    day = _format_day(value, now)
    return f"{day} · {_format_time(value)}"


def _advance_task_date(value: datetime, recurrence: str) -> datetime:
    if recurrence == "daily":
        return value + timedelta(days=1)
    if recurrence == "weekly":
        return value + timedelta(days=7)
    if recurrence == "fortnightly":
        return value + timedelta(days=14)
    if recurrence == "monthly":
        month = value.month + 1
        year = value.year
        if month == 13:
            month = 1
            year += 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return value.replace(year=year, month=month, day=day)
    if recurrence == "yearly":
        year = value.year + 1
        day = min(value.day, calendar.monthrange(year, value.month)[1])
        return value.replace(year=year, day=day)
    return value


def _task_calendar_items(tasks: list[dict], current: datetime) -> list[dict]:
    horizon = current + timedelta(days=366)
    items: list[dict] = []
    for task in tasks:
        if not task.get("due_at"):
            continue
        recurrence = normalize_recurrence(task.get("recurrence"))
        occurrence = datetime.fromisoformat(task["due_at"])
        if recurrence != "none":
            guard = 0
            while occurrence < current and guard < 5000:
                occurrence = _advance_task_date(occurrence, recurrence)
                guard += 1
            occurrences: list[datetime] = []
            while occurrence <= horizon and len(occurrences) < 500:
                occurrences.append(occurrence)
                occurrence = _advance_task_date(occurrence, recurrence)
        else:
            occurrences = [occurrence]
        for occurrence in occurrences:
            items.append(
                {
                    "id": f"task-{task['id']}-{occurrence.isoformat()}",
                    "source_type": "task",
                    "source_id": task["id"],
                    "title": task["title"],
                    "starts_at": occurrence.isoformat(),
                    "time_label": _format_time(occurrence),
                    "day_label": _format_day(occurrence, current),
                    "person": None,
                    "assignee": task.get("assignee"),
                    "assignee_label": assignee_label(task.get("assignee")),
                    "status": task["status"],
                    "recurrence": recurrence,
                    "recurrence_label": TASK_RECURRENCES[recurrence],
                }
            )
    return items


def _owner_label(owner: str | None, viewer: str) -> str:
    if owner is None:
        return "Unassigned"
    if owner == viewer:
        return "You"
    if owner == "partner":
        return "Partner"
    return owner


def _meal_item(meal: dict, current: datetime) -> dict:
    meal_type = str(meal.get("meal_type", "meal")).lower()
    meal_time = {"breakfast": "07:00:00", "lunch": "12:00:00", "dinner": "18:00:00"}.get(meal_type, "12:00:00")
    starts_at = f"{meal['meal_date']}T{meal_time}"
    cook = meal.get("cook")
    return {
        "id": f"meal-{meal['id']}",
        "source_type": "meal",
        "source_id": meal["id"],
        "title": meal["title"],
        "starts_at": starts_at,
        "time_label": meal_type.title(),
        "day_label": _format_day(datetime.fromisoformat(starts_at), current),
        "person": meal.get("cook_label") or (assignee_label(cook) if cook else None),
        "assignee": cook,
        "assignee_label": meal.get("cook_label") or assignee_label(cook),
        "status": meal.get("status", "planned"),
        "recurrence": "none",
        "recurrence_label": TASK_RECURRENCES["none"],
        "meal_type": meal_type,
        "ingredients": meal.get("ingredients", []),
    }


def _connected_attention(
    task_attention: list[dict],
    meals: list[dict],
    grocery_summary: dict,
    current: datetime,
) -> list[dict]:
    items: list[dict] = []
    for task in task_attention:
        items.append({
            **task,
            "source_type": "task",
            "source_id": task["id"],
            "href": f"/tasks?edit={task['id']}",
            "action_type": "complete",
            "action_label": "Done",
            "meta_label": task["assignee_label"],
        })

    meals_by_date = {meal["meal_date"]: [] for meal in meals}
    for meal in meals:
        meals_by_date.setdefault(meal["meal_date"], []).append(meal)
    for offset in range(3):
        day = current.date() + timedelta(days=offset)
        date_value = day.isoformat()
        dinner = next((meal for meal in meals_by_date.get(date_value, []) if meal["meal_type"].lower() == "dinner"), None)
        day_label = _format_day(datetime.fromisoformat(f"{date_value}T12:00:00"), current)
        if dinner is None:
            items.append({
                "id": f"meal-gap-{date_value}",
                "source_type": "meal_gap",
                "source_id": date_value,
                "title": f"Plan dinner for {day_label}",
                "owner_label": "Meal plan",
                "meta_label": "Meal plan",
                "due_label": day_label,
                "urgency": "now" if offset == 0 else "soon",
                "href": f"/meals?date={date_value}",
                "action_type": "plan",
                "action_label": "Plan dinner",
            })
        elif not dinner.get("cook"):
            items.append({
                "id": f"meal-cook-{dinner['id']}",
                "source_type": "meal",
                "source_id": dinner["id"],
                "title": f"Assign a cook for {dinner['title']}",
                "owner_label": "Meal plan",
                "meta_label": "Meal plan",
                "due_label": day_label,
                "urgency": "now" if offset == 0 else "soon",
                "href": f"/meals?date={date_value}",
                "action_type": "plan",
                "action_label": "Open meal plan",
            })

    if grocery_summary["unknown_price_count"]:
        count = grocery_summary["unknown_price_count"]
        items.append({
            "id": "grocery-unknown-prices",
            "source_type": "grocery",
            "source_id": "unknown-prices",
            "title": f"Review {count} grocery item{'s' if count != 1 else ''} without a price",
            "owner_label": "Groceries",
            "meta_label": "Shopping list",
            "due_label": "Needs review",
            "urgency": "soon",
            "href": "/groceries",
            "action_type": "review",
            "action_label": "Review",
        })
    if grocery_summary["over_budget"]:
        over_by = abs(grocery_summary["remaining"] or 0)
        items.append({
            "id": "grocery-over-budget",
            "source_type": "grocery",
            "source_id": "budget",
            "title": f"Grocery budget is ${over_by:.2f} over",
            "owner_label": "Groceries",
            "meta_label": "Shopping list",
            "due_label": "Needs review",
            "urgency": "now",
            "href": "/groceries",
            "action_type": "review",
            "action_label": "Review",
        })

    priority = {"now": 0, "soon": 1, "open": 2}
    items.sort(key=lambda item: (priority.get(item.get("urgency"), 3), item.get("due_at") or item.get("due_label") or "9999", item["id"]))
    return items[:12]


def _planning_week(current: datetime, calendar_items: list[dict], meal_items: list[dict]) -> list[dict]:
    days: list[dict] = []
    for offset in range(7):
        day = current.date() + timedelta(days=offset)
        date_value = day.isoformat()
        day_meals = [item for item in meal_items if item["starts_at"].startswith(date_value)]
        day_items = [
            {key: item[key] for key in ("id", "source_type", "source_id", "title", "time_label", "assignee", "assignee_label", "recurrence", "recurrence_label")}
            for item in calendar_items
            if item["starts_at"].startswith(date_value)
        ]
        dinner = next((meal for meal in day_meals if meal["meal_type"] == "dinner"), None)
        days.append({
            "date": date_value,
            "date_label": _format_day(datetime.fromisoformat(f"{date_value}T12:00:00"), current),
            "short_label": day.strftime("%a"),
            "day_number": day.day,
            "meals": day_meals,
            "dinner": dinner,
            "items": day_items,
        })
    return days


def build_dashboard_snapshot(
    store: PlannerStore,
    viewer: str = "you",
    now: datetime | None = None,
) -> dict:
    """Build the privacy-filtered read model consumed by the dashboard."""
    current = (now or local_now()).replace(second=0, microsecond=0)
    visible_tasks = [
        task
        for task in store.list_tasks()
        if not task["private"] or task["owner"] == viewer
    ]

    attention: list[dict] = []
    for task in visible_tasks:
        due_at = datetime.fromisoformat(task["due_at"]) if task["due_at"] else None
        if due_at and due_at <= current:
            urgency = "now"
        elif due_at and due_at <= current + timedelta(days=1):
            urgency = "soon"
        else:
            urgency = "open"
        attention.append(
            {
                "id": task["id"],
                "title": task["title"],
                "owner": task["owner"],
                "owner_label": _owner_label(task["owner"], viewer),
                "assignee": task.get("assignee"),
                "assignee_label": assignee_label(task.get("assignee")),
                "private": bool(task["private"]),
                "due_at": task["due_at"],
                "due_label": _format_due(due_at, current) if due_at else "No due date",
                "recurrence": normalize_recurrence(task.get("recurrence")),
                "recurrence_label": TASK_RECURRENCES[normalize_recurrence(task.get("recurrence"))],
                "urgency": urgency,
            }
        )
    attention.sort(
        key=lambda item: (
            0 if item["owner"] is None else 1,
            {"now": 0, "soon": 1, "open": 2}[item["urgency"]],
            item["due_at"] or "9999",
            item["id"],
        )
    )

    calendar_items: list[dict] = []
    for event in store.list_events():
        starts_at = datetime.fromisoformat(event["starts_at"])
        calendar_items.append(
            {
                "id": event["id"],
                "source_type": "event",
                "source_id": event["id"],
                "title": event["title"],
                "starts_at": event["starts_at"],
                "time_label": _format_time(starts_at),
                "day_label": _format_day(starts_at, current),
                "person": event["person"],
                "assignee": event.get("assignee"),
                "assignee_label": assignee_label(event.get("assignee")),
                "status": event["status"],
                "recurrence": "none",
                "recurrence_label": TASK_RECURRENCES["none"],
            }
        )
    calendar_items.extend(_task_calendar_items(visible_tasks, current))
    meal_items = [
        _meal_item(meal, current)
        for meal in store.list_meals(
            start_date=current.date().isoformat(),
            end_date=(current + timedelta(days=366)).date().isoformat(),
        )
    ]
    calendar_items.extend(meal_items)
    calendar_items.sort(key=lambda item: (item["starts_at"], item["source_type"], str(item["id"])))
    today = [
        item for item in calendar_items
        if item["source_type"] == "event" and item["starts_at"][:10] == current.date().isoformat()
    ]
    upcoming = [
        item for item in calendar_items
        if item["source_type"] == "event"
        and current.date().isoformat() < item["starts_at"][:10] <= (current + timedelta(days=7)).date().isoformat()
    ]
    today_items = [
        item for item in calendar_items
        if item["starts_at"][:10] == current.date().isoformat()
    ]
    grocery_summary = store.grocery_budget_snapshot()
    attention_items = _connected_attention(attention, [
        meal for meal in store.list_meals(
            start_date=current.date().isoformat(),
            end_date=(current + timedelta(days=6)).date().isoformat(),
        )
    ], grocery_summary, current)
    planning_week = _planning_week(current, calendar_items, meal_items)

    return {
        "viewer": viewer,
        "generated_at": current.isoformat(),
        "counts": {
            "attention": len(attention),
            "today_events": len(today),
            "groceries": len(store.list_grocery_items()),
        },
        "attention": attention[:8],
        "attention_items": attention_items,
        "tasks": attention,
        "today": today,
        "today_items": today_items,
        "upcoming": upcoming[:8],
        "planning_week": planning_week,
        "calendar": calendar_items,
        "grocery_summary": grocery_summary,
        "groceries": [
            {
                "id": item["id"],
                "name": item["name"],
                "created_by": item["created_by"],
                "quantity": item.get("quantity", 1),
                "unit": item.get("unit", "each"),
                "price": item.get("price"),
                "line_total": round(item["price"] * (item.get("quantity") or 1), 2) if item.get("price") is not None else None,
                "price_source": item.get("price_source"),
                "price_url": item.get("price_url"),
                "price_checked_at": item.get("price_checked_at"),
                "price_confidence": item.get("price_confidence"),
                "price_note": item.get("price_note"),
            }
            for item in store.list_grocery_items()[:12]
        ],
    }


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server: "DashboardServer"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path == "/api/groceries":
            apply_known_coles_prices(self.server.store)
            payload = self.server.store.grocery_budget_snapshot()
            payload["generated_at"] = self.server.now().replace(second=0, microsecond=0).isoformat()
            self._send_json(payload)
            return
        if parsed.path == "/api/recipes":
            query = parse_qs(parsed.query)
            recipes = self.server.store.list_recipes(
                search=query.get("search", [None])[0],
                tag=query.get("tag", [None])[0],
                saved_by=query.get("saved_by", [None])[0],
            )
            self._send_json({"recipes": recipes, "generated_at": self.server.now().replace(second=0, microsecond=0).isoformat()})
            return
        if parsed.path in {"/api/dashboard", "/api/tasks", "/api/calendar", "/api/meals"}:
            viewer = parse_qs(parsed.query).get("viewer", ["you"])[0].strip() or "you"
            assignee = normalize_assignee(parse_qs(parsed.query).get("assignee", [""])[0])
            payload = build_dashboard_snapshot(self.server.store, viewer, self.server.now())
            if assignee:
                payload["tasks"] = [item for item in payload["tasks"] if item.get("assignee") == assignee]
                payload["calendar"] = [item for item in payload["calendar"] if item.get("assignee") == assignee]
            if parsed.path == "/api/meals":
                meals = self.server.store.list_meals()
                payload = {
                    "generated_at": self.server.now().replace(second=0, microsecond=0).isoformat(),
                    "meals": [
                        {**meal, "cook_label": assignee_label(meal.get("cook"))}
                        for meal in meals
                    ],
                }
            elif parsed.path == "/api/tasks":
                payload = {"viewer": viewer, "generated_at": payload["generated_at"], "tasks": payload["tasks"]}
            elif parsed.path == "/api/calendar":
                payload = {"viewer": viewer, "generated_at": payload["generated_at"], "calendar": payload["calendar"]}
            self._send_bytes(
                json.dumps(payload).encode("utf-8"),
                "application/json; charset=utf-8",
                cache_control="no-store",
            )
            return

        if parsed.path.startswith("/recipe-images/"):
            requested = parsed.path.removeprefix("/recipe-images/")
            filename = Path(requested).name
            image_path = _DASHBOARD_DIR / "recipe-images" / filename
            allowed_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
            if requested != filename or filename not in image_path.name or image_path.suffix.lower() not in allowed_types or not image_path.is_file():
                self.send_error(404, "Image not found")
                return
            self._send_bytes(image_path.read_bytes(), allowed_types[image_path.suffix.lower()], cache_control="public, max-age=86400")
            return

        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/calendar": ("calendar.html", "text/html; charset=utf-8"),
            "/calendar/": ("calendar.html", "text/html; charset=utf-8"),
            "/tasks": ("tasks.html", "text/html; charset=utf-8"),
            "/tasks/": ("tasks.html", "text/html; charset=utf-8"),
            "/meals": ("meals.html", "text/html; charset=utf-8"),
            "/meals/": ("meals.html", "text/html; charset=utf-8"),
            "/groceries": ("groceries.html", "text/html; charset=utf-8"),
            "/groceries/": ("groceries.html", "text/html; charset=utf-8"),
            "/recipes": ("recipes.html", "text/html; charset=utf-8"),
            "/recipes/": ("recipes.html", "text/html; charset=utf-8"),
            "/nav.js": ("nav.js", "text/javascript; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/section.js": ("section.js", "text/javascript; charset=utf-8"),
            "/meals.js": ("meals.js", "text/javascript; charset=utf-8"),
            "/groceries.js": ("groceries.js", "text/javascript; charset=utf-8"),
            "/recipes.js": ("recipes.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/favicon.svg": ("favicon.svg", "image/svg+xml"),
        }
        asset = assets.get(parsed.path)
        if asset:
            filename, content_type = asset
            content = (_DASHBOARD_DIR / filename).read_bytes()
            self._send_bytes(content, content_type, cache_control="no-cache")
            return

        self.send_error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        except (ValueError, json.JSONDecodeError):
            self._send_json({"error": "invalid JSON"}, status=400)
            return

        try:
            recipe_parts = parsed.path.strip("/").split("/")
            if parsed.path == "/api/groceries/budget":
                budget = self.server.store.set_weekly_budget(float(payload["budget"]), str(payload.get("updated_by", "grant")))
                snapshot = self.server.store.grocery_budget_snapshot()
                snapshot["budget"] = budget
                self._send_json(snapshot)
                return

            if parsed.path == "/api/groceries/price":
                item = self.server.store.set_grocery_price(
                    int(payload["item_id"]), float(payload["price"]),
                    str(payload.get("source", "Manual entry")), payload.get("url") or None,
                    str(payload.get("confidence", "manual")),
                    str(payload.get("checked_at", self.server.now().date().isoformat())),
                    str(payload.get("note", "Entered by household")),
                )
                self._send_json({"item": item})
                return

            if parsed.path == "/api/groceries/item":
                item = self.server.store.update_grocery_item(
                    int(payload["item_id"]), quantity=payload.get("quantity"),
                    unit=payload.get("unit"), category=payload.get("category"),
                )
                self._send_json({"item": item})
                return

            if parsed.path == "/api/groceries/refresh-coles":
                updated = apply_known_coles_prices(self.server.store)
                self._send_json({"updated": updated, **self.server.store.grocery_budget_snapshot()})
                return
            if len(recipe_parts) == 3 and recipe_parts[:2] == ["api", "recipes"] and recipe_parts[2] == "import":
                title = str(payload.get("title", "")).strip()
                source_url = str(payload.get("source_url", "user://recipe")).strip()
                image_url = str(payload.get("image_url", "")).strip()
                if not title:
                    raise ValueError("title is required")
                if not (source_url.startswith("https://") or source_url.startswith("http://") or source_url.startswith("user://")):
                    raise ValueError("source_url must use http(s) or user://")
                if image_url and not (image_url.startswith("https://") or image_url.startswith("http://") or image_url.startswith("/recipe-images/")):
                    raise ValueError("image_url must use http(s) or /recipe-images/")
                ingredients = [
                    {
                        "name": str(item.get("name", "")).strip(),
                        "quantity": str(item.get("quantity", "")).strip(),
                        "unit": str(item.get("unit", "")).strip(),
                    }
                    for item in payload.get("ingredients", [])
                    if isinstance(item, dict) and str(item.get("name", "")).strip()
                ]
                grocery_indexes_payload = payload.get("grocery_ingredient_indexes")
                grocery_indexes = None
                if grocery_indexes_payload is not None:
                    if not isinstance(grocery_indexes_payload, list):
                        raise ValueError("grocery_ingredient_indexes must be a list")
                    try:
                        grocery_indexes = [int(index) for index in grocery_indexes_payload]
                    except (TypeError, ValueError) as error:
                        raise ValueError("grocery_ingredient_indexes must contain integers") from error
                recipe_id = self.server.store.add_recipe(
                    "user_supplied", "user_supplied", title, source_url,
                    image_url=image_url or None,
                    summary=str(payload.get("summary", "")).strip(),
                    tags=[str(tag).strip() for tag in payload.get("tags", []) if str(tag).strip()],
                    prep_minutes=payload.get("prep_minutes"),
                    cook_minutes=payload.get("cook_minutes"),
                    ingredients=ingredients,
                )
                added = []
                if grocery_indexes is not None:
                    added = self.server.store.add_recipe_ingredients_to_groceries(
                        recipe_id, str(payload.get("created_by", "grant")), grocery_indexes,
                    )
                recipe = next(item for item in self.server.store.list_recipes() if item["id"] == recipe_id)
                self._send_json({"recipe": recipe, "added": added}, status=201)
                return

            if len(recipe_parts) == 4 and recipe_parts[:2] == ["api", "recipes"]:
                recipe_id = int(recipe_parts[2])
                action = recipe_parts[3]
                if action == "save":
                    saved = bool(payload.get("saved", True))
                    saved_by = str(payload.get("saved_by", "grant"))
                    self.server.store.set_recipe_saved(recipe_id, saved_by, saved)
                    self._send_json({"saved": saved})
                    return
                if action == "plan":
                    meal_date = str(payload.get("meal_date", "")).strip()
                    if not meal_date:
                        raise ValueError("meal_date is required")
                    grocery_indexes = None
                    grocery_indexes_payload = payload.get("grocery_ingredient_indexes")
                    if grocery_indexes_payload is not None:
                        if not isinstance(grocery_indexes_payload, list):
                            raise ValueError("grocery_ingredient_indexes must be a list")
                        try:
                            grocery_indexes = [int(index) for index in grocery_indexes_payload]
                        except (TypeError, ValueError) as error:
                            raise ValueError("grocery_ingredient_indexes must contain integers") from error
                        recipe = next(item for item in self.server.store.list_recipes() if item["id"] == recipe_id)
                        if any(index < 0 or index >= len(recipe["ingredients"]) for index in grocery_indexes):
                            raise ValueError("ingredient index is out of range")
                    meal_id = self.server.store.plan_recipe(
                        recipe_id, meal_date, str(payload.get("meal_type", "dinner")),
                        payload.get("cook") or None, str(payload.get("created_by", "grant")),
                    )
                    added = []
                    if grocery_indexes is not None:
                        added = self.server.store.add_recipe_ingredients_to_groceries(
                            recipe_id, str(payload.get("created_by", "grant")), grocery_indexes,
                        )
                    meal = next(item for item in self.server.store.list_meals() if item["id"] == meal_id)
                    meal["cook_label"] = assignee_label(meal.get("cook"))
                    self._send_json({"meal": meal, "added": added}, status=201)
                    return
                if action == "shopping-list":
                    if payload.get("meal_id"):
                        added = self.server.store.add_meal_ingredients_to_groceries(
                            int(payload["meal_id"]), str(payload.get("created_by", "grant")),
                        )
                    else:
                        added = self.server.store.add_recipe_ingredients_to_groceries(
                            recipe_id, str(payload.get("created_by", "grant")),
                        )
                    self._send_json({"added": added})
                    return

            if parsed.path.startswith("/api/tasks/"):
                route_parts = parsed.path.removeprefix("/api/tasks/").strip("/").split("/")
                if len(route_parts) != 2 or not route_parts[0].isdigit() or route_parts[1] not in {"complete", "delete"}:
                    self._send_json({"error": "not found"}, status=404)
                    return
                task_id = int(route_parts[0])
                if route_parts[1] == "complete":
                    task = self.server.store.complete_task(task_id)
                    self._send_json({"task": task})
                else:
                    self.server.store.delete_task(task_id)
                    self._send_json({"deleted": task_id})
                return

            if parsed.path == "/api/tasks":
                title = str(payload.get("title", "")).strip()
                if not title:
                    raise ValueError("title is required")
                due_at = str(payload.get("due_at", "")).strip() or None
                recurrence = normalize_recurrence(payload.get("recurrence"))
                if payload.get("id"):
                    task = self.server.store.update_task(
                        int(payload["id"]), title, due_at, payload.get("assignee"), recurrence,
                    )
                    self._send_json({"task": task})
                else:
                    task_id = self.server.store.add_task(
                        title,
                        due_at,
                        None,
                        False,
                        str(payload.get("created_by", "grant")),
                        assignee=payload.get("assignee"),
                        recurrence=recurrence,
                    )
                    task = next(item for item in self.server.store.list_tasks() if item["id"] == task_id)
                    self._send_json({"task": task}, status=201)
                return

            if parsed.path == "/api/calendar":
                title = str(payload.get("title", "")).strip()
                starts_at = str(payload.get("starts_at", "")).strip()
                if not title or not starts_at:
                    raise ValueError("title and starts_at are required")
                if payload.get("id"):
                    event = self.server.store.update_event(
                        int(payload["id"]), title, starts_at, payload.get("person") or None, payload.get("assignee"),
                    )
                    self._send_json({"event": event})
                else:
                    event_id = self.server.store.add_event(
                        title, starts_at, payload.get("person") or None,
                        str(payload.get("created_by", "grant")), assignee=payload.get("assignee"),
                    )
                    event = next(item for item in self.server.store.list_events() if item["id"] == event_id)
                    self._send_json({"event": event}, status=201)
                return

            if parsed.path == "/api/meals":
                title = str(payload.get("title", "")).strip()
                meal_date = str(payload.get("meal_date", "")).strip()
                meal_type = str(payload.get("meal_type", "dinner")).strip().lower()
                if not title or not meal_date:
                    raise ValueError("title and meal_date are required")
                ingredients = [str(item).strip().lower() for item in payload.get("ingredients", []) if str(item).strip()]
                if payload.get("id"):
                    meal = self.server.store.update_meal(
                        int(payload["id"]), meal_date, meal_type, title, payload.get("cook") or None, ingredients,
                    )
                    meal["cook_label"] = assignee_label(meal.get("cook"))
                    self._send_json({"meal": meal})
                else:
                    meal_id = self.server.store.add_meal(
                        meal_date, meal_type, title, payload.get("cook") or None,
                        ingredients, str(payload.get("created_by", "grant")),
                    )
                    meal = next(item for item in self.server.store.list_meals() if item["id"] == meal_id)
                    meal["cook_label"] = assignee_label(meal.get("cook"))
                    self._send_json({"meal": meal}, status=201)
                return

            if parsed.path == "/api/meals/sync-groceries":
                added = self.server.store.add_meal_ingredients_to_groceries(
                    int(payload["meal_id"]), str(payload.get("created_by", "grant")),
                )
                self._send_json({"added": added})
                return

            if parsed.path.startswith("/api/meals/"):
                route_parts = parsed.path.removeprefix("/api/meals/").strip("/").split("/")
                if len(route_parts) != 2 or not route_parts[0].isdigit() or route_parts[1] != "delete":
                    self._send_json({"error": "not found"}, status=404)
                    return
                meal_id = int(route_parts[0])
                self.server.store.delete_meal(meal_id)
                self._send_json({"deleted": meal_id})
                return

            self._send_json({"error": "not found"}, status=404)
        except (KeyError, TypeError, ValueError, StopIteration) as error:
            self._send_json({"error": str(error)}, status=400)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        self._send_bytes(
            json.dumps(payload).encode("utf-8"),
            "application/json; charset=utf-8",
            cache_control="no-store",
            status=status,
        )

    def _send_bytes(self, content: bytes, content_type: str, cache_control: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args) -> None:
        return


class DashboardServer(ThreadingHTTPServer):
    """Local dashboard server with an injected store and clock for testing."""

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        store: PlannerStore,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.now = now or local_now
        super().__init__(server_address, DashboardRequestHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Hearthstate dashboard.")
    parser.add_argument(
        "--database",
        default=os.environ.get("HEARTHSTATE_DB", os.environ.get("FAMILY_PLANNER_DB", "family_planner.db")),
        help="SQLite database path (default: HEARTHSTATE_DB or family_planner.db)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8788, type=int)
    args = parser.parse_args()

    store = PlannerStore(args.database)
    server = DashboardServer((args.host, args.port), store=store)
    print(f"Hearthstate dashboard: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
