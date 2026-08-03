from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import UUID


# This is Supabase's publishable client key, intentionally safe for browser use.
# Environment variables remain the preferred override for other deployments.
_DEFAULT_SUPABASE_URL = "https://zcfzdqtjglelrbyhcvcu.supabase.co"
_DEFAULT_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_8TG9k3vZPrIW2NLGeHuH1w_KGzTOgiA"


class SupabaseHTTPError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _config() -> tuple[str, str]:
    url = (os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or _DEFAULT_SUPABASE_URL).strip().rstrip("/")
    key = (os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY") or _DEFAULT_SUPABASE_PUBLISHABLE_KEY).strip()
    if not url or not key:
        raise SupabaseHTTPError(503, "Supabase environment is not configured")
    return url, key


def _json_body(request: BaseHTTPRequestHandler) -> dict:
    try:
        length = int(request.headers.get("Content-Length", "0"))
        payload = json.loads(request.rfile.read(length) or b"{}")
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")
    return payload


def _safe_error(raw: bytes) -> str:
    try:
        payload = json.loads(raw or b"{}")
        return str(payload.get("message") or payload.get("hint") or payload.get("error_description") or "Supabase request failed")[:300]
    except (TypeError, ValueError, json.JSONDecodeError):
        return "Supabase request failed"


def _supabase_request(method: str, path: str, *, token: str | None = None, payload: object | None = None, query: list[tuple[str, str]] | None = None) -> object:
    base_url, publishable_key = _config()
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    headers = {
        "apikey": publishable_key,
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "return=representation"
        body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method=method, headers=headers)
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read()
    except HTTPError as exc:
        raise SupabaseHTTPError(exc.code, _safe_error(exc.read())) from exc
    except URLError as exc:
        raise SupabaseHTTPError(503, "Supabase is unavailable") from exc
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SupabaseHTTPError(502, "Supabase returned invalid JSON") from exc


def _uuid(value: object, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"invalid {field}") from exc


def _rows(value: object) -> list[dict]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]
    return []


