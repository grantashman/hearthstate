from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path


_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapped


class HouseholdDirectory:
    """Account, household, membership, invitation, and sign-in directory."""

    def __init__(self, database: str = "hearthstate-accounts.db") -> None:
        self._lock = threading.RLock()
        self.database_path = database
        self.connection = sqlite3.connect(database, check_same_thread=False)
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

            CREATE TABLE IF NOT EXISTS invitations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT NOT NULL UNIQUE,
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                email TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('member', 'child', 'guest')),
                invited_by TEXT NOT NULL REFERENCES accounts(id),
                expires_at TEXT NOT NULL,
                accepted_at TEXT,
                accepted_account_id TEXT REFERENCES accounts(id),
                revoked_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS auth_tokens (
                token_hash TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK (kind = 'sign_in'),
                expires_at TEXT NOT NULL,
                consumed_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        invitation_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(invitations)").fetchall()}
        if "revoked_at" not in invitation_columns:
            self.connection.execute("ALTER TABLE invitations ADD COLUMN revoked_at TEXT")
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

    @staticmethod
    def _email(value: str) -> str:
        email = str(value or "").strip().lower()
        if len(email) > 320 or not _EMAIL.fullmatch(email):
            raise ValueError("invalid email")
        return email

    @staticmethod
    def _timestamp(value: datetime | None) -> datetime:
        current = value or datetime.now(timezone.utc)
        if current.tzinfo is None:
            return current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _account_id_for_email(email: str) -> str:
        digest = hashlib.sha256(email.encode("utf-8")).hexdigest()[:20]
        return f"user-{digest}"

    @_serialized
    def create_account(self, account_id: str, display_name: str, email: str | None = None) -> dict[str, str | None]:
        account_id = self._identifier(account_id, "account id")
        display_name = self._required_text(display_name, "display name")
        email = self._email(email) if email is not None and str(email).strip() else None
        try:
            self.connection.execute(
                "INSERT INTO accounts (id, display_name, email) VALUES (?, ?, ?)",
                (account_id, display_name, email),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("account already exists") from exc
        return dict(self.connection.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())

    @_serialized
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

    @_serialized
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

    @_serialized
    def household_for(self, account_id: str) -> str | None:
        account_id = self._identifier(account_id, "account id")
        row = self.connection.execute(
            "SELECT household_id FROM memberships WHERE account_id = ? ORDER BY created_at, household_id LIMIT 1",
            (account_id,),
        ).fetchone()
        return str(row["household_id"]) if row else None

    @_serialized
    def role_for(self, account_id: str, household_id: str) -> str | None:
        account_id = self._identifier(account_id, "account id")
        household_id = self._identifier(household_id, "household id")
        row = self.connection.execute(
            "SELECT role FROM memberships WHERE account_id = ? AND household_id = ?",
            (account_id, household_id),
        ).fetchone()
        return str(row["role"]) if row else None

    @_serialized
    def can_access(self, account_id: str, household_id: str) -> bool:
        return self.role_for(account_id, household_id) is not None

    @_serialized
    def require_access(self, account_id: str, household_id: str) -> str:
        role = self.role_for(account_id, household_id)
        if role is None:
            raise ValueError("household membership required")
        return role

    @_serialized
    def get_member_contact(self, household_id: str, account_id: str) -> dict[str, str | None]:
        household_id = self._identifier(household_id, "household id")
        account_id = self._identifier(account_id, "account id")
        row = self.connection.execute(
            """SELECT accounts.id, accounts.display_name, accounts.email, memberships.role
               FROM memberships JOIN accounts ON accounts.id = memberships.account_id
               WHERE memberships.household_id = ? AND memberships.account_id = ?""",
            (household_id, account_id),
        ).fetchone()
        if row is None:
            raise ValueError("household membership required")
        return dict(row)

    @_serialized
    def list_members(self, household_id: str) -> list[dict[str, str | None]]:
        household_id = self._identifier(household_id, "household id")
        rows = self.connection.execute(
            """SELECT accounts.id, accounts.display_name, accounts.email, memberships.role
               FROM memberships JOIN accounts ON accounts.id = memberships.account_id
               WHERE memberships.household_id = ? ORDER BY accounts.id""",
            (household_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @_serialized
    def get_household(self, household_id: str) -> dict[str, str]:
        household_id = self._identifier(household_id, "household id")
        row = self.connection.execute(
            "SELECT id, name FROM households WHERE id = ?",
            (household_id,),
        ).fetchone()
        if row is None:
            raise ValueError("household not found")
        return dict(row)

    @_serialized
    def update_household(self, household_id: str, name: str, updated_by: str) -> dict[str, str]:
        household_id = self._identifier(household_id, "household id")
        updated_by = self._identifier(updated_by, "account id")
        name = self._required_text(name, "household name")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            if self.role_for(updated_by, household_id) != "owner":
                raise ValueError("only household owners can update settings")
            updated = self.connection.execute(
                "UPDATE households SET name = ? WHERE id = ?",
                (name, household_id),
            )
            if updated.rowcount != 1:
                raise ValueError("household not found")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_household(household_id)

    @_serialized
    def update_member_role(self, household_id: str, account_id: str, role: str, updated_by: str) -> dict[str, str | None]:
        household_id = self._identifier(household_id, "household id")
        account_id = self._identifier(account_id, "account id")
        updated_by = self._identifier(updated_by, "account id")
        role = str(role or "").strip().lower()
        if role not in {"owner", "member", "child", "guest"}:
            raise ValueError("invalid membership role")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            if self.role_for(updated_by, household_id) != "owner":
                raise ValueError("only household owners can manage members")
            current = self.connection.execute(
                "SELECT role FROM memberships WHERE household_id = ? AND account_id = ?",
                (household_id, account_id),
            ).fetchone()
            if current is None:
                raise ValueError("member not found")
            if current["role"] == "owner" and role != "owner":
                owners = self.connection.execute(
                    "SELECT COUNT(*) AS count FROM memberships WHERE household_id = ? AND role = 'owner'",
                    (household_id,),
                ).fetchone()["count"]
                if owners <= 1:
                    raise ValueError("cannot remove the last owner")
            self.connection.execute(
                "UPDATE memberships SET role = ? WHERE household_id = ? AND account_id = ?",
                (role, household_id, account_id),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self._member(household_id, account_id)

    @_serialized
    def remove_member(self, household_id: str, account_id: str, removed_by: str) -> dict[str, str | None]:
        household_id = self._identifier(household_id, "household id")
        account_id = self._identifier(account_id, "account id")
        removed_by = self._identifier(removed_by, "account id")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            if self.role_for(removed_by, household_id) != "owner":
                raise ValueError("only household owners can manage members")
            member = self._member(household_id, account_id)
            if member["role"] == "owner":
                owners = self.connection.execute(
                    "SELECT COUNT(*) AS count FROM memberships WHERE household_id = ? AND role = 'owner'",
                    (household_id,),
                ).fetchone()["count"]
                if owners <= 1:
                    raise ValueError("cannot remove the last owner")
            deleted = self.connection.execute(
                "DELETE FROM memberships WHERE household_id = ? AND account_id = ?",
                (household_id, account_id),
            )
            if deleted.rowcount != 1:
                raise ValueError("member not found")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        member["removed"] = True
        return member

    @_serialized
    def list_invitations(self, household_id: str, *, now: datetime | None = None) -> list[dict[str, str | int | None]]:
        household_id = self._identifier(household_id, "household id")
        current = self._timestamp(now)
        rows = self.connection.execute(
            """SELECT id, email, role, invited_by, expires_at, accepted_at, accepted_account_id,
                      revoked_at, created_at
               FROM invitations WHERE household_id = ? ORDER BY id DESC""",
            (household_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            if item["revoked_at"]:
                status = "revoked"
            elif item["accepted_at"]:
                status = "accepted"
            elif current >= datetime.fromisoformat(str(item["expires_at"])):
                status = "expired"
            else:
                status = "pending"
            item["status"] = status
            item.pop("accepted_account_id", None)
            result.append(item)
        return result

    @_serialized
    def revoke_invitation(self, household_id: str, invitation_id: int, revoked_by: str, *, now: datetime | None = None) -> dict[str, str | int | None]:
        household_id = self._identifier(household_id, "household id")
        revoked_by = self._identifier(revoked_by, "account id")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            if self.role_for(revoked_by, household_id) != "owner":
                raise ValueError("only household owners can manage invitations")
            revoked_at = self._timestamp(now).isoformat()
            updated = self.connection.execute(
                """UPDATE invitations SET revoked_at = ?
                   WHERE id = ? AND household_id = ? AND accepted_at IS NULL AND revoked_at IS NULL""",
                (revoked_at, int(invitation_id), household_id),
            )
            if updated.rowcount != 1:
                raise ValueError("invitation is no longer pending")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        invitations = self.list_invitations(household_id, now=now)
        return next(item for item in invitations if item["id"] == int(invitation_id))

    def _member(self, household_id: str, account_id: str) -> dict[str, str | None]:
        row = self.connection.execute(
            """SELECT accounts.id, accounts.display_name, accounts.email, memberships.role
               FROM memberships JOIN accounts ON accounts.id = memberships.account_id
               WHERE memberships.household_id = ? AND memberships.account_id = ?""",
            (household_id, account_id),
        ).fetchone()
        if row is None:
            raise ValueError("member not found")
        return dict(row)

    def _household_name(self, household_id: str) -> str:
        row = self.connection.execute("SELECT name FROM households WHERE id = ?", (household_id,)).fetchone()
        if row is None:
            raise ValueError("household not found")
        return str(row["name"])

    def _account_by_email(self, email: str) -> dict[str, str | None] | None:
        row = self.connection.execute(
            "SELECT * FROM accounts WHERE lower(email) = lower(?) ORDER BY created_at LIMIT 1",
            (email,),
        ).fetchone()
        return dict(row) if row else None

    @_serialized
    def create_invitation(
        self,
        household_id: str,
        email: str,
        role: str,
        invited_by: str,
        *,
        now: datetime | None = None,
        expires_in: timedelta = timedelta(days=7),
    ) -> dict[str, str | int]:
        household_id = self._identifier(household_id, "household id")
        email = self._email(email)
        role = str(role or "member").strip().lower()
        invited_by = self._identifier(invited_by, "account id")
        if role not in {"member", "child", "guest"}:
            raise ValueError("invalid invitation role")
        if self.role_for(invited_by, household_id) != "owner":
            raise ValueError("only household owners can invite members")
        self._household_name(household_id)
        if expires_in <= timedelta(0) or expires_in > timedelta(days=30):
            raise ValueError("invalid invitation expiry")
        created = self._timestamp(now)
        token = secrets.token_urlsafe(32)
        expires_at = created + expires_in
        cursor = self.connection.execute(
            """INSERT INTO invitations
               (token_hash, household_id, email, role, invited_by, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (self._token_hash(token), household_id, email, role, invited_by, expires_at.isoformat()),
        )
        self.connection.commit()
        return {
            "id": int(cursor.lastrowid),
            "token": token,
            "household_id": household_id,
            "household_name": self._household_name(household_id),
            "email": email,
            "role": role,
            "expires_at": expires_at.isoformat(),
        }

    @_serialized
    def inspect_invitation(self, token: str, *, now: datetime | None = None) -> dict[str, str]:
        token = str(token or "").strip()
        row = self.connection.execute(
            "SELECT * FROM invitations WHERE token_hash = ?",
            (self._token_hash(token),),
        ).fetchone()
        if row is None:
            raise ValueError("invitation not found")
        if row["accepted_at"]:
            raise ValueError("invitation already used")
        if row["revoked_at"]:
            raise ValueError("invitation revoked")
        if self._timestamp(now) >= datetime.fromisoformat(row["expires_at"]):
            raise ValueError("invitation expired")
        result = dict(row)
        result.pop("token_hash", None)
        result["household_name"] = self._household_name(result["household_id"])
        return result

    @_serialized
    def accept_invitation(
        self,
        token: str,
        display_name: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, str]:
        token = str(token or "").strip()
        if not token:
            raise ValueError("invitation not found")
        current = self._timestamp(now)
        accepted_at = current.isoformat()
        token_hash = self._token_hash(token)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                """SELECT invitations.*, households.name AS household_name
                   FROM invitations JOIN households ON households.id = invitations.household_id
                   WHERE invitations.token_hash = ?""",
                (token_hash,),
            ).fetchone()
            if row is None:
                raise ValueError("invitation not found")
            if row["accepted_at"]:
                raise ValueError("invitation already used")
            if row["revoked_at"]:
                raise ValueError("invitation revoked")
            if current >= datetime.fromisoformat(row["expires_at"]):
                raise ValueError("invitation expired")

            account = self._account_by_email(str(row["email"]))
            if account is None:
                account_id = self._account_id_for_email(str(row["email"]))
                self.connection.execute(
                    "INSERT INTO accounts (id, display_name, email) VALUES (?, ?, ?)",
                    (account_id, self._required_text(display_name, "display name"), row["email"]),
                )
                account_name = self._required_text(display_name, "display name")
            else:
                account_id = str(account["id"])
                account_name = str(account["display_name"])
            membership = self.connection.execute(
                "SELECT role FROM memberships WHERE household_id = ? AND account_id = ?",
                (row["household_id"], account_id),
            ).fetchone()
            if membership is None:
                self.connection.execute(
                    "INSERT INTO memberships (household_id, account_id, role) VALUES (?, ?, ?)",
                    (row["household_id"], account_id, row["role"]),
                )
            claimed = self.connection.execute(
                """UPDATE invitations
                   SET accepted_at = ?, accepted_account_id = ?
                   WHERE token_hash = ? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?""",
                (accepted_at, account_id, token_hash, current.isoformat()),
            )
            if claimed.rowcount != 1:
                raise ValueError("invitation already used")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return {
            "account_id": account_id,
            "display_name": account_name,
            "household_id": str(row["household_id"]),
            "household_name": str(row["household_name"]),
            "role": str(membership["role"] if membership is not None else row["role"]),
        }

    @_serialized
    def create_sign_in_token(
        self,
        email: str,
        *,
        household_id: str | None = None,
        now: datetime | None = None,
        expires_in: timedelta = timedelta(minutes=15),
    ) -> dict[str, str]:
        email = self._email(email)
        account = self._account_by_email(email)
        if account is None:
            raise ValueError("account not found")
        memberships = self.connection.execute(
            "SELECT household_id FROM memberships WHERE account_id = ? ORDER BY created_at, household_id",
            (account["id"],),
        ).fetchall()
        if not memberships:
            raise ValueError("household membership required")
        if household_id is None:
            if len(memberships) != 1:
                raise ValueError("household selection required")
            household_id = str(memberships[0]["household_id"])
        else:
            household_id = self._identifier(household_id, "household id")
            if not any(str(row["household_id"]) == household_id for row in memberships):
                raise ValueError("household membership required")
        if expires_in <= timedelta(0) or expires_in > timedelta(hours=1):
            raise ValueError("invalid sign-in expiry")
        token = secrets.token_urlsafe(32)
        expires_at = self._timestamp(now) + expires_in
        self.connection.execute(
            "INSERT INTO auth_tokens (token_hash, account_id, household_id, kind, expires_at) VALUES (?, ?, ?, 'sign_in', ?)",
            (self._token_hash(token), account["id"], household_id, expires_at.isoformat()),
        )
        self.connection.commit()
        return {"token": token, "email": email, "household_id": household_id, "expires_at": expires_at.isoformat()}

    @_serialized
    def inspect_sign_in_token(self, token: str, *, now: datetime | None = None) -> dict[str, str]:
        row = self.connection.execute(
            """SELECT auth_tokens.*, accounts.display_name
               FROM auth_tokens JOIN accounts ON accounts.id = auth_tokens.account_id
               WHERE token_hash = ? AND kind = 'sign_in'""",
            (self._token_hash(str(token or "").strip()),),
        ).fetchone()
        if row is None:
            raise ValueError("sign-in token not found")
        if row["consumed_at"]:
            raise ValueError("sign-in token already used")
        if self._timestamp(now) >= datetime.fromisoformat(row["expires_at"]):
            raise ValueError("sign-in token expired")
        return dict(row)

    @_serialized
    def consume_sign_in_token(self, token: str, *, now: datetime | None = None) -> dict[str, str]:
        token = str(token or "").strip()
        if not token:
            raise ValueError("sign-in token not found")
        current = self._timestamp(now)
        token_hash = self._token_hash(token)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                """SELECT auth_tokens.*, accounts.display_name
                   FROM auth_tokens JOIN accounts ON accounts.id = auth_tokens.account_id
                   WHERE token_hash = ? AND kind = 'sign_in'""",
                (token_hash,),
            ).fetchone()
            if row is None:
                raise ValueError("sign-in token not found")
            if row["consumed_at"]:
                raise ValueError("sign-in token already used")
            if current >= datetime.fromisoformat(row["expires_at"]):
                raise ValueError("sign-in token expired")
            consumed_at = current.isoformat()
            claimed = self.connection.execute(
                """UPDATE auth_tokens SET consumed_at = ?
                   WHERE token_hash = ? AND consumed_at IS NULL AND expires_at > ?""",
                (consumed_at, token_hash, current.isoformat()),
            )
            if claimed.rowcount != 1:
                raise ValueError("sign-in token already used")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return {
            "account_id": str(row["account_id"]),
            "display_name": str(row["display_name"]),
            "household_id": str(row["household_id"]),
            "role": str(self.role_for(str(row["account_id"]), str(row["household_id"]))),
        }

    @_serialized
    def close(self) -> None:
        self.connection.close()
