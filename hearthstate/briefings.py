from __future__ import annotations

import argparse
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .store import PlannerStore
from .timezone import local_now


def _current_time(now: datetime | None = None) -> datetime:
    return (now or local_now()).replace(second=0, microsecond=0)


def _is_quiet(current: datetime) -> bool:
    return current.hour < 7 or current.hour >= 21


def compose_briefing(store: PlannerStore, viewer: str, now: datetime | None = None) -> str | None:
    current = _current_time(now)
    if _is_quiet(current):
        return None
    tasks = [task for task in store.list_tasks() if not task["private"] or task["owner"] == viewer]
    due_soon = [task for task in tasks if task.get("due_at") and datetime.fromisoformat(task["due_at"]) <= current + timedelta(days=1)]
    events = [event for event in store.list_events() if current.date().isoformat() <= event["starts_at"][:10] <= (current + timedelta(days=1)).date().isoformat()]
    meals = store.list_meals(current.date().isoformat(), (current + timedelta(days=1)).date().isoformat())
    lines = ["Good morning — Hearthstate briefing:"]
    if due_soon:
        lines.append("Tasks: " + ", ".join(task["title"] for task in due_soon[:5]) + ".")
    if events:
        lines.append("Calendar: " + ", ".join(event["title"] for event in events[:5]) + ".")
    if not any(meal["meal_type"] == "dinner" and meal["meal_date"] == current.date().isoformat() for meal in meals):
        lines.append("Dinner is unplanned tonight.")
    grocery = store.grocery_budget_snapshot()
    if grocery["over_budget"]:
        lines.append(f"Groceries are ${abs(grocery['remaining']):.2f} over budget.")
    if len(lines) == 1:
        lines.append("The household is looking clear.")
    return " ".join(lines)


def build_briefing(store: PlannerStore, viewer: str, now: datetime | None = None) -> str | None:
    """Build a preview without claiming the briefing run."""
    current = _current_time(now)
    if _is_quiet(current) or store.briefing_claimed(viewer, "morning", current.date().isoformat()):
        return None
    return compose_briefing(store, viewer, current)


def run_briefing(
    store: PlannerStore,
    viewer: str,
    now: datetime | None = None,
    *,
    briefing_type: str = "morning",
) -> str | None:
    """Compose a briefing and claim its dedupe key before it can be emitted."""
    current = _current_time(now)
    if _is_quiet(current):
        return None
    message = compose_briefing(store, viewer, current)
    if message is None or not store.claim_briefing(viewer, briefing_type, current.date().isoformat()):
        return None
    return message


def claim_briefing(store: PlannerStore, viewer: str, briefing_type: str, now: datetime | None = None) -> bool:
    current = _current_time(now)
    return store.claim_briefing(viewer, briefing_type, current.date().isoformat())


def write_private_briefing(path: str, message: str) -> None:
    """Atomically replace a briefing file with owner-only permissions."""
    destination = Path(path).expanduser()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(message)
            temporary_file.write("\n")
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.close(file_descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Render one Hearthstate household briefing.")
    parser.add_argument("--database", default="hearthstate.db")
    parser.add_argument("--viewer", default="grant")
    parser.add_argument("--briefing-type", default="morning")
    parser.add_argument("--household-id", default="default")
    parser.add_argument("--output-file")
    args = parser.parse_args()
    store = PlannerStore(args.database, household_id=args.household_id)
    try:
        message = run_briefing(store, args.viewer, briefing_type=args.briefing_type)
        if message:
            if args.output_file:
                write_private_briefing(args.output_file, message)
            else:
                print(message)
    finally:
        store.close()


if __name__ == "__main__":
    main()