class handler(BaseHTTPRequestHandler):  # Vercel's Python runtime discovers this name.
    def _route(self) -> str:
        parsed = urlparse(self.path)
        rewritten = parse_qs(parsed.query).get("route", [""])[0]
        if rewritten:
            return rewritten if rewritten.startswith("/") else f"/{rewritten}"
        path = parsed.path.removeprefix("/api/index.py")
        return path or "/"

    def _token(self) -> str | None:
        value = self.headers.get("Authorization", "")
        if value.lower().startswith("bearer "):
            token = value[7:].strip()
            return token or None
        return None

    def _respond(self, payload: dict, status: int = 200) -> None:
        content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Hearthstate-Household")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.end_headers()
        self.wfile.write(content)

    def _authenticate(self) -> tuple[str, str]:
        token = self._token()
        if token is None:
            raise SupabaseHTTPError(401, "authentication required")
        user = _supabase_request("GET", "/auth/v1/user", token=token)
        if not isinstance(user, dict) or not user.get("id"):
            raise SupabaseHTTPError(401, "authentication required")
        return str(user["id"]), token

    def _memberships(self, user_id: str, token: str) -> list[dict]:
        memberships = _rows(_supabase_request(
            "GET", "/rest/v1/memberships", token=token,
            query=[("select", "household_id,role,created_at"), ("user_id", f"eq.{user_id}"), ("order", "created_at.asc")],
        ))
        result = []
        for membership in memberships:
            household_id = membership.get("household_id")
            if not household_id:
                continue
            households = _rows(_supabase_request(
                "GET", "/rest/v1/households", token=token,
                query=[("select", "id,name,created_at"), ("id", f"eq.{household_id}")],
            ))
            if households:
                result.append({**households[0], "role": membership.get("role"), "membership_created_at": membership.get("created_at")})
        return result

    def _context(self, user_id: str, token: str, *, required: bool = True) -> tuple[str, list[dict]] | None:
        memberships = self._memberships(user_id, token)
        if not memberships:
            if required:
                raise SupabaseHTTPError(409, "household setup required")
            return None
        parsed = urlparse(self.path)
        requested = self.headers.get("X-Hearthstate-Household") or parse_qs(parsed.query).get("household_id", [""])[0]
        household_id = _uuid(requested, "household id") if requested else str(memberships[0]["id"])
        if not any(str(item["id"]) == household_id for item in memberships):
            raise SupabaseHTTPError(403, "household membership required")
        return household_id, memberships

    def _table(self, table: str, household_id: str, token: str, *filters: tuple[str, str], order: str | None = None, limit: int | None = None) -> list[dict]:
        query = [("select", "*") , ("household_id", f"eq.{household_id}")]
        query.extend(filters)
        if order:
            query.append(("order", order))
        if limit is not None:
            query.append(("limit", str(limit)))
        return _rows(_supabase_request("GET", f"/rest/v1/{table}", token=token, query=query))

    def _dashboard(self, household_id: str, user_id: str, token: str) -> dict:
        tasks = self._table("tasks", household_id, token, ("status", "eq.open"), order="due_at.asc.nullsfirst")
        events = self._table("events", household_id, token, ("status", "eq.confirmed"), order="starts_at.asc")
        meals = self._table("meals", household_id, token, ("status", "eq.planned"), order="meal_date.asc")
        groceries = self._table("grocery_items", household_id, token, ("status", "eq.open"), order="category.asc,name.asc")
        inbox = self._table("inbox_items", household_id, token, ("status", "eq.open"), order="created_at.desc", limit=50)
        now = datetime.now(timezone.utc)
        attention = []
        for task in tasks:
            due_at = task.get("due_at")
            urgency = "open"
            if due_at:
                try:
                    due = datetime.fromisoformat(str(due_at).replace("Z", "+00:00"))
                    urgency = "now" if due <= now else ("soon" if due <= now.replace(hour=23, minute=59, second=59) else "open")
                except ValueError:
                    pass
            attention.append({**task, "urgency": urgency})
        calendar = [
            {**event, "source_type": "event", "source_id": event.get("id")}
            for event in events
        ]
        calendar.extend({**task, "source_type": "task", "source_id": task.get("id"), "starts_at": task.get("due_at")} for task in tasks if task.get("due_at"))
        calendar.extend({**meal, "source_type": "meal", "source_id": meal.get("id"), "starts_at": f"{meal.get('meal_date')}T12:00:00+00:00"} for meal in meals)
        calendar.sort(key=lambda item: str(item.get("starts_at") or "9999"))
        return {
            "viewer": user_id,
            "generated_at": now.replace(second=0, microsecond=0).isoformat(),
            "counts": {"attention": len(attention), "today_events": len([item for item in events if str(item.get("starts_at", "")).startswith(now.date().isoformat())]), "groceries": len(groceries), "inbox": len(inbox)},
            "attention": attention[:12],
            "attention_items": attention[:12],
            "tasks": attention,
            "today": [item for item in calendar if str(item.get("starts_at", "")).startswith(now.date().isoformat())],
            "today_items": [item for item in calendar if str(item.get("starts_at", "")).startswith(now.date().isoformat())],
            "upcoming": calendar[:12],
            "calendar": calendar,
            "meals": meals,
            "groceries": groceries,
            "inbox": inbox,
            "grocery_summary": {"items": groceries, "total_count": len(groceries), "priced_count": len([item for item in groceries if item.get("price") is not None]), "unknown_price_count": len([item for item in groceries if item.get("price") is None])},
        }

    def _post_record(self, table: str, household_id: str, user_id: str, token: str, payload: dict) -> dict:
        record = {key: value for key, value in payload.items() if key in {"title", "due_at", "owner", "assignee", "private", "recurrence", "starts_at", "ends_at", "person", "meal_date", "meal_type", "cook", "ingredients", "name", "quantity", "unit", "category", "source", "original_text"}}
        record["household_id"] = household_id
        record["created_by"] = user_id
        rows = _rows(_supabase_request("POST", f"/rest/v1/{table}", token=token, payload=record))
        if not rows:
            raise SupabaseHTTPError(502, "Supabase did not return the created record")
        return rows[0]

    def _handle_get(self, route: str) -> None:
        if route in {"/health", "/api/health"}:
            _supabase_request("GET", "/rest/v1/households", query=[("select", "id"), ("limit", "1")])
            self._respond({"status": "ok", "service": "hearthstate", "backend": "supabase"})
            return
        if route in {"/auth/config", "/api/auth/config"}:
            url, key = _config()
            self._respond({"hosted": True, "supabase_url": url, "supabase_publishable_key": key})
            return
        user_id, token = self._authenticate()
        if route in {"/me", "/api/me"}:
            user = _supabase_request("GET", "/auth/v1/user", token=token)
            self._respond({"user": {"id": user_id, "email": user.get("email") if isinstance(user, dict) else None}, "households": self._memberships(user_id, token)})
            return
        context = self._context(user_id, token)
        assert context is not None
        household_id, memberships = context
        if route in {"/dashboard", "/api/dashboard"}:
            snapshot = self._dashboard(household_id, user_id, token)
            snapshot["household_id"] = household_id
            self._respond(snapshot)
        elif route in {"/inbox", "/api/inbox", "/captures", "/api/captures"}:
            self._respond({"household_id": household_id, "items": self._table("inbox_items", household_id, token, ("status", "eq.open"), order="created_at.desc", limit=100)})
        elif route in {"/tasks", "/api/tasks"}:
            self._respond({"household_id": household_id, "tasks": self._table("tasks", household_id, token, ("status", "eq.open"), order="due_at.asc.nullsfirst")})
        elif route in {"/calendar", "/api/calendar"}:
            self._respond({"household_id": household_id, "events": self._table("events", household_id, token, ("status", "eq.confirmed"), order="starts_at.asc")})
        elif route in {"/meals", "/api/meals"}:
            self._respond({"household_id": household_id, "meals": self._table("meals", household_id, token, ("status", "eq.planned"), order="meal_date.asc")})
        elif route in {"/groceries", "/api/groceries"}:
            items = self._table("grocery_items", household_id, token, ("status", "eq.open"), order="category.asc,name.asc")
            self._respond({"household_id": household_id, "items": items, "total_count": len(items)})
        else:
            self._respond({"error": "not found"}, status=404)

    def _handle_post(self, route: str) -> None:
        payload = _json_body(self)
        if route in {"/households", "/api/households"}:
            _, token = self._authenticate()
            rows = _rows(_supabase_request("POST", "/rest/v1/rpc/create_household", token=token, payload={"household_name": payload.get("name", "")}))
            self._respond({"household": rows[0] if rows else {}}, status=201)
            return
        user_id, token = self._authenticate()
        context = self._context(user_id, token)
        assert context is not None
        household_id, _ = context
        if route in {"/inbox", "/api/inbox", "/captures", "/api/captures"}:
            text = str(payload.get("original_text", "")).strip()
            if not text or len(text) > 4000:
                raise ValueError("original_text is required and must be 4000 characters or fewer")
            if not isinstance(payload.get("private", False), bool):
                raise ValueError("private must be a boolean")
            item = self._post_record("inbox_items", household_id, user_id, token, {"original_text": text, "source": str(payload.get("source", "dashboard")), "private": payload.get("private", False)})
            self._respond({"item": item}, status=201)
        elif route in {"/tasks", "/api/tasks"}:
            title = str(payload.get("title", "")).strip()
            if not title:
                raise ValueError("title is required")
            task = self._post_record("tasks", household_id, user_id, token, payload)
            self._respond({"task": task}, status=201)
        elif route in {"/events", "/api/calendar"}:
            if not str(payload.get("title", "")).strip() or not str(payload.get("starts_at", "")).strip():
                raise ValueError("title and starts_at are required")
            self._respond({"event": self._post_record("events", household_id, user_id, token, payload)}, status=201)
        elif route in {"/meals", "/api/meals"}:
            if not str(payload.get("title", "")).strip() or not str(payload.get("meal_date", "")).strip():
                raise ValueError("title and meal_date are required")
            self._respond({"meal": self._post_record("meals", household_id, user_id, token, payload)}, status=201)
        elif route in {"/groceries", "/api/groceries"}:
            if not str(payload.get("name", "")).strip():
                raise ValueError("name is required")
            self._respond({"item": self._post_record("grocery_items", household_id, user_id, token, payload)}, status=201)
        else:
            self._respond({"error": "not found"}, status=404)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Hearthstate-Household")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._handle_get(self._route())
        except (ValueError, SupabaseHTTPError) as exc:
            status = exc.status if isinstance(exc, SupabaseHTTPError) else 400
            self._respond({"error": str(exc)}, status=status)
        except Exception:
            self._respond({"error": "internal server error"}, status=500)

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._handle_post(self._route())
        except (ValueError, SupabaseHTTPError) as exc:
            status = exc.status if isinstance(exc, SupabaseHTTPError) else 400
            self._respond({"error": str(exc)}, status=status)
        except Exception:
            self._respond({"error": "internal server error"}, status=500)

    def log_message(self, format: str, *args) -> None:
        return
