from __future__ import annotations

import argparse
import calendar
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .accounts import HouseholdDirectory
from .conflicts import detect_conflicts
from .pricing import apply_known_coles_prices
from .store import TASK_RECURRENCES, PlannerStore, assignee_label, normalize_assignee, normalize_recurrence
from .timezone import local_now


_DASHBOARD_DIR = Path(__file__).with_name("dashboard")
_MAX_INBOX_ACTOR_LENGTH = 120
_MAX_INBOX_SOURCE_LENGTH = 80
_SESSION_COOKIE = "HearthstateSession"
_SESSION_MAX_AGE = 12 * 60 * 60
HOUSEHOLD_USERS = {
    "grant": {"name": "Grant", "role": "Household admin", "image": "/user-images/grant.png"},
    "billie": {"name": "Billie", "role": "Household member", "image": "/user-images/billie.png"},
    "skye": {"name": "Skye", "role": "Household member", "image": "/user-images/skye.png"},
}


def _inbox_actor(payload: dict, field: str = "created_by", *, default: str | None = None) -> str:
    if field not in payload and default is None:
        raise ValueError(f"{field} is required")
    value = str(payload.get(field, default) or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    if len(value) > _MAX_INBOX_ACTOR_LENGTH:
        raise ValueError(f"{field} is too long")
    return value


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
                "ends_at": event.get("ends_at"),
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
    inbox_items = store.list_inbox_items(viewer=viewer)
    attention_items = _connected_attention(attention, [
        meal for meal in store.list_meals(
            start_date=current.date().isoformat(),
            end_date=(current + timedelta(days=6)).date().isoformat(),
        )
    ], grocery_summary, current)
    planning_week = _planning_week(current, calendar_items, meal_items)
    conflicts = detect_conflicts(store)

    return {
        "viewer": viewer,
        "viewer_name": HOUSEHOLD_USERS.get(viewer, {"name": viewer.title()})["name"],
        "viewer_role": HOUSEHOLD_USERS.get(viewer, {"role": "Household member"})["role"],
        "generated_at": current.isoformat(),
        "counts": {
            "attention": len(attention),
            "today_events": len(today),
            "groceries": len(store.list_grocery_items()),
            "inbox": len(inbox_items),
        },
        "attention": attention[:8],
        "attention_items": attention_items,
        "tasks": attention,
        "today": today,
        "today_items": today_items,
        "upcoming": upcoming[:8],
        "planning_week": planning_week,
        "conflicts": conflicts,
        "calendar": calendar_items,
        "grocery_summary": grocery_summary,
        "inbox": inbox_items[:12],
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
        if parsed.path == "/" and not self.server.session_user(self.headers):
            self._send_asset("login.html", "text/html; charset=utf-8")
            return
        protected_pages = {"/index.html", "/admin", "/admin/", "/notifications", "/notifications/", "/calendar", "/calendar/", "/tasks", "/tasks/", "/meals", "/meals/", "/groceries", "/groceries/", "/recipes", "/recipes/"}
        if parsed.path in {"/admin", "/admin/"}:
            actor = self.server.session_user(self.headers)
            if actor is None:
                self._send_redirect("/login")
                return
            if self.server.accounts is None or self.server.accounts.role_for(actor, self.server.store.household_id) != "owner":
                self._send_redirect("/")
                return
        if parsed.path in protected_pages and not self.server.session_user(self.headers):
            self._send_redirect("/login")
            return
        if parsed.path == "/health":
            try:
                health = self.server.store.health_check()
                status = 200 if health["database"] == "ok" else 503
                self._send_json({"status": "ok" if status == 200 else "degraded", "service": "hearthstate", **health}, status=status)
            except sqlite3.Error:
                self._send_json({"status": "degraded", "service": "hearthstate", "database": "unavailable"}, status=503)
            return
        if parsed.path == "/api/auth/config":
            self._send_json({"account_backed": self.server.accounts is not None})
            return
        if parsed.path == "/api/auth/invitations/inspect":
            if self.server.accounts is None:
                self._send_json({"error": "account directory unavailable"}, status=503)
                return
            token = parse_qs(parsed.query).get("token", [""])[0]
            try:
                invitation = self.server.accounts.inspect_invitation(token, now=self.server.now())
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            for key in ("id", "invited_by", "accepted_at", "accepted_account_id", "created_at"):
                invitation.pop(key, None)
            self._send_json({"invitation": invitation})
            return
        if self.server.accounts is not None and parsed.path.startswith("/api/") and not self.server.session_user(self.headers):
            self._send_json({"error": "authentication required"}, status=401)
            return
        if parsed.path == "/api/notifications/preferences":
            actor = self.server.session_user(self.headers)
            if actor is None:
                self._send_json({"error": "authentication required"}, status=401)
                return
            briefing_type = parse_qs(parsed.query).get("briefing_type", ["morning"])[0].strip().lower() or "morning"
            try:
                self._send_json({"preferences": self.server.store.get_notification_preferences(actor, briefing_type)})
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/admin":
            actor = self.server.session_user(self.headers)
            if self.server.accounts is None:
                self._send_json({"error": "account directory unavailable"}, status=404)
                return
            if actor is None:
                self._send_json({"error": "authentication required"}, status=401)
                return
            if self.server.accounts.role_for(actor, self.server.store.household_id) != "owner":
                self._send_json({"error": "owner access required"}, status=403)
                return
            self._send_json({
                "household": self.server.accounts.get_household(self.server.store.household_id),
                "members": self.server.accounts.list_members(self.server.store.household_id),
                "invitations": self.server.accounts.list_invitations(self.server.store.household_id, now=self.server.now()),
            })
            return
        if parsed.path == "/api/inbox":
            viewer = self.server.session_user(self.headers) or parse_qs(parsed.query).get("viewer", ["you"])[0].strip() or "you"
            items = self.server.store.list_inbox_items(viewer=viewer)
            self._send_json({"viewer": viewer, "items": items, "generated_at": self.server.now().replace(second=0, microsecond=0).isoformat()})
            return
        if parsed.path == "/api/activity":
            viewer = self.server.session_user(self.headers) or parse_qs(parsed.query).get("viewer", ["you"])[0].strip() or "you"
            self._send_json({"viewer": viewer, "activity": self.server.store.list_activity(viewer=viewer)})
            return
        if parsed.path == "/api/conflicts":
            self._send_json({"conflicts": detect_conflicts(self.server.store)})
            return
        if parsed.path == "/api/chores":
            self._send_json({"chores": self.server.store.list_chores()})
            return
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
            viewer = self.server.session_user(self.headers) or parse_qs(parsed.query).get("viewer", ["you"])[0].strip() or "you"
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

        if parsed.path.startswith("/user-images/"):
            requested = parsed.path.removeprefix("/user-images/")
            filename = Path(requested).name
            image_path = _DASHBOARD_DIR / "user-images" / filename
            if requested != filename or filename not in {"grant.png", "billie.png", "skye.png"} or not image_path.is_file():
                self.send_error(404, "Image not found")
                return
            self._send_bytes(image_path.read_bytes(), "image/png", cache_control="public, max-age=86400")
            return

        assets = {
            "/login": ("login.html", "text/html; charset=utf-8"),
            "/login.js": ("login.js", "text/javascript; charset=utf-8"),
            "/invite": ("invite.html", "text/html; charset=utf-8"),
            "/invite.js": ("invite.js", "text/javascript; charset=utf-8"),
            "/admin": ("admin.html", "text/html; charset=utf-8"),
            "/admin/": ("admin.html", "text/html; charset=utf-8"),
            "/admin.js": ("admin.js", "text/javascript; charset=utf-8"),
            "/notifications": ("notifications.html", "text/html; charset=utf-8"),
            "/notifications/": ("notifications.html", "text/html; charset=utf-8"),
            "/notifications.js": ("notifications.js", "text/javascript; charset=utf-8"),
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
        if not isinstance(payload, dict):
            self._send_json({"error": "JSON object required"}, status=400)
            return

        try:
            recipe_parts = parsed.path.strip("/").split("/")
            actor = self.server.session_user(self.headers)
            if self.server.accounts is not None and actor is None and parsed.path.startswith("/api/") and parsed.path not in {"/api/session", "/api/auth/invitations/accept", "/api/auth/sign-in/request", "/api/auth/sign-in"}:
                self._send_json({"error": "authentication required"}, status=401)
                return
            if parsed.path == "/api/session":
                if self.server.accounts is not None:
                    raise ValueError("passwordless chooser is disabled for account-backed households")
                user = str(payload.get("user", "")).strip().lower()
                if user not in HOUSEHOLD_USERS:
                    raise ValueError("unknown household user")
                session_payload = {"user": user, "name": HOUSEHOLD_USERS[user]["name"]}
                token = self.server.create_session(user)
                self._send_json(
                    session_payload,
                    headers={"Set-Cookie": f"{_SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={_SESSION_MAX_AGE}"},
                )
                return
            if parsed.path == "/api/auth/invitations":
                if self.server.accounts is None or actor is None:
                    raise ValueError("authenticated account required")
                household_id = self.server.session_household(self.headers) or self.server.accounts.household_for(actor)
                if household_id is None or self.server.store.household_id != household_id:
                    raise ValueError("household context unavailable")
                invitation = self.server.accounts.create_invitation(
                    household_id,
                    str(payload.get("email", "")),
                    str(payload.get("role", "member")),
                    actor,
                    now=self.server.now(),
                )
                invitation["url"] = f"/invite?token={invitation['token']}"
                if self.server.invitation_delivery is not None:
                    try:
                        self.server.invitation_delivery(invitation)
                    except OSError:
                        self._send_json({"error": "invitation delivery unavailable"}, status=503)
                        return
                self._send_json({"invitation": invitation}, status=201)
                return
            if parsed.path == "/api/auth/invitations/accept":
                if self.server.accounts is None:
                    raise ValueError("account directory unavailable")
                invitation = self.server.accounts.inspect_invitation(str(payload.get("token", "")), now=self.server.now())
                if invitation["household_id"] != self.server.store.household_id:
                    raise ValueError("household context unavailable")
                accepted = self.server.accounts.accept_invitation(
                    str(payload.get("token", "")),
                    str(payload.get("display_name", "")),
                    now=self.server.now(),
                )
                if accepted["household_id"] != self.server.store.household_id:
                    raise ValueError("household context unavailable")
                token = self.server.create_session(accepted["account_id"], accepted["household_id"])
                self._send_json(
                    {"session": {"user": accepted["account_id"], "name": accepted["display_name"], "household_id": accepted["household_id"], "role": accepted["role"]}},
                    status=201,
                    headers={"Set-Cookie": f"{_SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={_SESSION_MAX_AGE}"},
                )
                return
            if parsed.path == "/api/auth/sign-in/request":
                if self.server.accounts is not None:
                    try:
                        issued = self.server.accounts.create_sign_in_token(
                            str(payload.get("email", "")),
                            household_id=self.server.store.household_id,
                            now=self.server.now(),
                        )
                        if self.server.sign_in_delivery is not None:
                            self.server.sign_in_delivery({
                                **issued,
                                "url": f"/login?token={issued['token']}",
                            })
                    except OSError:
                        self._send_json({"error": "sign-in delivery unavailable"}, status=503)
                        return
                    except ValueError:
                        pass
                self._send_json({"sent": True}, status=202)
                return
            if parsed.path == "/api/auth/sign-in":
                if self.server.accounts is None:
                    raise ValueError("account directory unavailable")
                pending = self.server.accounts.inspect_sign_in_token(str(payload.get("token", "")), now=self.server.now())
                if pending["household_id"] != self.server.store.household_id:
                    raise ValueError("household context unavailable")
                signed_in = self.server.accounts.consume_sign_in_token(str(payload.get("token", "")), now=self.server.now())
                if signed_in["household_id"] != self.server.store.household_id:
                    raise ValueError("household context unavailable")
                token = self.server.create_session(signed_in["account_id"], signed_in["household_id"])
                self._send_json(
                    {"session": {"user": signed_in["account_id"], "name": signed_in["display_name"], "household_id": signed_in["household_id"], "role": signed_in["role"]}},
                    headers={"Set-Cookie": f"{_SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={_SESSION_MAX_AGE}"},
                )
                return
            if parsed.path == "/api/notifications/preferences":
                if actor is None:
                    raise ValueError("authentication required")
                allowed = {"briefing_type", "enabled", "preferred_time", "quiet_start", "quiet_end", "channel"}
                if set(payload) - allowed:
                    raise ValueError("unsupported notification preference field")
                briefing_type = str(payload.get("briefing_type", "morning")).strip().lower() or "morning"
                values = {
                    key: payload[key]
                    for key in ("enabled", "preferred_time", "quiet_start", "quiet_end", "channel")
                    if key in payload
                }
                preferences = self.server.store.set_notification_preferences(
                    actor,
                    briefing_type=briefing_type,
                    updated_by=actor,
                    **values,
                )
                self._send_json({"preferences": preferences})
                return
            if parsed.path.startswith("/api/admin"):
                if self.server.accounts is None:
                    self._send_json({"error": "account directory unavailable"}, status=404)
                    return
                if actor is None:
                    self._send_json({"error": "authentication required"}, status=401)
                    return
                household_id = self.server.store.household_id
                if self.server.accounts.role_for(actor, household_id) != "owner":
                    self._send_json({"error": "owner access required"}, status=403)
                    return
                if parsed.path == "/api/admin/household":
                    household = self.server.accounts.update_household(household_id, str(payload.get("name", "")), actor)
                    self._send_json({"household": household})
                    return
                member_parts = parsed.path.removeprefix("/api/admin/members/").strip("/").split("/")
                if parsed.path.startswith("/api/admin/members/"):
                    if len(member_parts) == 2 and member_parts[1] == "remove":
                        member = self.server.accounts.remove_member(household_id, member_parts[0], actor)
                        self._send_json({"member": member})
                        return
                    if len(member_parts) == 1:
                        member = self.server.accounts.update_member_role(
                            household_id, member_parts[0], str(payload.get("role", "")), actor,
                        )
                        self._send_json({"member": member})
                        return
                invitation_parts = parsed.path.removeprefix("/api/admin/invitations/").strip("/").split("/")
                if len(invitation_parts) == 2 and invitation_parts[1] == "revoke" and invitation_parts[0].isdigit():
                    invitation_id = int(invitation_parts[0])
                    if not 1 <= invitation_id <= 9223372036854775807:
                        raise ValueError("invalid invitation id")
                    invitation = self.server.accounts.revoke_invitation(
                        household_id, invitation_id, actor, now=self.server.now(),
                    )
                    self._send_json({"invitation": invitation})
                    return
                self._send_json({"error": "not found"}, status=404)
                return
            if parsed.path == "/api/inbox":
                created_by = actor or _inbox_actor(payload)
                source = str(payload.get("source", "dashboard") or "dashboard").strip()
                if len(source) > _MAX_INBOX_SOURCE_LENGTH:
                    raise ValueError("source is too long")
                private = payload.get("private", False)
                if not isinstance(private, bool):
                    raise ValueError("private must be a boolean")
                item_id = self.server.store.add_inbox_item(
                    str(payload.get("original_text", "")),
                    created_by,
                    source=source,
                    private=private,
                )
                item = self.server.store.get_inbox_item(item_id, include_closed=True)
                self._send_json({"item": item}, status=201)
                return

            if parsed.path.startswith("/api/inbox/"):
                route_parts = parsed.path.removeprefix("/api/inbox/").strip("/").split("/")
                if len(route_parts) != 2 or not route_parts[0].isdigit() or route_parts[1] not in {"archive", "convert"}:
                    self._send_json({"error": "not found"}, status=404)
                    return
                item_id = int(route_parts[0])
                viewer = actor or str(payload.get("viewer", payload.get("created_by", "you"))).strip() or "you"
                self.server.store.get_inbox_item(item_id, viewer=viewer)
                if route_parts[1] == "archive":
                    item = self.server.store.archive_inbox_item(item_id)
                    self._send_json({"item": item})
                    return
                converted_type = str(payload.get("type", "")).strip().lower()
                created_by = actor or str(payload.get("created_by", viewer)).strip() or viewer
                result = self.server.store.convert_inbox_item(
                    item_id,
                    converted_type,
                    payload,
                    created_by=created_by,
                )
                item = self.server.store.get_inbox_item(item_id, viewer=viewer, include_closed=True)
                self._send_json({converted_type: result, "item": item}, status=201)
                return

            if parsed.path == "/api/activity/undo":
                undo = self.server.store.undo_last(actor or str(payload.get("viewer", "you")))
                self._send_json({"undone": undo})
                return
            if parsed.path == "/api/chores":
                title = str(payload.get("title", "")).strip()
                participants = payload.get("participants", [])
                if not isinstance(participants, list):
                    raise ValueError("participants must be a list")
                chore_id = self.server.store.add_chore(title, str(payload.get("cadence", "weekly")), participants, actor or str(payload.get("created_by", "grant")))
                self._send_json({"chore": next(item for item in self.server.store.list_chores() if item["id"] == chore_id)}, status=201)
                return
            if parsed.path.startswith("/api/chores/"):
                route_parts = parsed.path.removeprefix("/api/chores/").strip("/").split("/")
                if len(route_parts) != 1 or not route_parts[0].isdigit():
                    self._send_json({"error": "not found"}, status=404)
                    return
                chore_id = int(route_parts[0])
                task = self.server.store.assign_next_chore(chore_id, str(payload["due_date"]), actor or str(payload.get("created_by", "grant")))
                self._send_json({"task": task}, status=201)
                return
            if parsed.path == "/api/groceries/budget":
                budget = self.server.store.set_weekly_budget(float(payload["budget"]), actor or str(payload.get("updated_by", "grant")))
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
                        recipe_id, actor or str(payload.get("created_by", "grant")), grocery_indexes,
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
                        payload.get("cook") or None, actor or str(payload.get("created_by", "grant")),
                    )
                    added = []
                    if grocery_indexes is not None:
                        added = self.server.store.add_recipe_ingredients_to_groceries(
                            recipe_id, actor or str(payload.get("created_by", "grant")), grocery_indexes,
                        )
                    meal = next(item for item in self.server.store.list_meals() if item["id"] == meal_id)
                    meal["cook_label"] = assignee_label(meal.get("cook"))
                    self._send_json({"meal": meal, "added": added}, status=201)
                    return
                if action == "shopping-list":
                    if payload.get("meal_id"):
                        added = self.server.store.add_meal_ingredients_to_groceries(
                            int(payload["meal_id"]), actor or str(payload.get("created_by", "grant")),
                        )
                    else:
                        added = self.server.store.add_recipe_ingredients_to_groceries(
                            recipe_id, actor or str(payload.get("created_by", "grant")),
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
                    task = self.server.store.complete_task(task_id, actor=actor)
                    self._send_json({"task": task})
                else:
                    self.server.store.delete_task(task_id, actor=actor)
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
                        int(payload["id"]), title, due_at, payload.get("assignee"), recurrence, actor=actor,
                    )
                    self._send_json({"task": task})
                else:
                    task_id = self.server.store.add_task(
                        title,
                        due_at,
                        None,
                        False,
                        actor or str(payload.get("created_by", "grant")),
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
                        ends_at=str(payload.get("ends_at", "")).strip() or None, actor=actor,
                    )
                    self._send_json({"event": event})
                else:
                    event_id = self.server.store.add_event(
                        title, starts_at, payload.get("person") or None,
                        actor or str(payload.get("created_by", "grant")), assignee=payload.get("assignee"),
                        ends_at=str(payload.get("ends_at", "")).strip() or None, actor=actor,
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
                        int(payload["id"]), meal_date, meal_type, title, payload.get("cook") or None, ingredients, actor=actor,
                    )
                    meal["cook_label"] = assignee_label(meal.get("cook"))
                    self._send_json({"meal": meal})
                else:
                    meal_id = self.server.store.add_meal(
                        meal_date, meal_type, title, payload.get("cook") or None,
                        ingredients, actor or str(payload.get("created_by", "grant")), actor=actor,
                    )
                    meal = next(item for item in self.server.store.list_meals() if item["id"] == meal_id)
                    meal["cook_label"] = assignee_label(meal.get("cook"))
                    self._send_json({"meal": meal}, status=201)
                return

            if parsed.path == "/api/meals/sync-groceries":
                added = self.server.store.add_meal_ingredients_to_groceries(
                    int(payload["meal_id"]), actor or str(payload.get("created_by", "grant")),
                )
                self._send_json({"added": added})
                return

            if parsed.path.startswith("/api/meals/"):
                route_parts = parsed.path.removeprefix("/api/meals/").strip("/").split("/")
                if len(route_parts) != 2 or not route_parts[0].isdigit() or route_parts[1] != "delete":
                    self._send_json({"error": "not found"}, status=404)
                    return
                meal_id = int(route_parts[0])
                self.server.store.delete_meal(meal_id, actor=actor)
                self._send_json({"deleted": meal_id})
                return

            self._send_json({"error": "not found"}, status=404)
        except (KeyError, TypeError, ValueError, StopIteration) as error:
            self._send_json({"error": str(error)}, status=400)

    def _send_asset(self, filename: str, content_type: str) -> None:
        self._send_bytes((_DASHBOARD_DIR / filename).read_bytes(), content_type, cache_control="no-cache")

    def _send_redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, payload: dict, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self._send_bytes(
            json.dumps(payload).encode("utf-8"),
            "application/json; charset=utf-8",
            cache_control="no-store",
            status=status,
            headers=headers,
        )

    def _send_bytes(
        self,
        content: bytes,
        content_type: str,
        cache_control: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
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
        accounts: HouseholdDirectory | None = None,
        sign_in_delivery: Callable[[dict[str, str]], None] | None = None,
        invitation_delivery: Callable[[dict[str, str]], None] | None = None,
    ) -> None:
        self.store = store
        self.accounts = accounts
        self.sign_in_delivery = sign_in_delivery
        self.invitation_delivery = invitation_delivery
        self.now = now or local_now
        self.sessions: dict[str, tuple[str, float, str | None]] = {}
        self.session_lock = threading.Lock()
        super().__init__(server_address, DashboardRequestHandler)

    def create_session(self, user: str, household_id: str | None = None) -> str:
        token = secrets.token_urlsafe(32)
        with self.session_lock:
            self.sessions[token] = (user, time.time(), household_id)
        return token

    def session_user(self, headers) -> str | None:
        cookie = SimpleCookie()
        cookie.load(headers.get("Cookie", ""))
        token = cookie.get(_SESSION_COOKIE)
        if token is None:
            return None
        with self.session_lock:
            session = self.sessions.get(token.value)
            if session is None:
                return None
            user, created_at, household_id = session
            if time.time() - created_at > _SESSION_MAX_AGE:
                self.sessions.pop(token.value, None)
                return None
        if self.accounts is not None:
            if household_id != self.store.household_id or not self.accounts.can_access(user, self.store.household_id):
                with self.session_lock:
                    self.sessions.pop(token.value, None)
                return None
        return user

    def session_household(self, headers) -> str | None:
        if self.session_user(headers) is None:
            return None
        cookie = SimpleCookie()
        cookie.load(headers.get("Cookie", ""))
        token = cookie.get(_SESSION_COOKIE)
        if token is None:
            return None
        with self.session_lock:
            session = self.sessions.get(token.value)
            return session[2] if session is not None else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Hearthstate dashboard.")
    parser.add_argument(
        "--database",
        default=os.environ.get("HEARTHSTATE_DB", "hearthstate.db"),
        help="SQLite database path (default: HEARTHSTATE_DB or hearthstate.db)",
    )
    parser.add_argument(
        "--accounts-database",
        default=os.environ.get("HEARTHSTATE_ACCOUNTS_DB"),
        help="Account/household SQLite path; enables account-backed auth when combined with --household-id",
    )
    parser.add_argument(
        "--household-id",
        default=os.environ.get("HEARTHSTATE_HOUSEHOLD_ID"),
        help="Named household context for account-backed auth",
    )
    parser.add_argument(
        "--agentmail",
        action="store_true",
        default=os.environ.get("HEARTHSTATE_AGENTMAIL_ENABLED", "").lower() in {"1", "true", "yes"},
        help="Send invitation and sign-in links through AgentMail",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8788, type=int)
    args = parser.parse_args()

    if bool(args.accounts_database) != bool(args.household_id):
        parser.error("--accounts-database and --household-id must be supplied together")
    accounts = HouseholdDirectory(args.accounts_database) if args.accounts_database else None
    store = PlannerStore(args.database, household_id=args.household_id or "default")
    sign_in_delivery = None
    invitation_delivery = None
    if args.agentmail:
        if accounts is None:
            parser.error("--agentmail requires account-backed mode")
        from .agentmail import send_invitation_email, send_sign_in_email

        sign_in_delivery = send_sign_in_email
        invitation_delivery = send_invitation_email
    server = DashboardServer(
        (args.host, args.port),
        store=store,
        accounts=accounts,
        sign_in_delivery=sign_in_delivery,
        invitation_delivery=invitation_delivery,
    )
    print(f"Hearthstate dashboard: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()
        if accounts is not None:
            accounts.close()


if __name__ == "__main__":
    main()
