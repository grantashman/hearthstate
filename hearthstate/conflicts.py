from __future__ import annotations

from datetime import datetime, timedelta

from .store import PlannerStore


def _same_household_scope(left: str | None, right: str | None) -> bool:
    return not left or not right or left == right or left == "all" or right == "all"


def detect_conflicts(store: PlannerStore) -> list[dict]:
    events = store.list_events()
    tasks = store.list_tasks()
    conflicts: list[dict] = []
    intervals = []
    for event in events:
        start = datetime.fromisoformat(event["starts_at"])
        end = datetime.fromisoformat(event["ends_at"]) if event.get("ends_at") else start + timedelta(hours=1)
        intervals.append((event, start, end))
    for index, (left, left_start, left_end) in enumerate(intervals):
        for right, right_start, right_end in intervals[index + 1:]:
            if _same_household_scope(left.get("assignee"), right.get("assignee")) and left_start < right_end and right_start < left_end:
                conflicts.append({
                    "id": f"event-overlap-{left['id']}-{right['id']}",
                    "kind": "event_overlap",
                    "title": f"{left['title']} overlaps {right['title']}",
                    "items": [left["title"], right["title"]],
                    "starts_at": min(left["starts_at"], right["starts_at"]),
                    "assignee": left.get("assignee") or right.get("assignee"),
                })
    for task in tasks:
        if not task.get("due_at"):
            continue
        due = datetime.fromisoformat(task["due_at"])
        for event, start, end in intervals:
            if _same_household_scope(task.get("assignee"), event.get("assignee")) and start <= due < end:
                conflicts.append({
                    "id": f"task-event-{task['id']}-{event['id']}",
                    "kind": "task_during_event",
                    "title": f"{task['title']} is due during {event['title']}",
                    "items": [task["title"], event["title"]],
                    "starts_at": task["due_at"],
                    "assignee": task.get("assignee") or event.get("assignee"),
                })
    return sorted(conflicts, key=lambda item: (item["starts_at"], item["id"]))
