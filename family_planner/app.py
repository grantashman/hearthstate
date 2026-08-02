from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Callable

from .store import HOUSEHOLD_MEMBERS, PlannerStore, assignee_label, normalize_assignee
from .timezone import local_now


_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class FamilyPlanner:
    """Translate a small set of natural-language messages into planner actions."""

    def __init__(self, store: PlannerStore, now: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.now = now or local_now

    def handle_message(self, sender: str, message: str) -> str:
        text = " ".join(message.strip().split())
        lowered = text.lower()

        if lowered in {"what needs attention?", "what needs attention", "family state"}:
            return self._family_state(sender)

        task_query = re.fullmatch(
            r"(?:what|show) (?:are )?(?:the )?tasks?(?: are)?(?: assigned to| for) (grant|billie|skye|all)\??",
            lowered,
            flags=re.IGNORECASE,
        )
        if task_query:
            return self._task_query(normalize_assignee(task_query.group(1)))

        calendar_query = re.fullmatch(
            r"(?:what(?:'s| is)|show) (?:on )?(?:the )?calendar(?: for| assigned to) (grant|billie|skye|all)\??",
            lowered,
            flags=re.IGNORECASE,
        )
        if calendar_query:
            return self._calendar_query(normalize_assignee(calendar_query.group(1)))

        meal_query = re.fullmatch(
            r"what(?:'s| is) for (breakfast|lunch|dinner) (today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\??",
            lowered,
            flags=re.IGNORECASE,
        )
        if meal_query:
            meal_date = self._parse_day_date(meal_query.group(2)).isoformat()
            meals = [meal for meal in self.store.list_meals(meal_date, meal_date) if meal["meal_type"] == meal_query.group(1).lower()]
            if not meals:
                return f"No {meal_query.group(1).lower()} planned for {meal_query.group(2).lower()}."
            return "\n".join(
                [f"{meal_query.group(1).capitalize()} for {meal_query.group(2).lower()}:" ]
                + [f"{meal['title']} — cooking: {assignee_label(meal['cook'])}. Ingredients: {', '.join(meal['ingredients']) or 'none listed'}." for meal in meals]
            )

        meal_match = re.fullmatch(
            r"add (.+?) to the meal plan (today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
            r"(?: for (grant|billie|skye|all))?(?: with ingredients (.+))?",
            text,
            flags=re.IGNORECASE,
        )
        if meal_match:
            title = self._clean_name(meal_match.group(1))
            meal_date = self._parse_day_date(meal_match.group(2)).isoformat()
            cook = normalize_assignee(meal_match.group(3))
            ingredients = [
                self._clean_name(part)
                for part in re.split(r"\s*,\s*|\s+and\s+", meal_match.group(4) or "")
                if part.strip()
            ]
            meal_id = self.store.add_meal(meal_date, "dinner", title, cook, ingredients, sender)
            suffix = f" for {assignee_label(cook)}" if cook else ""
            ingredient_suffix = f" Ingredients: {', '.join(ingredients)}." if ingredients else ""
            return f"Added meal{suffix}: {title} on {meal_match.group(2).lower()}. Meal id {meal_id}.{ingredient_suffix}"

        grocery_match = re.fullmatch(
            r"(?:add|put) (.+?) (?:to|on) (?:the )?(?:grocery|shopping) list",
            text,
            flags=re.IGNORECASE,
        )
        if grocery_match:
            names = [
                self._clean_name(part)
                for part in re.split(r"\s*,\s*|\s+and\s+", grocery_match.group(1))
                if part.strip()
            ]
            added: list[str] = []
            existing: list[str] = []
            for name in names:
                if self.store.add_grocery_item(name, sender):
                    added.append(name)
                else:
                    existing.append(name)
            parts: list[str] = []
            if added:
                parts.append(f"Added to groceries: {', '.join(added)}.")
            if existing:
                parts.append(f"Already on groceries: {', '.join(existing)}.")
            return " ".join(parts)

        reminder_match = re.fullmatch(
            r"remind me to (.+?)\s+(today|tomorrow)",
            text,
            flags=re.IGNORECASE,
        )
        if reminder_match:
            title = self._clean_name(reminder_match.group(1))
            due = self.now() + timedelta(days=1 if reminder_match.group(2).lower() == "tomorrow" else 0)
            due_at = due.replace(second=0, microsecond=0)
            self.store.add_task(title, due_at.isoformat(), sender, True, sender)
            return f"Reminder added for you: {title} — {self._format_datetime(due_at)}."

        shared_task_match = re.fullmatch(
            r"add (.+?) to (?:the )?(?:family )?tasks(?: for (grant|billie|skye|all))?",
            text,
            flags=re.IGNORECASE,
        )
        if shared_task_match:
            title = self._clean_name(shared_task_match.group(1))
            assignee = normalize_assignee(shared_task_match.group(2))
            now = self.now().replace(second=0, microsecond=0)
            self.store.add_task(title, now.isoformat(), None, False, sender, assignee=assignee)
            suffix = f" for {assignee_label(assignee)}" if assignee else ""
            return f"Added shared task{suffix}: {title}."

        event_match = re.fullmatch(
            r"add (.+?)\s+(?:on\s+)?(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
            r"\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s+for\s+(.+))?",
            text,
            flags=re.IGNORECASE,
        )
        if event_match:
            title = self._clean_name(event_match.group(1))
            starts_at = self._parse_datetime(
                event_match.group(2),
                event_match.group(3),
                event_match.group(4),
                event_match.group(5),
            )
            person_or_assignee = event_match.group(6).strip() if event_match.group(6) else None
            assignee = normalize_assignee(person_or_assignee)
            person = person_or_assignee
            self.store.add_event(title, starts_at.isoformat(), person, sender, assignee=assignee)
            suffix = f" — {assignee_label(assignee)}" if assignee else (f" — {person}" if person else "")
            return f"Added: {title} — {self._format_datetime(starts_at)}{suffix}."

        return "I can add events, reminders, and groceries, or show what needs attention."

    def _task_query(self, assignee: str | None) -> str:
        tasks = self.store.list_tasks(assignee)
        label = assignee_label(assignee)
        if not tasks:
            return f"No open tasks assigned to {label}."
        lines = [f"Tasks for {label}:"]
        for index, task in enumerate(tasks[:8], start=1):
            due = ""
            if task["due_at"]:
                due = f" — due {self._format_datetime(datetime.fromisoformat(task['due_at']))}"
            lines.append(f"{index}. {task['title']}{due}")
        return "\n".join(lines)

    def _calendar_query(self, assignee: str | None) -> str:
        events = self.store.list_events(assignee)
        label = assignee_label(assignee)
        if not events:
            return f"No upcoming calendar events assigned to {label}."
        lines = [f"Calendar for {label}:"]
        for index, event in enumerate(events[:8], start=1):
            starts_at = datetime.fromisoformat(event["starts_at"])
            day = "today" if starts_at.date() == self.now().date() else "tomorrow" if starts_at.date() == (self.now() + timedelta(days=1)).date() else starts_at.strftime("%A, %B %-d")
            time = starts_at.strftime("%I:%M %p").lstrip("0")
            lines.append(f"{index}. {event['title']} — {day} at {time}")
        return "\n".join(lines)

    def _family_state(self, viewer: str) -> str:
        tasks = [
            task
            for task in self.store.list_tasks()
            if not task["private"] or task["owner"] == viewer
        ]
        if not tasks:
            return "Nothing urgent. The family is caught up."

        now = self.now()
        tasks.sort(
            key=lambda task: (
                0 if task["owner"] is None else 1,
                task["due_at"] is None,
                task["due_at"] or "",
            )
        )
        lines = ["Needs attention:"]
        for index, task in enumerate(tasks[:5], start=1):
            if task["owner"] is None:
                owner = "unassigned"
            elif task["owner"] == viewer:
                owner = "you"
            else:
                owner = "assigned"
            due = ""
            if task["due_at"]:
                due_datetime = datetime.fromisoformat(task["due_at"])
                due = f" — due {self._format_datetime(due_datetime)}"
                if due_datetime <= now:
                    due += " (due now)"
            lines.append(f"{index}. {task['title']} ({owner}){due}")
        return "\n".join(lines)

    def _parse_day_date(self, day: str):
        current = self.now().replace(second=0, microsecond=0)
        day_lower = day.lower()
        if day_lower == "today":
            return current.date()
        if day_lower == "tomorrow":
            return (current + timedelta(days=1)).date()
        days_ahead = (_WEEKDAYS[day_lower] - current.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return (current + timedelta(days=days_ahead)).date()

    def _parse_datetime(
        self,
        day: str,
        hour_text: str,
        minute_text: str | None,
        meridiem: str | None,
    ) -> datetime:
        current = self.now().replace(second=0, microsecond=0)
        day_lower = day.lower()
        if day_lower == "today":
            date = current.date()
        elif day_lower == "tomorrow":
            date = (current + timedelta(days=1)).date()
        else:
            days_ahead = (_WEEKDAYS[day_lower] - current.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            date = (current + timedelta(days=days_ahead)).date()

        hour = int(hour_text)
        minute = int(minute_text or "00")
        if meridiem:
            if meridiem.lower() == "pm" and hour != 12:
                hour += 12
            elif meridiem.lower() == "am" and hour == 12:
                hour = 0
        elif 1 <= hour <= 7:
            hour += 12
        return datetime.combine(date, datetime.min.time()).replace(hour=hour, minute=minute)

    @staticmethod
    def _clean_name(value: str) -> str:
        return value.strip().lower().rstrip(".")

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        hour = value.strftime("%I").lstrip("0")
        return f"{value.strftime('%A, %B %-d at')} {hour}:{value:%M} {value:%p}"
