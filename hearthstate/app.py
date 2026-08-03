from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Callable

from .store import HOUSEHOLD_MEMBERS, PlannerStore, assignee_label, normalize_assignee
from .conflicts import detect_conflicts
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


class Hearthstate:
    """Translate a small set of natural-language messages into planner actions."""

    def __init__(self, store: PlannerStore, now: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.now = now or local_now

    def handle_message(self, sender: str, message: str) -> str:
        text = " ".join(message.strip().split())
        lowered = text.lower()

        if lowered in {"what needs attention?", "what needs attention", "family state"}:
            return self._family_state(sender)

        if lowered in {"what conflicts?", "what conflicts are there?", "show conflicts"}:
            conflicts = detect_conflicts(self.store)
            if not conflicts:
                return "No calendar conflicts found."
            return "Conflicts:\n" + "\n".join(f"{index}. {item['title']}" for index, item in enumerate(conflicts[:8], start=1))

        if lowered in {"what changed?", "what has changed?", "show recent changes"}:
            activity = self.store.list_activity(limit=8)
            if not activity:
                return "No household changes recorded yet."
            return "Recent changes:\n" + "\n".join(
                f"{index}. {item['action'].replace('.', ' ')} — {item['after'].get('title', item['after'].get('name', 'item')) if item.get('after') else 'item'}"
                for index, item in enumerate(activity, start=1)
            )

        if lowered in {"undo that", "undo the last change", "undo"}:
            try:
                undone = self.store.undo_last(sender)
            except ValueError:
                return "There is nothing for me to undo."
            return f"Restored the last {undone['entity_type']} change."

        completion_match = re.fullmatch(r"(?:mark|complete|finish) (.+?)(?: as done| done)?", text, flags=re.IGNORECASE)
        if completion_match:
            title = self._clean_name(completion_match.group(1))
            tasks = [task for task in self.store.list_tasks() if title in task["title"].lower()]
            if not tasks:
                return f"I couldn't find an open task matching {title}."
            self.store.complete_task(tasks[0]["id"], actor=sender)
            return f"Completed: {tasks[0]['title']}."

        grocery_remove_match = re.fullmatch(r"(?:remove|delete|take off) (.+?) from (?:the )?(?:grocery list|shopping list|groceries)", text, flags=re.IGNORECASE)
        if grocery_remove_match:
            name = self._clean_name(grocery_remove_match.group(1))
            items = [item for item in self.store.list_grocery_items() if name in item["name"].lower()]
            if not items:
                return f"I couldn't find {name} on groceries."
            self.store.archive_grocery_item(items[0]["id"], actor=sender)
            return f"Removed from groceries: {items[0]['name']}."

        assign_match = re.fullmatch(r"assign (.+?) to (grant|billie|skye)", lowered, flags=re.IGNORECASE)
        if assign_match:
            title = self._clean_name(assign_match.group(1))
            tasks = [task for task in self.store.list_tasks() if title in task["title"].lower()]
            if not tasks:
                return f"I couldn't find an open task matching {title}."
            task = tasks[0]
            updated = self.store.update_task(task["id"], task["title"], task["due_at"], assign_match.group(2), task.get("recurrence", "none"), actor=sender)
            return f"Assigned {updated['title']} to {assignee_label(updated['assignee'])}."

        rename_match = re.fullmatch(r"rename (?:task )?(.+?) to (.+)", text, flags=re.IGNORECASE)
        if rename_match:
            old_title = self._clean_name(rename_match.group(1))
            new_title = self._clean_name(rename_match.group(2))
            tasks = [task for task in self.store.list_tasks() if old_title in task["title"].lower()]
            if not tasks:
                return f"I couldn't find an open task matching {old_title}."
            task = tasks[0]
            updated = self.store.update_task(task["id"], new_title, task["due_at"], task.get("assignee"), task.get("recurrence", "none"), actor=sender)
            return f"Renamed task to: {updated['title']}."

        move_match = re.fullmatch(
            r"move (.+?) to (today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
            text,
            flags=re.IGNORECASE,
        )
        if move_match:
            old_title = self._clean_name(move_match.group(1))
            events = [event for event in self.store.list_events() if old_title in event["title"].lower()]
            if not events:
                return f"I couldn't find an event matching {old_title}."
            event = events[0]
            starts_at = self._parse_datetime(move_match.group(2), move_match.group(3), move_match.group(4), move_match.group(5))
            updated = self.store.update_event(event["id"], event["title"], starts_at.isoformat(), event.get("person"), event.get("assignee"), event.get("ends_at"), actor=sender)
            return f"Moved: {updated['title']} — {self._format_datetime(starts_at)}."

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

        chore_match = re.fullmatch(
            r"add (.+?) as a (daily|weekly|fortnightly|monthly) chore for (grant|billie|skye)(?: and (grant|billie|skye))+",
            lowered,
            flags=re.IGNORECASE,
        )
        if chore_match:
            title = self._clean_name(chore_match.group(1))
            participants = re.findall(r"grant|billie|skye", chore_match.group(0), flags=re.IGNORECASE)
            chore_id = self.store.add_chore(title, chore_match.group(2), participants, sender)
            return f"Added chore: {title}. Chore id {chore_id}."

        chore_query = re.fullmatch(r"who(?:'s| is) next for (.+?)(?: chore)?\??", lowered, flags=re.IGNORECASE)
        if chore_query:
            title = self._clean_name(chore_query.group(1))
            chores = [chore for chore in self.store.list_chores() if title in chore["title"].lower()]
            if not chores:
                return f"I couldn't find a chore matching {title}."
            chore = chores[0]
            next_person = chore["participants"][chore["next_index"] % len(chore["participants"])]
            return f"Next for {chore['title']}: {assignee_label(next_person)}."

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

        if self._should_capture_inbox(lowered):
            item_id = self.store.add_inbox_item(text, sender, source="imessage")
            return f"Captured in Inbox for later triage: {text}. Inbox item {item_id}."
        return "I can add events, reminders, and groceries, or show what needs attention."

    @staticmethod
    def _should_capture_inbox(lowered: str) -> bool:
        return bool(re.search(r"\b(?:need to|need|remember|maybe|check|sort|should we|could we|can we|don't forget)\b", lowered))

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
