from __future__ import annotations

import re
import sqlite3
from pathlib import Path


_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class HouseholdDirectory:
    """Small account/household directory used by the hosted tenancy boundary."""

    def __init__(self, database: str = "hearthstate-accounts.db") -> None:
        self.database_path = database
        self.connection = sqlite3.connect(database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                email TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS households (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS memberships (
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('owner', 'member', 'child', 'guest')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (household_id, account_id)
            );
            """
        )
        self.connection.commit()

    @staticmethod
    def _identifier(value: str, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if not _IDENTIFIER.fullmatch(normalized):
            raise ValueError(f"invalid {field}")
        return normalized

    @staticmethod
    def _required_text(value: str, field: str) -> str:
        text = str(value or "").strip()
        if not text or len(text) > 200:
            raise ValueError(f"invalid {field}")
        return text

    def create_account(self, account_id: str, display_name: str, email: str | None = None) -> dict[str, str | None]:
        account_id = self._identifier(account_id, "account id")
        display_name = self._required_text(display_name, "display name")
        email = str(email).strip() if email is not None and str(email).strip() else None
        if email is not None and len(email) > 320:
            raise ValueError("invalid email")
        try:
            self.connection.execute(
                "INSERT INTO accounts (id, display_name, email) VALUES (?, ?, ?)",
                (account_id, display_name, email),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("account already exists") from exc
        return dict(self.connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())

    def create_household(self, household_id: str, name: str, owner_account_id: str) -> dict[str, str]:
        household_id = self._identifier(household_id, "household id")
        name = self._required_text(name, "household name")
        owner_account_id = self._identifier(owner_account_id, "account id")
        if not self.connection.execute("SELECT 1 FROM accounts WHERE id = ?", (owner_account_id,)).fetchone():
            raise ValueError("owner account not found")
        try:
            self.connection.execute("INSERT INTO households (id, name) VALUES (?, ?)", (household_id, name))
            self.connection.execute(
                "INSERT INTO memberships (household_id, account_id, role) VALUES (?, ?, 'owner')",
                (household_id, owner_account_id),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise ValueError("household already exists") from exc
        return dict(self.connection.execute("SELECT * FROM households WHERE id = ?", (household_id,)).fetchone())

    def add_member(self, household_id: str, account_id: str, role: str = "member") -> dict[str, str]:
        household_id = self._identifier(household_id, "household id")
        account_id = self._identifier(account_id, "account id")
        role = str(role or "member").strip().lower()
        if role not in {"owner", "member", "child", "guest"}:
            raise ValueError("invalid membership role")
        if not self.connection.execute("SELECT 1 FROM households WHERE id = ?", (household_id,)).fetchone():
            raise ValueError("household not found")
        if not self.connection.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone():
            raise ValueError("account not found")
        try:
            self.connection.execute(
                "INSERT INTO memberships (household_id, account_id, role) VALUES (?, ?, ?)",
                (household_id, account_id, role),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("membership already exists") from exc
        return dict(self.connection.execute(
            "SELECT * FROM memberships WHERE household_id = ? AND account_id = ?",
            (household_id, account_id),
        ).fetchone())

    def household_for(self, account_id: str) -> str | None:
        account_id = self._identifier(account_id, "account id")
        row = self.connection.execute(
            "SELECT household_id FROM memberships WHERE account_id = ? ORDER BY created_at, household_id LIMIT 1",
            (account_id,),
        ).fetchone()
        return str(row["household_id"]) if row else None

    def role_for(self, account_id: str, household_id: str) -> str | None:
        account_id = self._identifier(account_id, "account id")
        household_id = self._identifier(household_id, "household id")
        row = self.connection.execute(
            "SELECT role FROM memberships WHERE account_id = ? AND household_id = ?",
            (account_id, household_id),
        ).fetchone()
        return str(row["role"]) if row else None

    def can_access(self, account_id: str, household_id: str) -> bool:
        return self.role_for(account_id, household_id) is not None

    def require_access(self, account_id: str, household_id: str) -> str:
        role = self.role_for(account_id, household_id)
        if role is None:
            raise ValueError("household membership required")
        return role

    def list_members(self, household_id: str) -> list[dict[str, str | None]]:
        household_id = self._identifier(household_id, "household id")
        rows = self.connection.execute(
            """SELECT accounts.id, accounts.display_name, accounts.email, memberships.role
               FROM memberships JOIN accounts ON accounts.id = memberships.account_id
               WHERE memberships.household_id = ? ORDER BY accounts.id""",
            (household_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.connection.close()
