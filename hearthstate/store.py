from __future__ import annotations

import json
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
    """SQLite persistence layer for one household's shared primitives.

    The default context keeps the original database path for local compatibility.
    Named household contexts use a sibling SQLite file, giving the hosted boundary
    a simple, auditable isolation model before a shared multi-tenant database is
    introduced.
    """

    def __init__(self, database: str = "hearthstate.db", *, household_id: str = "default") -> None:
        self._lock = threading.RLock()
        self.household_id = self._normalize_household_id(household_id)
        self.database_path = self._database_for_household(database, self.household_id)
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
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
                    ends_at TEXT,
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

                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id INTEGER NOT NULL,
                    before_json TEXT,
                    after_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    undone_at TEXT
                );

                CREATE TABLE IF NOT EXISTS briefing_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    viewer TEXT NOT NULL,
                    briefing_type TEXT NOT NULL,
                    run_date TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(viewer, briefing_type, run_date)
                );

                CREATE TABLE IF NOT EXISTS notification_preferences (
                    viewer TEXT NOT NULL,
                    briefing_type TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    preferred_time TEXT NOT NULL DEFAULT '07:30',
                    quiet_start TEXT NOT NULL DEFAULT '21:00',
                    quiet_end TEXT NOT NULL DEFAULT '07:00',
                    channel TEXT NOT NULL DEFAULT 'email',
                    updated_by TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (viewer, briefing_type)
                );

                CREATE TABLE IF NOT EXISTS briefing_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    viewer TEXT NOT NULL,
                    briefing_type TEXT NOT NULL,
                    run_date TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    claim_id TEXT,
                    claimed_at TEXT,
                    lease_until TEXT,
                    sent_at TEXT,
                    next_attempt_at TEXT,
                    provider_message_id TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(viewer, briefing_type, run_date)
                );

                CREATE TABLE IF NOT EXISTS chore_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    cadence TEXT NOT NULL DEFAULT 'weekly',
                    participants_json TEXT NOT NULL,
                    next_index INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._ensure_column("tasks", "assignee", "TEXT")
            self._ensure_column("tasks", "recurrence", "TEXT NOT NULL DEFAULT 'none'")
            self._ensure_column("events", "assignee", "TEXT")
            self._ensure_column("events", "ends_at", "TEXT")
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

    @staticmethod
    def _normalize_household_id(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized == "default":
            return normalized
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", normalized):
            raise ValueError("invalid household id")
        return normalized

    @staticmethod
    def _database_for_household(database: str, household_id: str) -> str:
        if household_id == "default" or database == ":memory:":
            return database
        path = Path(database)
        return str(path.with_name(f"{path.name}.{household_id}"))

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _record_activity(
        self,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: int,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO activity_log
               (actor, action, entity_type, entity_id, before_json, after_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(actor or "system"), action, entity_type, entity_id,
             json.dumps(before, sort_keys=True) if before is not None else None,
             json.dumps(after, sort_keys=True) if after is not None else None),
        )

    @staticmethod
    def _decode_activity(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["before"] = json.loads(item.pop("before_json")) if item.get("before_json") else None
        item["after"] = json.loads(item.pop("after_json")) if item.get("after_json") else None
        return item

    def list_activity(self, *, viewer: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 200)),)
            ).fetchall()
            result = []
            for row in rows:
                item = self._decode_activity(row)
                state = item.get("after") or item.get("before") or {}
                if viewer is not None and item["entity_type"] == "task" and state.get("private") and state.get("owner") != viewer and state.get("created_by") != viewer:
                    continue
                result.append(item)
            return result

    def undo_last(self, actor: str) -> dict[str, Any]:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM activity_log WHERE actor = ? AND undone_at IS NULL AND action NOT LIKE '%.undone' ORDER BY id DESC LIMIT 1",
                (actor,),
            ).fetchone()
            if row is None:
                raise ValueError("nothing to undo")
            activity = self._decode_activity(row)
            before = activity["before"]
            after = activity["after"]
            entity_type = activity["entity_type"]
            entity_id = activity["entity_id"]
            entity_info = {
                "task": ("tasks", ("title", "due_at", "owner", "assignee", "private", "recurrence", "status", "created_by")),
                "event": ("events", ("title", "starts_at", "ends_at", "person", "assignee", "status", "created_by")),
                "meal": ("meals", ("meal_date", "meal_type", "title", "cook", "status", "created_by", "recipe_id")),
                "grocery": ("grocery_items", ("name", "quantity", "unit", "category", "price", "price_source", "price_url", "price_checked_at", "price_confidence", "price_note", "status", "created_by")),
            }
            table_info = entity_info.get(entity_type)
            if table_info is None or after is None:
                raise ValueError("change cannot be undone")
            table, columns = table_info
            if before is None:
                self.connection.execute("UPDATE " + table + " SET status = 'archived' WHERE id = ?", (entity_id,))
            else:
                assignments = ", ".join(column + " = ?" for column in columns)
                self.connection.execute(
                    "UPDATE " + table + " SET " + assignments + " WHERE id = ?",
                    tuple(before.get(column) for column in columns) + (entity_id,),
                )
                if entity_type == "meal" and "ingredients" in before:
                    self.connection.execute("DELETE FROM meal_ingredients WHERE meal_id = ?", (entity_id,))
                    self.connection.executemany(
                        "INSERT INTO meal_ingredients (meal_id, name) VALUES (?, ?)",
                        [(entity_id, ingredient) for ingredient in before["ingredients"]],
                    )
            self.connection.execute("UPDATE activity_log SET undone_at = CURRENT_TIMESTAMP WHERE id = ?", (activity["id"],))
            self.connection.commit()
            return {"entity_type": entity_type, "entity_id": entity_id, "action": activity["action"]}

    def add_chore(self, title: str, cadence: str, participants: list[str], created_by: str) -> int:
        title = str(title).strip()
        cadence = str(cadence).strip().lower()
        participants = [normalize_assignee(item) for item in participants]
        participants = list(dict.fromkeys(item for item in participants if item and item != "all"))
        if not title or cadence not in {"daily", "weekly", "fortnightly", "monthly"} or len(participants) < 2:
            raise ValueError("a chore needs a title, supported cadence, and at least two participants")
        with self._lock:
            cursor = self.connection.execute(
                "INSERT INTO chore_templates (title, cadence, participants_json, created_by) VALUES (?, ?, ?, ?)",
                (title, cadence, json.dumps(participants), created_by),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    def list_chores(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute("SELECT * FROM chore_templates WHERE active = 1 ORDER BY title COLLATE NOCASE, id").fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["participants"] = json.loads(item.pop("participants_json"))
                result.append(item)
            return result

    def assign_next_chore(self, chore_id: int, due_date: str, created_by: str) -> dict[str, Any]:
        with self._lock:
            row = self.connection.execute("SELECT * FROM chore_templates WHERE id = ? AND active = 1", (chore_id,)).fetchone()
            if row is None:
                raise ValueError("chore not found")
            participants = json.loads(row["participants_json"])
            index = int(row["next_index"]) % len(participants)
            assignee = participants[index]
            task_id = self.add_task(row["title"], f"{due_date}T09:00:00", None, False, created_by, assignee=assignee, recurrence=row["cadence"], actor=created_by)
            self.connection.execute("UPDATE chore_templates SET next_index = ? WHERE id = ?", ((index + 1) % len(participants), chore_id))
            self.connection.commit()
            return next(task for task in self.list_tasks() if task["id"] == task_id)

    @staticmethod
    def _delivery_timestamp(value: datetime | None = None) -> datetime:
        current = value or datetime.now(timezone.utc)
        if current.tzinfo is None:
            return current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    @staticmethod
    def _clock(value: str, field: str) -> str:
        text = str(value or "").strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", text):
            raise ValueError(f"invalid {field}")
        return text

    @staticmethod
    def _preference_item(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        return item

    def get_notification_preferences(self, viewer: str, briefing_type: str = "morning") -> dict[str, Any]:
        viewer = str(viewer or "").strip()
        briefing_type = str(briefing_type or "").strip().lower()
        if not viewer or len(viewer) > 120 or not briefing_type or len(briefing_type) > 64:
            raise ValueError("invalid notification preference identity")
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM notification_preferences WHERE viewer = ? AND briefing_type = ?",
                (viewer, briefing_type),
            ).fetchone()
            if row is None:
                self.connection.execute(
                    """INSERT OR IGNORE INTO notification_preferences
                       (viewer, briefing_type, updated_by)
                       VALUES (?, ?, ?)""",
                    (viewer, briefing_type, viewer),
                )
                self.connection.commit()
                row = self.connection.execute(
                    "SELECT * FROM notification_preferences WHERE viewer = ? AND briefing_type = ?",
                    (viewer, briefing_type),
                ).fetchone()
            return self._preference_item(row)

    def set_notification_preferences(
        self,
        viewer: str,
        *,
        briefing_type: str = "morning",
        enabled: bool | None = None,
        preferred_time: str | None = None,
        quiet_start: str | None = None,
        quiet_end: str | None = None,
        channel: str | None = None,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_notification_preferences(viewer, briefing_type)
        viewer = str(viewer or "").strip()
        updated_by = str(updated_by or viewer).strip()
        if not updated_by or len(updated_by) > 120:
            raise ValueError("invalid updated_by")
        preferred_time = self._clock(preferred_time or current["preferred_time"], "preferred time")
        quiet_start = self._clock(quiet_start or current["quiet_start"], "quiet start")
        quiet_end = self._clock(quiet_end or current["quiet_end"], "quiet end")
        channel = str(channel or current["channel"]).strip().lower()
        if channel != "email":
            raise ValueError("unsupported notification channel")
        with self._lock:
            self.connection.execute(
                """UPDATE notification_preferences
                   SET enabled = ?, preferred_time = ?, quiet_start = ?, quiet_end = ?,
                       channel = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE viewer = ? AND briefing_type = ?""",
                (
                    int(current["enabled"] if enabled is None else bool(enabled)),
                    preferred_time,
                    quiet_start,
                    quiet_end,
                    channel,
                    updated_by,
                    viewer,
                    briefing_type,
                ),
            )
            self.connection.commit()
            row = self.connection.execute(
                "SELECT * FROM notification_preferences WHERE viewer = ? AND briefing_type = ?",
                (viewer, briefing_type),
            ).fetchone()
            return self._preference_item(row)

    def get_briefing_delivery(self, viewer: str, briefing_type: str, run_date: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                """SELECT * FROM briefing_deliveries
                   WHERE viewer = ? AND briefing_type = ? AND run_date = ?""",
                (viewer, briefing_type, run_date),
            ).fetchone()
            return dict(row) if row is not None else None

    def claim_briefing_delivery(
        self,
        viewer: str,
        briefing_type: str,
        run_date: str,
        *,
        now: datetime | None = None,
        lease: timedelta = timedelta(minutes=10),
        max_attempts: int = 3,
    ) -> dict[str, Any] | None:
        if lease <= timedelta(0) or max_attempts < 1:
            raise ValueError("invalid delivery claim settings")
        current = self._delivery_timestamp(now)
        current_text = current.isoformat()
        claim_id = secrets.token_urlsafe(18)
        lease_until = (current + lease).isoformat()
        with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                self.connection.execute(
                    """INSERT OR IGNORE INTO briefing_deliveries
                       (viewer, briefing_type, run_date, status)
                       VALUES (?, ?, ?, 'pending')""",
                    (viewer, briefing_type, run_date),
                )
                row = self.connection.execute(
                    """SELECT * FROM briefing_deliveries
                       WHERE viewer = ? AND briefing_type = ? AND run_date = ?""",
                    (viewer, briefing_type, run_date),
                ).fetchone()
                if row is None or row["status"] == "sent":
                    self.connection.commit()
                    return None
                if int(row["attempt_count"]) >= max_attempts and row["status"] == "failed":
                    self.connection.commit()
                    return None
                if row["status"] == "pending" and row["lease_until"]:
                    if self._delivery_timestamp(datetime.fromisoformat(row["lease_until"])) > current:
                        self.connection.commit()
                        return None
                if row["status"] == "failed" and row["next_attempt_at"]:
                    if self._delivery_timestamp(datetime.fromisoformat(row["next_attempt_at"])) > current:
                        self.connection.commit()
                        return None
                self.connection.execute(
                    """UPDATE briefing_deliveries
                       SET status = 'pending', attempt_count = attempt_count + 1,
                           claim_id = ?, claimed_at = ?, lease_until = ?, next_attempt_at = NULL
                       WHERE id = ?""",
                    (claim_id, current_text, lease_until, row["id"]),
                )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            updated = self.connection.execute(
                "SELECT * FROM briefing_deliveries WHERE id = ?", (row["id"],)
            ).fetchone()
            return dict(updated)

    def mark_briefing_delivery_sent(
        self,
        viewer: str,
        briefing_type: str,
        run_date: str,
        claim_id: str,
        provider_message_id: str | None,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        sent_at = self._delivery_timestamp(now).isoformat()
        provider_message_id = str(provider_message_id or "")[:200] or None
        with self._lock:
            updated = self.connection.execute(
                """UPDATE briefing_deliveries
                   SET status = 'sent', sent_at = ?, provider_message_id = ?,
                       claim_id = NULL, lease_until = NULL, next_attempt_at = NULL
                   WHERE viewer = ? AND briefing_type = ? AND run_date = ?
                     AND claim_id = ? AND status = 'pending'""",
                (sent_at, provider_message_id, viewer, briefing_type, run_date, claim_id),
            )
            if updated.rowcount != 1:
                raise ValueError("briefing delivery claim is no longer active")
            self.connection.commit()
            return dict(self.connection.execute(
                "SELECT * FROM briefing_deliveries WHERE viewer = ? AND briefing_type = ? AND run_date = ?",
                (viewer, briefing_type, run_date),
            ).fetchone())

    def mark_briefing_delivery_failed(
        self,
        viewer: str,
        briefing_type: str,
        run_date: str,
        claim_id: str,
        error: str,
        *,
        retry_at: datetime | None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        next_attempt_at = self._delivery_timestamp(retry_at).isoformat() if retry_at is not None else None
        safe_error = str(error or "delivery provider failed")[:240]
        with self._lock:
            updated = self.connection.execute(
                """UPDATE briefing_deliveries
                   SET status = 'failed', last_error = ?, next_attempt_at = ?,
                       claim_id = NULL, lease_until = NULL
                   WHERE viewer = ? AND briefing_type = ? AND run_date = ?
                     AND claim_id = ? AND status = 'pending'""",
                (safe_error, next_attempt_at, viewer, briefing_type, run_date, claim_id),
            )
            if updated.rowcount != 1:
                raise ValueError("briefing delivery claim is no longer active")
            self.connection.commit()
            return dict(self.connection.execute(
                "SELECT * FROM briefing_deliveries WHERE viewer = ? AND briefing_type = ? AND run_date = ?",
                (viewer, briefing_type, run_date),
            ).fetchone())

    def claim_briefing(self, viewer: str, briefing_type: str, run_date: str) -> bool:
        with self._lock:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO briefing_runs (viewer, briefing_type, run_date) VALUES (?, ?, ?)",
                (viewer, briefing_type, run_date),
            )
            self.connection.commit()
            return cursor.rowcount == 1

    def briefing_claimed(self, viewer: str, briefing_type: str, run_date: str) -> bool:
        with self._lock:
            return self.connection.execute(
                "SELECT 1 FROM briefing_runs WHERE viewer = ? AND briefing_type = ? AND run_date = ?",
                (viewer, briefing_type, run_date),
            ).fetchone() is not None

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

    def add_grocery_item(self, name: str, created_by: str, *, actor: str | None = None) -> bool:
        with self._lock:
            existing = self.connection.execute(
                "SELECT 1 FROM grocery_items WHERE lower(name) = lower(?) AND status = 'open'",
                (name,),
            ).fetchone()
            if existing:
                return False
            cursor = self.connection.execute(
                "INSERT INTO grocery_items (name, created_by) VALUES (?, ?)",
                (name, created_by),
            )
            item_id = int(cursor.lastrowid)
            after = dict(self.connection.execute("SELECT * FROM grocery_items WHERE id = ?", (item_id,)).fetchone())
            self._record_activity(actor or created_by, "grocery.created", "grocery", item_id, None, after)
            self.connection.commit()
        # Match immediately on every successful grocery capture so callers never
        # have to wait for a page refresh or press a separate retailer button.
        from .pricing import apply_known_coles_prices
        apply_known_coles_prices(self)
        return True

    def archive_grocery_item(self, item_id: int, *, actor: str | None = None) -> dict[str, Any]:
        with self._lock:
            before_row = self.connection.execute("SELECT * FROM grocery_items WHERE id = ? AND status = 'open'", (item_id,)).fetchone()
            if before_row is None:
                raise ValueError("grocery item not found")
            before = dict(before_row)
            self.connection.execute("UPDATE grocery_items SET status = 'archived' WHERE id = ?", (item_id,))
            after = dict(self.connection.execute("SELECT * FROM grocery_items WHERE id = ?", (item_id,)).fetchone())
            self._record_activity(actor or before["created_by"], "grocery.archived", "grocery", item_id, before, after)
            self.connection.commit()
            return after

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
        actor: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            current = self.connection.execute("SELECT * FROM grocery_items WHERE id = ?", (item_id,)).fetchone()
            if current is None:
                raise ValueError("grocery item not found")
            before = dict(current)
            self.connection.execute(
                "UPDATE grocery_items SET quantity = ?, unit = ?, category = ? WHERE id = ?",
                (
                    float(quantity) if quantity is not None else current["quantity"],
                    (unit or current["unit"]).strip(),
                    (category or current["category"]).strip(),
                    item_id,
                ),
            )
            result = dict(self.connection.execute("SELECT * FROM grocery_items WHERE id = ?", (item_id,)).fetchone())
            self._record_activity(actor or result["created_by"], "grocery.updated", "grocery", item_id, before, result)
            self.connection.commit()
            return result

    def set_grocery_price(
        self,
        item_id: int,
        price: float,
        source: str,
        url: str | None,
        confidence: str,
        checked_at: str,
        note: str = "",
        actor: str | None = None,
    ) -> dict[str, Any]:
        if price < 0:
            raise ValueError("price cannot be negative")
        with self._lock:
            if not self.connection.execute("SELECT 1 FROM grocery_items WHERE id = ?", (item_id,)).fetchone():
                raise ValueError("grocery item not found")
            before = dict(self.connection.execute("SELECT * FROM grocery_items WHERE id = ?", (item_id,)).fetchone())
            self.connection.execute(
                """UPDATE grocery_items
                   SET price = ?, price_source = ?, price_url = ?, price_confidence = ?,
                       price_checked_at = ?, price_note = ?
                   WHERE id = ?""",
                (round(float(price), 2), source.strip(), url, confidence.strip(), checked_at.strip(), note.strip(), item_id),
            )
            result = dict(self.connection.execute("SELECT * FROM grocery_items WHERE id = ?", (item_id,)).fetchone())
            self._record_activity(actor or result["created_by"], "grocery.repriced", "grocery", item_id, before, result)
            self.connection.commit()
            return result
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
        actor: str | None = None,
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
            task_id = int(cursor.lastrowid)
            after = dict(self.connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
            self._record_activity(actor or created_by, "task.created", "task", task_id, None, after)
            self.connection.commit()
            return task_id

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
        actor: str | None = None,
    ) -> dict[str, Any]:
        normalized_recurrence = normalize_recurrence(recurrence)
        if normalized_recurrence != "none" and not due_at:
            raise ValueError("recurrence requires a due date")
        with self._lock:
            before_row = self.connection.execute("SELECT * FROM tasks WHERE id = ? AND status = 'open'", (task_id,)).fetchone()
            if before_row is None:
                raise ValueError("task not found")
            before = dict(before_row)
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
            row = self.connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            result = dict(row)
            self._record_activity(actor or result["created_by"], "task.updated", "task", task_id, before, result)
            self.connection.commit()
            return result

    def complete_task(self, task_id: int, *, actor: str | None = None) -> dict[str, Any]:
        with self._lock:
            before_row = self.connection.execute("SELECT * FROM tasks WHERE id = ? AND status = 'open'", (task_id,)).fetchone()
            if before_row is None:
                raise ValueError("task not found")
            before = dict(before_row)
            cursor = self.connection.execute(
                "UPDATE tasks SET status = 'done' WHERE id = ? AND status = 'open'",
                (task_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("task not found")
            row = self.connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            result = dict(row)
            self._record_activity(actor or result["created_by"], "task.completed", "task", task_id, before, result)
            self.connection.commit()
            return result

    def delete_task(self, task_id: int, *, actor: str | None = None) -> None:
        with self._lock:
            before_row = self.connection.execute("SELECT * FROM tasks WHERE id = ? AND status = 'open'", (task_id,)).fetchone()
            if before_row is None:
                raise ValueError("task not found")
            before = dict(before_row)
            cursor = self.connection.execute("UPDATE tasks SET status = 'archived' WHERE id = ? AND status = 'open'", (task_id,))
            if cursor.rowcount != 1:
                raise ValueError("task not found")
            after = dict(self.connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
            self._record_activity(actor or before["created_by"], "task.archived", "task", task_id, before, after)
            self.connection.commit()

    def add_event(
        self,
        title: str,
        starts_at: str,
        person: str | None,
        created_by: str,
        assignee: str | None = None,
        ends_at: str | None = None,
        actor: str | None = None,
    ) -> int:
        with self._lock:
            cursor = self.connection.execute(
                """
                INSERT INTO events (title, starts_at, ends_at, person, assignee, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (title, starts_at, ends_at, person, normalize_assignee(assignee), created_by),
            )
            event_id = int(cursor.lastrowid)
            after = dict(self.connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
            self._record_activity(actor or created_by, "event.created", "event", event_id, None, after)
            self.connection.commit()
            return event_id

    def update_event(
        self,
        event_id: int,
        title: str,
        starts_at: str,
        person: str | None,
        assignee: str | None,
        ends_at: str | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            before_row = self.connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            if before_row is None:
                raise ValueError("event not found")
            before = dict(before_row)
            self.connection.execute(
                "UPDATE events SET title = ?, starts_at = ?, ends_at = ?, person = ?, assignee = ? WHERE id = ?",
                (title, starts_at, ends_at, person, normalize_assignee(assignee), event_id),
            )
            result = dict(self.connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())
            self._record_activity(actor or result["created_by"], "event.updated", "event", event_id, before, result)
            self.connection.commit()
            return result

    def add_meal(
        self,
        meal_date: str,
        meal_type: str,
        title: str,
        cook: str | None,
        ingredients: list[str],
        created_by: str,
        recipe_id: int | None = None,
        actor: str | None = None,
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
            after = dict(self.connection.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone())
            self._record_activity(actor or created_by, "meal.created", "meal", meal_id, None, after)
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
        actor: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            before_row = self.connection.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
            if before_row is None:
                raise ValueError("meal not found")
            before = dict(before_row)
            before["ingredients"] = [
                row["name"] for row in self.connection.execute(
                    "SELECT name FROM meal_ingredients WHERE meal_id = ? ORDER BY id", (meal_id,)
                ).fetchall()
            ]
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
            meal = dict(self.connection.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone())
            meal["ingredients"] = [
                row["name"]
                for row in self.connection.execute(
                    "SELECT name FROM meal_ingredients WHERE meal_id = ? ORDER BY id",
                    (meal_id,),
                ).fetchall()
            ]
            self._record_activity(actor or before["created_by"], "meal.updated", "meal", meal_id, before, meal)
            self.connection.commit()
            return meal

    def delete_meal(self, meal_id: int, *, actor: str | None = None) -> None:
        with self._lock:
            before_row = self.connection.execute("SELECT * FROM meals WHERE id = ? AND status = 'planned'", (meal_id,)).fetchone()
            if before_row is None:
                raise ValueError("meal not found")
            before = dict(before_row)
            cursor = self.connection.execute("UPDATE meals SET status = 'archived' WHERE id = ? AND status = 'planned'", (meal_id,))
            if cursor.rowcount != 1:
                raise ValueError("meal not found")
            after = dict(self.connection.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone())
            self._record_activity(actor or before["created_by"], "meal.archived", "meal", meal_id, before, after)
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
