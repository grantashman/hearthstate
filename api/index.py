from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import UUID


# The publishable key is safe to expose to the browser. Production should still
# set these values in Vercel so the deployment is explicit and portable.
_DEFAULT_SUPABASE_URL = "https://zcfzdqtjglelrbyhcvcu.supabase.co"
_DEFAULT_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_8TG9k3vZPrIW2NLGeHuH1w_KGzTOgiA"
_SESSION_COOKIE = "HearthstateHostedSession"
_SESSION_MAX_AGE = 60 * 60 * 24 * 7
_DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "hearthstate" / "dashboard"


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
        return str(payload.get("message") or payload.get("hint") or payload.get("error_description") or payload.get("msg") or "Supabase request failed")[:300]
    except (TypeError, ValueError, json.JSONDecodeError):
        return "Supabase request failed"


def _supabase_request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: object | None = None,
    query: list[tuple[str, str]] | None = None,
    prefer: str | None = None,
    api_key: str | None = None,
) -> object:
    base_url, publishable_key = _config()
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    headers = {"apikey": api_key or publishable_key, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = prefer or "return=representation"
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


def _supabase_admin_request(method: str, path: str, *, payload: object | None = None, query: list[tuple[str, str]] | None = None, prefer: str | None = None) -> object:
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not service_key:
        raise SupabaseHTTPError(503, "Supabase service role environment is not configured")
    return _supabase_request(method, path, payload=payload, query=query, prefer=prefer, api_key=service_key)


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


def _first(value: object) -> dict | None:
    rows = _rows(value)
    return rows[0] if rows else None


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _format_time(value: object) -> str:
    parsed = _parse_datetime(value)
    return parsed.strftime("%-I:%M %p") if parsed else ""


def _format_day(value: object, now: datetime) -> str:
    parsed = _parse_datetime(value)
    if not parsed:
        return ""
    if parsed.date() == now.date():
        return "Today"
    return parsed.strftime("%a %-d %b")


class handler(BaseHTTPRequestHandler):  # Vercel's Python runtime discovers this name.
    def _route(self) -> str:
        parsed = urlparse(self.path)
        rewritten = parse_qs(parsed.query).get("route", [""])[0]
        if rewritten:
            route = rewritten if rewritten.startswith("/") else f"/{rewritten}"
        else:
            route = parsed.path.removeprefix("/api/index.py") or "/"
        if route.startswith("/api/"):
            route = route.removeprefix("/api")
        return route or "/"

    def _query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.path).query)

    def _token(self) -> str | None:
        value = self.headers.get("Authorization", "")
        if value.lower().startswith("bearer "):
            token = value[7:].strip()
            if token:
                return token
        cookies = SimpleCookie(self.headers.get("Cookie", ""))
        hosted = cookies.get(_SESSION_COOKIE)
        return hosted.value if hosted and hosted.value else None

    def _respond(self, payload: object, status: int = 200, headers: dict[str, str] | None = None) -> None:
        content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Hearthstate-Household")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def _send_bytes(self, content: bytes, content_type: str, *, cache_control: str = "no-cache", status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _authenticate(self, token: str | None = None) -> tuple[str, str, dict]:
        access_token = token or self._token()
        if not access_token:
            raise SupabaseHTTPError(401, "authentication required")
        user = _supabase_request("GET", "/auth/v1/user", token=access_token)
        if not isinstance(user, dict) or not user.get("id"):
            raise SupabaseHTTPError(401, "authentication required")
        self._upsert_profile(str(user["id"]), str(user.get("email") or ""), user, access_token)
        return str(user["id"]), access_token, user

    def _upsert_profile(self, user_id: str, email: str, user: dict | None = None, token: str | None = None) -> None:
        metadata = (user or {}).get("user_metadata") or {}
        display_name = str(metadata.get("display_name") or metadata.get("full_name") or email.split("@", 1)[0] or "Household member").strip()[:120]
        try:
            _supabase_request(
                "POST", "/rest/v1/profiles", token=token or self._token(),
                query=[("on_conflict", "user_id")],
                payload={"user_id": user_id, "email": email or None, "display_name": display_name},
                prefer="return=minimal,resolution=merge-duplicates",
            )
        except SupabaseHTTPError:
            # Profile sync must not prevent an otherwise valid Auth session.
            return

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
            household = _first(_supabase_request(
                "GET", "/rest/v1/households", token=token,
                query=[("select", "id,name,created_at"), ("id", f"eq.{household_id}")],
            ))
            if household:
                result.append({**household, "role": membership.get("role"), "membership_created_at": membership.get("created_at")})
        return result

    def _context(self, user_id: str, token: str, *, required: bool = True) -> tuple[str, list[dict]] | None:
        memberships = self._memberships(user_id, token)
        if not memberships:
            if required:
                raise SupabaseHTTPError(409, "household setup required")
            return None
        requested = self.headers.get("X-Hearthstate-Household") or self._query().get("household_id", [""])[0]
        household_id = _uuid(requested, "household id") if requested else str(memberships[0]["id"])
        if not any(str(item["id"]) == household_id for item in memberships):
            raise SupabaseHTTPError(403, "household membership required")
        return household_id, memberships

    def _role(self, household_id: str, user_id: str, token: str) -> str:
        row = _first(_supabase_request("GET", "/rest/v1/memberships", token=token, query=[("select", "role"), ("household_id", f"eq.{household_id}"), ("user_id", f"eq.{user_id}")]))
        return str(row.get("role")) if row else ""

    def _table(self, table: str, household_id: str, token: str, *filters: tuple[str, str], order: str | None = None, limit: int | None = None) -> list[dict]:
        query = [("select", "*") , ("household_id", f"eq.{household_id}")]
        query.extend(filters)
        if order:
            query.append(("order", order))
        if limit is not None:
            query.append(("limit", str(limit)))
        return _rows(_supabase_request("GET", f"/rest/v1/{table}", token=token, query=query))

    def _profile_map(self, user_ids: set[str], token: str) -> dict[str, dict]:
        profiles: dict[str, dict] = {}
        for user_id in sorted(item for item in user_ids if item):
            row = _first(_supabase_request("GET", "/rest/v1/profiles", token=token, query=[("select", "user_id,email,display_name"), ("user_id", f"eq.{user_id}")]))
            if row:
                profiles[user_id] = row
        return profiles

    def _enrich_rows(self, rows: list[dict], token: str) -> list[dict]:
        ids = set()
        for row in rows:
            for key in ("owner", "assignee", "cook", "created_by", "actor"):
                value = row.get(key)
                if value:
                    ids.add(str(value))
        profiles = self._profile_map(ids, token)
        for row in rows:
            for key in ("owner", "assignee", "cook", "created_by", "actor"):
                value = row.get(key)
                if value:
                    profile = profiles.get(str(value), {})
                    row[f"{key}_label"] = profile.get("display_name") or str(value)
        return rows

    def _record_payload(self, table: str, payload: dict, user_id: str, household_id: str) -> dict:
        fields = {
            "inbox_items": {"original_text", "source", "private", "status"},
            "tasks": {"title", "due_at", "owner", "assignee", "private", "recurrence", "status"},
            "events": {"title", "starts_at", "ends_at", "person", "assignee", "status"},
            "meals": {"meal_date", "meal_type", "title", "cook", "status", "ingredients"},
            "grocery_items": {"name", "quantity", "unit", "category", "price", "price_source", "price_url", "price_checked_at", "price_confidence", "price_note", "status"},
            "recipes": {"source", "source_policy", "title", "source_url", "image_url", "summary", "tags", "prep_minutes", "cook_minutes", "ingredients"},
            "chore_templates": {"title", "cadence", "participants", "next_index", "active"},
        }.get(table, set())
        record = {key: value for key, value in payload.items() if key in fields}
        record["household_id"] = household_id
        record["created_by"] = user_id
        return record

    def _post_record(self, table: str, household_id: str, user_id: str, token: str, payload: dict) -> dict:
        record = self._record_payload(table, payload, user_id, household_id)
        rows = _rows(_supabase_request("POST", f"/rest/v1/{table}", token=token, payload=record))
        if not rows:
            raise SupabaseHTTPError(502, "Supabase did not return the created record")
        return rows[0]

    def _patch_record(self, table: str, record_id: object, household_id: str, token: str, payload: dict) -> dict:
        identifier = _uuid(record_id, f"{table} id")
        allowed = {
            "tasks": {"title", "due_at", "owner", "assignee", "private", "recurrence", "status"},
            "events": {"title", "starts_at", "ends_at", "person", "assignee", "status"},
            "meals": {"meal_date", "meal_type", "title", "cook", "status", "ingredients"},
            "grocery_items": {"name", "quantity", "unit", "category", "price", "price_source", "price_url", "price_checked_at", "price_confidence", "price_note", "status"},
        }.get(table, set())
        record = {key: value for key, value in payload.items() if key in allowed}
        rows = _rows(_supabase_request("PATCH", f"/rest/v1/{table}", token=token, query=[("id", f"eq.{identifier}"), ("household_id", f"eq.{household_id}")], payload=record))
        if not rows:
            raise SupabaseHTTPError(404, f"{table} record not found")
        return rows[0]

    def _delete_record(self, table: str, record_id: object, household_id: str, token: str) -> str:
        identifier = _uuid(record_id, f"{table} id")
        _supabase_request("DELETE", f"/rest/v1/{table}", token=token, query=[("id", f"eq.{identifier}"), ("household_id", f"eq.{household_id}")])
        return identifier

    def _log(self, household_id: str, user_id: str, token: str, action: str, entity_type: str, entity_id: str | None = None, before: dict | None = None, after: dict | None = None) -> None:
        try:
            _supabase_request("POST", "/rest/v1/activity_log", token=token, payload={"household_id": household_id, "actor": user_id, "action": action, "entity_type": entity_type, "entity_id": entity_id, "before_json": before, "after_json": after})
        except SupabaseHTTPError:
            return

    def _grocery_snapshot(self, household_id: str, token: str) -> dict:
        items = self._table("grocery_items", household_id, token, ("status", "eq.open"), order="category.asc,name.asc")
        settings = _first(_supabase_request("GET", "/rest/v1/planner_settings", token=token, query=[("select", "weekly_budget,updated_at"), ("household_id", f"eq.{household_id}")])) or {}
        budget = settings.get("weekly_budget")
        total = round(sum(float(item.get("price") or 0) * float(item.get("quantity") or 1) for item in items), 2)
        remaining = round(float(budget) - total, 2) if budget is not None else None
        for item in items:
            if item.get("price") is not None:
                item["line_total"] = round(float(item["price"]) * float(item.get("quantity") or 1), 2)
            else:
                item["line_total"] = None
        return {
            "items": items,
            "total_count": len(items),
            "priced_count": sum(1 for item in items if item.get("price") is not None),
            "unknown_price_count": sum(1 for item in items if item.get("price") is None),
            "budget": float(budget) if budget is not None else None,
            "total": total,
            "priced_total": total,
            "remaining": remaining,
            "over_budget": remaining is not None and remaining < 0,
            "updated_at": settings.get("updated_at"),
        }

    def _calendar_items(self, household_id: str, token: str, now: datetime) -> list[dict]:
        events = self._enrich_rows(self._table("events", household_id, token, ("status", "eq.confirmed"), order="starts_at.asc"), token)
        tasks = self._enrich_rows(self._table("tasks", household_id, token, ("status", "eq.open"), order="due_at.asc.nullsfirst"), token)
        meals = self._enrich_rows(self._table("meals", household_id, token, ("status", "eq.planned"), order="meal_date.asc"), token)
        items = []
        for event in events:
            items.append({**event, "source_type": "event", "source_id": event["id"], "time_label": _format_time(event.get("starts_at")), "day_label": _format_day(event.get("starts_at"), now), "recurrence": "none", "recurrence_label": "Does not repeat"})
        for task in tasks:
            if task.get("due_at"):
                items.append({**task, "source_type": "task", "source_id": task["id"], "starts_at": task["due_at"], "time_label": _format_time(task.get("due_at")), "day_label": _format_day(task.get("due_at"), now), "recurrence_label": task.get("recurrence", "none")})
        for meal in meals:
            starts_at = f"{meal.get('meal_date')}T12:00:00+00:00"
            items.append({**meal, "source_type": "meal", "source_id": meal["id"], "starts_at": starts_at, "time_label": "Dinner", "day_label": _format_day(starts_at, now), "person": meal.get("cook_label") or meal.get("cook")})
        return sorted(items, key=lambda item: (str(item.get("starts_at") or "9999"), item.get("source_type", ""), str(item.get("id"))))

    def _dashboard(self, household_id: str, user_id: str, token: str, user: dict) -> dict:
        now = datetime.now(timezone.utc)
        tasks = self._enrich_rows(self._table("tasks", household_id, token, ("status", "eq.open"), order="due_at.asc.nullsfirst"), token)
        events = self._table("events", household_id, token, ("status", "eq.confirmed"), order="starts_at.asc")
        meals = self._table("meals", household_id, token, ("status", "eq.planned"), order="meal_date.asc")
        inbox = self._table("inbox_items", household_id, token, ("status", "eq.open"), order="created_at.desc", limit=50)
        groceries = self._grocery_snapshot(household_id, token)
        profile = _first(_supabase_request("GET", "/rest/v1/profiles", token=token, query=[("select", "display_name"), ("user_id", f"eq.{user_id}")])) or {}
        attention = []
        for task in tasks:
            due = _parse_datetime(task.get("due_at"))
            urgency = "now" if due and due <= now else "soon" if due and due <= now + timedelta(days=1) else "open"
            attention.append({**task, "urgency": urgency, "owner_label": task.get("owner_label") or "Unassigned", "meta_label": task.get("assignee_label") or task.get("owner_label") or "Unassigned", "due_label": _format_day(task.get("due_at"), now) if due else "No due date", "action_type": "complete", "action_label": "Mark done", "href": f"/tasks?edit={task.get('id')}"})
        calendar = self._calendar_items(household_id, token, now)
        today = [item for item in calendar if str(item.get("starts_at", "")).startswith(now.date().isoformat())]
        upcoming = [item for item in calendar if now.date().isoformat() < str(item.get("starts_at", ""))[:10] <= (now + timedelta(days=7)).date().isoformat()]
        planning_week = []
        for offset in range(7):
            day = (now + timedelta(days=offset)).date()
            day_items = [item for item in calendar if str(item.get("starts_at", ""))[:10] == day.isoformat()]
            dinner = next((item for item in meals if item.get("meal_date") == day.isoformat() and item.get("meal_type") == "dinner"), None)
            planning_week.append({"date": day.isoformat(), "short_label": day.strftime("%a"), "day_number": day.strftime("%-d"), "dinner": dinner, "items": day_items})
        role = self._role(household_id, user_id, token)
        return {
            "viewer": user_id,
            "viewer_name": profile.get("display_name") or user.get("email", "Household member").split("@", 1)[0].title(),
            "viewer_role": role.title() if role else "Household member",
            "generated_at": now.replace(second=0, microsecond=0).isoformat(),
            "counts": {"attention": len(attention), "today_events": len([item for item in today if item.get("source_type") == "event"]), "groceries": groceries["total_count"], "inbox": len(inbox)},
            "attention": attention[:8], "attention_items": attention[:12], "tasks": tasks,
            "today": [item for item in today if item.get("source_type") == "event"], "today_items": today,
            "upcoming": upcoming[:8], "planning_week": planning_week, "calendar": calendar,
            "grocery_summary": groceries, "groceries": groceries["items"][:12], "inbox": inbox[:12],
        }

    def _admin(self, household_id: str, user_id: str, token: str) -> dict:
        members = _rows(_supabase_request("GET", "/rest/v1/memberships", token=token, query=[("select", "user_id,role,created_at"), ("household_id", f"eq.{household_id}"), ("order", "created_at.asc")]))
        profile_map = self._profile_map({str(member.get("user_id")) for member in members}, token)
        rendered_members = [{"id": member.get("user_id"), "role": member.get("role"), "created_at": member.get("created_at"), "display_name": profile_map.get(str(member.get("user_id")), {}).get("display_name") or str(member.get("user_id")), "email": profile_map.get(str(member.get("user_id")), {}).get("email")} for member in members]
        invitations = self._table("invitations", household_id, token, order="created_at.desc")
        now = datetime.now(timezone.utc)
        for invitation in invitations:
            invitation["status"] = "revoked" if invitation.get("revoked_at") else "accepted" if invitation.get("accepted_at") else "expired" if (_parse_datetime(invitation.get("expires_at")) or now) <= now else "pending"
            invitation.pop("token_hash", None)
        household = _first(_supabase_request("GET", "/rest/v1/households", token=token, query=[("select", "id,name,created_at"), ("id", f"eq.{household_id}")])) or {}
        return {"household": household, "members": rendered_members, "invitations": invitations}

    def _handle_asset(self, route: str) -> bool:
        pages = {
            "/login": ("hosted-login.html", "text/html; charset=utf-8", False),
            "/setup": ("hosted.html", "text/html; charset=utf-8", False),
            "/invite": ("invite.html", "text/html; charset=utf-8", False),
            "/index.html": ("index.html", "text/html; charset=utf-8", True),
            "/calendar": ("calendar.html", "text/html; charset=utf-8", True), "/calendar/": ("calendar.html", "text/html; charset=utf-8", True),
            "/tasks": ("tasks.html", "text/html; charset=utf-8", True), "/tasks/": ("tasks.html", "text/html; charset=utf-8", True),
            "/meals": ("meals.html", "text/html; charset=utf-8", True), "/meals/": ("meals.html", "text/html; charset=utf-8", True),
            "/groceries": ("groceries.html", "text/html; charset=utf-8", True), "/groceries/": ("groceries.html", "text/html; charset=utf-8", True),
            "/recipes": ("recipes.html", "text/html; charset=utf-8", True), "/recipes/": ("recipes.html", "text/html; charset=utf-8", True),
            "/admin": ("admin.html", "text/html; charset=utf-8", True), "/admin/": ("admin.html", "text/html; charset=utf-8", True),
            "/notifications": ("notifications.html", "text/html; charset=utf-8", True), "/notifications/": ("notifications.html", "text/html; charset=utf-8", True),
        }
        assets = {name: (name, content_type, False) for name, content_type in {
            "login.js": "text/javascript; charset=utf-8", "invite.js": "text/javascript; charset=utf-8", "nav.js": "text/javascript; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "section.js": "text/javascript; charset=utf-8", "meals.js": "text/javascript; charset=utf-8", "groceries.js": "text/javascript; charset=utf-8", "recipes.js": "text/javascript; charset=utf-8", "admin.js": "text/javascript; charset=utf-8", "notifications.js": "text/javascript; charset=utf-8", "styles.css": "text/css; charset=utf-8", "favicon.svg": "image/svg+xml"}.items()}
        if route == "/":
            if not self._token():
                filename, content_type, protected = "hosted-login.html", "text/html; charset=utf-8", False
            else:
                try:
                    user_id, token, _ = self._authenticate()
                    filename, content_type, protected = ("index.html", "text/html; charset=utf-8", True) if self._memberships(user_id, token) else ("hosted.html", "text/html; charset=utf-8", False)
                except SupabaseHTTPError:
                    filename, content_type, protected = "hosted-login.html", "text/html; charset=utf-8", False
            self._send_bytes((_DASHBOARD_DIR / filename).read_bytes(), content_type)
            return True
        if route == "/setup" and self._token():
            try:
                user_id, token, _ = self._authenticate()
                if self._memberships(user_id, token):
                    self._redirect("/")
                    return True
            except SupabaseHTTPError:
                self._redirect("/login")
                return True
        asset = pages.get(route) or assets.get(route.removeprefix("/"))
        if asset is None and route.startswith("/recipe-images/"):
            filename = Path(route.removeprefix("/recipe-images/")).name
            if filename != route.removeprefix("/recipe-images/") or Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                return False
            image = _DASHBOARD_DIR / "recipe-images" / filename
            if image.is_file():
                self._send_bytes(image.read_bytes(), {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[image.suffix.lower()], cache_control="public, max-age=86400")
                return True
            return False
        if asset is None:
            return False
        filename, content_type, protected = asset
        if protected and not self._token():
            self._redirect("/login")
            return True
        if route == "/admin" and self._token():
            try:
                user_id, token, _ = self._authenticate()
                context = self._context(user_id, token)
                if context and self._role(context[0], user_id, token) != "owner":
                    self._redirect("/")
                    return True
            except SupabaseHTTPError:
                self._redirect("/login")
                return True
        self._send_bytes((_DASHBOARD_DIR / filename).read_bytes(), content_type)
        return True

    def _handle_get(self, route: str) -> None:
        if self._handle_asset(route):
            return
        if route == "/health":
            _supabase_request("GET", "/rest/v1/households", query=[("select", "id"), ("limit", "1")])
            self._respond({"status": "ok", "service": "hearthstate", "backend": "supabase"})
            return
        if route == "/auth/config":
            url, key = _config()
            self._respond({"hosted": True, "account_backed": True, "supabase_url": url, "supabase_publishable_key": key})
            return
        if route == "/auth/invitations/inspect":
            token = self._query().get("token", [""])[0].strip()
            if not token:
                raise ValueError("invitation token is required")
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            invitation = _first(_supabase_admin_request("GET", "/rest/v1/invitations", query=[("select", "email,role,household_id,expires_at"), ("token_hash", f"eq.{token_hash}"), ("revoked_at", "is.null"), ("accepted_at", "is.null")]))
            if not invitation:
                raise SupabaseHTTPError(404, "invitation is invalid or expired")
            if (_parse_datetime(invitation.get("expires_at")) or datetime.now(timezone.utc)) <= datetime.now(timezone.utc):
                raise SupabaseHTTPError(404, "invitation is invalid or expired")
            household = _first(_supabase_admin_request("GET", "/rest/v1/households", query=[("select", "name"), ("id", f"eq.{invitation['household_id']}")])) or {}
            invitation["household_name"] = household.get("name")
            self._respond({"invitation": invitation})
            return
        user_id, token, user = self._authenticate()
        if route == "/me":
            self._respond({"user": {"id": user_id, "email": user.get("email")}, "households": self._memberships(user_id, token)})
            return
        if route == "/households":
            self._respond({"households": self._memberships(user_id, token)})
            return
        context = self._context(user_id, token)
        assert context is not None
        household_id, _ = context
        if route == "/dashboard":
            self._respond({**self._dashboard(household_id, user_id, token, user), "household_id": household_id})
        elif route == "/inbox":
            self._respond({"viewer": user_id, "items": self._table("inbox_items", household_id, token, ("status", "eq.open"), order="created_at.desc", limit=100), "generated_at": _iso_now()})
        elif route == "/activity":
            rows = self._table("activity_log", household_id, token, order="created_at.desc", limit=100)
            self._respond({"viewer": user_id, "activity": rows})
        elif route == "/conflicts":
            events = self._table("events", household_id, token, ("status", "eq.confirmed"), order="starts_at.asc")
            conflicts = []
            for index, left in enumerate(events):
                left_start = _parse_datetime(left.get("starts_at")); left_end = _parse_datetime(left.get("ends_at")) or (left_start + timedelta(hours=1) if left_start else None)
                for right in events[index + 1:]:
                    right_start = _parse_datetime(right.get("starts_at")); right_end = _parse_datetime(right.get("ends_at")) or (right_start + timedelta(hours=1) if right_start else None)
                    if left_start and left_end and right_start and right_end and left_start < right_end and right_start < left_end and (left.get("assignee") or left.get("person")) == (right.get("assignee") or right.get("person")):
                        conflicts.append({"title": f"{left.get('title')} · {right.get('title')}", "assignee": left.get("assignee") or left.get("person") or "Household"})
            self._respond({"conflicts": conflicts})
        elif route == "/chores":
            self._respond({"chores": self._table("chore_templates", household_id, token, ("active", "eq.true"), order="created_at.asc")})
        elif route == "/groceries":
            self._respond({**self._grocery_snapshot(household_id, token), "generated_at": _iso_now()})
        elif route == "/recipes":
            query = self._query(); recipes = self._table("recipes", household_id, token, order="created_at.desc")
            search = (query.get("search", [""])[0] or "").lower().strip(); tag = query.get("tag", [""])[0].lower().strip()
            saved = {str(row.get("recipe_id")) for row in _rows(_supabase_request("GET", "/rest/v1/saved_recipes", token=token, query=[("select", "recipe_id"), ("user_id", f"eq.{user_id}")]))}
            filtered = []
            for recipe in recipes:
                recipe["tags"] = recipe.get("tags") if isinstance(recipe.get("tags"), list) else []
                recipe["ingredients"] = recipe.get("ingredients") if isinstance(recipe.get("ingredients"), list) else []
                recipe["saved"] = str(recipe.get("id")) in saved
                haystack = f"{recipe.get('title', '')} {recipe.get('summary', '')} {' '.join(recipe['tags'])}".lower()
                if search and search not in haystack: continue
                if tag == "saved" and not recipe["saved"]: continue
                if tag and tag != "saved" and tag not in recipe["tags"]: continue
                filtered.append(recipe)
            self._respond({"recipes": filtered, "generated_at": _iso_now()})
        elif route == "/tasks":
            self._respond({"viewer": user_id, "generated_at": _iso_now(), "tasks": self._enrich_rows(self._table("tasks", household_id, token, ("status", "eq.open"), order="due_at.asc.nullsfirst"), token)})
        elif route == "/calendar":
            self._respond({"viewer": user_id, "generated_at": _iso_now(), "calendar": self._calendar_items(household_id, token, datetime.now(timezone.utc))})
        elif route == "/meals":
            meals = self._enrich_rows(self._table("meals", household_id, token, order="meal_date.asc"), token)
            self._respond({"generated_at": _iso_now(), "meals": meals})
        elif route == "/notifications/preferences":
            briefing_type = self._query().get("briefing_type", ["morning"])[0].lower() or "morning"
            preferences = _first(_supabase_request("GET", "/rest/v1/notification_preferences", token=token, query=[("select", "*"), ("household_id", f"eq.{household_id}"), ("user_id", f"eq.{user_id}"), ("briefing_type", f"eq.{briefing_type}")])) or {"household_id": household_id, "user_id": user_id, "briefing_type": briefing_type, "enabled": True, "preferred_time": "07:00", "quiet_start": "21:00", "quiet_end": "07:00", "channel": "email"}
            self._respond({"preferences": preferences})
        elif route == "/admin":
            if self._role(household_id, user_id, token) != "owner": raise SupabaseHTTPError(403, "owner access required")
            self._respond(self._admin(household_id, user_id, token))
        else:
            self._respond({"error": "not found"}, status=404)

    def _handle_post(self, route: str) -> None:
        payload = _json_body(self)
        if route in {"/auth/session", "/auth/sign-in/session"}:
            supplied = str(payload.get("access_token") or "").strip()
            user_id, token, user = self._authenticate(supplied or None)
            self._respond({"user": {"id": user_id, "email": user.get("email")}, "households": self._memberships(user_id, token)}, headers={"Set-Cookie": f"{_SESSION_COOKIE}={token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={_SESSION_MAX_AGE}"})
            return
        if route in {"/auth/sign-out", "/auth/logout"}:
            self._respond({"ok": True}, headers={"Set-Cookie": f"{_SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0"})
            return
        if route == "/auth/invitations/accept":
            user_id, token, user = self._authenticate()
            raw_token = str(payload.get("token", "")).strip()
            if not raw_token: raise ValueError("invitation token is required")
            token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            invitation = _first(_supabase_admin_request("GET", "/rest/v1/invitations", query=[("select", "id,household_id,email,role,expires_at,accepted_at,revoked_at"), ("token_hash", f"eq.{token_hash}")]))
            if not invitation or invitation.get("accepted_at") or invitation.get("revoked_at") or (_parse_datetime(invitation.get("expires_at")) or datetime.now(timezone.utc)) <= datetime.now(timezone.utc):
                raise SupabaseHTTPError(400, "invitation is invalid or expired")
            if str(invitation.get("email", "")).lower() != str(user.get("email", "")).lower():
                raise SupabaseHTTPError(403, "invitation email does not match sign-in email")
            membership = _first(_supabase_admin_request("POST", "/rest/v1/memberships", payload={"household_id": invitation["household_id"], "user_id": user_id, "role": invitation["role"]}, prefer="return=representation,resolution=merge-duplicates", query=[("on_conflict", "household_id,user_id")])) or {}
            _supabase_admin_request("PATCH", "/rest/v1/invitations", query=[("id", f"eq.{invitation['id']}")], payload={"accepted_at": _iso_now(), "accepted_user_id": user_id})
            display_name = str(payload.get("display_name", "")).strip() or str(user.get("email", "Household member")).split("@", 1)[0]
            _supabase_admin_request("POST", "/rest/v1/profiles", query=[("on_conflict", "user_id")], payload={"user_id": user_id, "email": user.get("email"), "display_name": display_name}, prefer="return=minimal,resolution=merge-duplicates")
            self._respond({"membership": membership or {}}, status=201)
            return
        if route == "/households":
            user_id, token, _ = self._authenticate()
            name = str(payload.get("name", "")).strip()
            if not name: raise ValueError("household name is required")
            household = _first(_supabase_request("POST", "/rest/v1/rpc/create_household", token=token, payload={"household_name": name}))
            self._respond({"household": household or {}}, status=201)
            return
        user_id, token, user = self._authenticate()
        context = self._context(user_id, token)
        assert context is not None
        household_id, _ = context

        if route == "/inbox":
            text = str(payload.get("original_text", "")).strip()
            if not text or len(text) > 4000: raise ValueError("original_text is required and must be 4000 characters or fewer")
            if not isinstance(payload.get("private", False), bool): raise ValueError("private must be a boolean")
            item = self._post_record("inbox_items", household_id, user_id, token, {"original_text": text, "source": str(payload.get("source", "dashboard")), "private": payload.get("private", False)})
            self._log(household_id, user_id, token, "inbox.created", "inbox", item.get("id"), after=item)
            self._respond({"item": item}, status=201)
            return
        if route.startswith("/inbox/"):
            parts = route.removeprefix("/inbox/").strip("/").split("/")
            if len(parts) != 2 or parts[1] not in {"archive", "convert"}: self._respond({"error": "not found"}, status=404); return
            item_id = _uuid(parts[0], "inbox id")
            if parts[1] == "archive":
                item = self._patch_record("inbox_items", item_id, household_id, token, {"status": "archived"})
                self._respond({"item": item}); return
            conversion = str(payload.get("type", "")).lower().strip()
            table_by_type = {"task": "tasks", "event": "events", "meal": "meals", "grocery": "grocery_items"}
            table = table_by_type.get(conversion)
            if not table: raise ValueError("unsupported conversion type")
            created = self._post_record(table, household_id, user_id, token, payload)
            item = self._patch_record("inbox_items", item_id, household_id, token, {"status": "converted"})
            self._respond({conversion: created, "item": item}, status=201); return
        if route == "/activity/undo":
            self._respond({"undone": None}); return
        if route == "/chores":
            title = str(payload.get("title", "")).strip(); participants = payload.get("participants", [])
            if not title: raise ValueError("title is required")
            if not isinstance(participants, list): raise ValueError("participants must be a list")
            chore = self._post_record("chore_templates", household_id, user_id, token, {"title": title, "cadence": str(payload.get("cadence", "weekly")), "participants": participants})
            self._respond({"chore": chore}, status=201); return
        if route.startswith("/chores/"):
            chore_id = _uuid(route.removeprefix("/chores/").strip("/"), "chore id")
            chore = _first(_supabase_request("GET", "/rest/v1/chore_templates", token=token, query=[("select", "*"), ("id", f"eq.{chore_id}"), ("household_id", f"eq.{household_id}")]))
            if not chore: raise SupabaseHTTPError(404, "chore not found")
            participants = chore.get("participants") if isinstance(chore.get("participants"), list) else []
            assignee = participants[int(chore.get("next_index", 0)) % len(participants)] if participants else None
            task = self._post_record("tasks", household_id, user_id, token, {"title": chore["title"], "due_at": payload.get("due_date"), "assignee": assignee})
            _supabase_request("PATCH", "/rest/v1/chore_templates", token=token, query=[("id", f"eq.{chore_id}")], payload={"next_index": int(chore.get("next_index", 0)) + 1})
            self._respond({"task": task}, status=201); return
        if route == "/groceries/budget":
            budget = float(payload.get("budget"))
            if budget < 0: raise ValueError("budget must not be negative")
            _supabase_request("POST", "/rest/v1/planner_settings", token=token, query=[("on_conflict", "household_id")], payload={"household_id": household_id, "weekly_budget": budget, "updated_by": user_id}, prefer="return=minimal,resolution=merge-duplicates")
            self._respond(self._grocery_snapshot(household_id, token)); return
        if route == "/groceries/price":
            item_id = _uuid(payload.get("item_id"), "grocery item id")
            item = self._patch_record("grocery_items", item_id, household_id, token, {"price": float(payload.get("price")), "price_source": payload.get("source", "Manual entry"), "price_url": payload.get("url"), "price_confidence": payload.get("confidence", "manual"), "price_checked_at": payload.get("checked_at", _iso_now()), "price_note": payload.get("note", "Entered by household")})
            self._respond({"item": item}); return
        if route == "/groceries/item":
            item_id = _uuid(payload.get("item_id"), "grocery item id")
            self._respond({"item": self._patch_record("grocery_items", item_id, household_id, token, {key: payload[key] for key in ("quantity", "unit", "category") if key in payload})}); return
        if route == "/groceries/refresh-coles":
            self._respond({"updated": 0, **self._grocery_snapshot(household_id, token)}); return
        if route == "/recipes/import":
            title = str(payload.get("title", "")).strip(); source_url = str(payload.get("source_url", "user://recipe")).strip()
            if not title: raise ValueError("title is required")
            if not (source_url.startswith(("https://", "http://", "user://"))): raise ValueError("source_url must use http(s) or user://")
            ingredients = [item for item in payload.get("ingredients", []) if isinstance(item, dict) and str(item.get("name", "")).strip()]
            recipe = self._post_record("recipes", household_id, user_id, token, {**payload, "source": "user_supplied", "source_policy": "user_supplied", "source_url": source_url, "tags": [str(tag).strip() for tag in payload.get("tags", []) if str(tag).strip()], "ingredients": ingredients})
            self._respond({"recipe": recipe, "added": []}, status=201); return
        if route.startswith("/recipes/"):
            parts = route.removeprefix("/recipes/").strip("/").split("/")
            if len(parts) != 2: self._respond({"error": "not found"}, status=404); return
            recipe_id, action = _uuid(parts[0], "recipe id"), parts[1]
            if action == "save":
                saved = bool(payload.get("saved", True))
                if saved:
                    _supabase_request("POST", "/rest/v1/saved_recipes", token=token, payload={"recipe_id": recipe_id, "user_id": user_id}, query=[("on_conflict", "recipe_id,user_id")], prefer="return=minimal,resolution=merge-duplicates")
                else:
                    _supabase_request("DELETE", "/rest/v1/saved_recipes", token=token, query=[("recipe_id", f"eq.{recipe_id}"), ("user_id", f"eq.{user_id}")])
                self._respond({"saved": saved}); return
            recipe = _first(_supabase_request("GET", "/rest/v1/recipes", token=token, query=[("select", "*"), ("id", f"eq.{recipe_id}"), ("household_id", f"eq.{household_id}")]))
            if not recipe: raise SupabaseHTTPError(404, "recipe not found")
            if action == "plan":
                meal = self._post_record("meals", household_id, user_id, token, {"meal_date": str(payload.get("meal_date", "")).strip(), "meal_type": str(payload.get("meal_type", "dinner")), "title": recipe["title"], "cook": payload.get("cook"), "ingredients": recipe.get("ingredients", [])})
                self._respond({"meal": meal, "added": []}, status=201); return
            if action == "shopping-list":
                ingredients = recipe.get("ingredients") if isinstance(recipe.get("ingredients"), list) else []
                added = [self._post_record("grocery_items", household_id, user_id, token, {"name": str(item.get("name")), "quantity": float(item.get("quantity") or 1) if str(item.get("quantity") or "1").replace(".", "", 1).isdigit() else 1, "unit": item.get("unit") or "each", "category": "Recipe"}) for item in ingredients if isinstance(item, dict) and item.get("name")]
                self._respond({"added": added}); return
        if route.startswith("/tasks/"):
            parts = route.removeprefix("/tasks/").strip("/").split("/")
            if len(parts) != 2 or parts[1] not in {"complete", "delete"}: self._respond({"error": "not found"}, status=404); return
            task_id = _uuid(parts[0], "task id")
            if parts[1] == "complete":
                task = self._patch_record("tasks", task_id, household_id, token, {"status": "done"}); self._respond({"task": task})
            else:
                deleted = self._delete_record("tasks", task_id, household_id, token); self._respond({"deleted": deleted})
            return
        if route == "/tasks":
            title = str(payload.get("title", "")).strip()
            if not title: raise ValueError("title is required")
            task = self._patch_record("tasks", payload["id"], household_id, token, payload) if payload.get("id") else self._post_record("tasks", household_id, user_id, token, payload)
            self._respond({"task": task}, status=200 if payload.get("id") else 201); return
        if route == "/calendar":
            if not str(payload.get("title", "")).strip() or not str(payload.get("starts_at", "")).strip(): raise ValueError("title and starts_at are required")
            event = self._patch_record("events", payload["id"], household_id, token, payload) if payload.get("id") else self._post_record("events", household_id, user_id, token, payload)
            self._respond({"event": event}, status=200 if payload.get("id") else 201); return
        if route.startswith("/meals/"):
            parts = route.removeprefix("/meals/").strip("/").split("/")
            if len(parts) != 2 or parts[1] != "delete": self._respond({"error": "not found"}, status=404); return
            self._respond({"deleted": self._delete_record("meals", parts[0], household_id, token)}); return
        if route == "/meals/sync-groceries":
            meal = _first(_supabase_request("GET", "/rest/v1/meals", token=token, query=[("select", "ingredients"), ("id", f"eq.{_uuid(payload.get('meal_id'), 'meal id')}"), ("household_id", f"eq.{household_id}")])) or {}
            added = [self._post_record("grocery_items", household_id, user_id, token, {"name": str(item), "category": "Meal"}) for item in meal.get("ingredients", []) if str(item).strip()]
            self._respond({"added": added}); return
        if route == "/meals":
            if not str(payload.get("title", "")).strip() or not str(payload.get("meal_date", "")).strip(): raise ValueError("title and meal_date are required")
            meal = self._patch_record("meals", payload["id"], household_id, token, payload) if payload.get("id") else self._post_record("meals", household_id, user_id, token, payload)
            self._respond({"meal": meal}, status=200 if payload.get("id") else 201); return
        if route == "/notifications/preferences":
            briefing_type = str(payload.get("briefing_type", "morning"))
            preference = {"household_id": household_id, "user_id": user_id, "briefing_type": briefing_type, "enabled": bool(payload.get("enabled", True)), "preferred_time": str(payload.get("preferred_time", "07:00")), "quiet_start": str(payload.get("quiet_start", "21:00")), "quiet_end": str(payload.get("quiet_end", "07:00")), "channel": "email", "updated_at": _iso_now()}
            row = _first(_supabase_request("POST", "/rest/v1/notification_preferences", token=token, query=[("on_conflict", "household_id,user_id,briefing_type")], payload=preference, prefer="return=representation,resolution=merge-duplicates")) or preference
            self._respond({"preferences": row}); return
        if route == "/admin/household":
            if self._role(household_id, user_id, token) != "owner": raise SupabaseHTTPError(403, "owner access required")
            name = str(payload.get("name", "")).strip()
            if not name: raise ValueError("name is required")
            household = _first(_supabase_request("PATCH", "/rest/v1/households", token=token, query=[("id", f"eq.{household_id}")], payload={"name": name})) or {}
            self._respond({"household": household}); return
        if route.startswith("/admin/members/"):
            if self._role(household_id, user_id, token) != "owner": raise SupabaseHTTPError(403, "owner access required")
            parts = route.removeprefix("/admin/members/").strip("/").split("/"); member_id = _uuid(parts[0], "member id")
            if len(parts) == 2 and parts[1] == "remove":
                _supabase_request("DELETE", "/rest/v1/memberships", token=token, query=[("household_id", f"eq.{household_id}"), ("user_id", f"eq.{member_id}")]); self._respond({"member": {"id": member_id}}); return
            role = str(payload.get("role", "member"));
            if role not in {"owner", "member", "child", "guest"}: raise ValueError("invalid role")
            member = _first(_supabase_request("PATCH", "/rest/v1/memberships", token=token, query=[("household_id", f"eq.{household_id}"), ("user_id", f"eq.{member_id}")], payload={"role": role})) or {}
            self._respond({"member": {"id": member_id, **member}}); return
        if route == "/auth/invitations":
            if self._role(household_id, user_id, token) != "owner": raise SupabaseHTTPError(403, "owner access required")
            email = str(payload.get("email", "")).strip().lower(); role = str(payload.get("role", "member"))
            if "@" not in email: raise ValueError("valid email is required")
            if role not in {"member", "child", "guest"}: raise ValueError("invalid role")
            raw_token = secrets.token_urlsafe(32); expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
            invitation = _first(_supabase_request("POST", "/rest/v1/invitations", token=token, payload={"household_id": household_id, "email": email, "role": role, "token_hash": hashlib.sha256(raw_token.encode()).hexdigest(), "invited_by": user_id, "expires_at": expires_at})) or {}
            invitation.pop("token_hash", None); invitation["url"] = f"/invite?token={raw_token}"
            self._respond({"invitation": invitation}, status=201); return
        if route.startswith("/admin/invitations/") and route.endswith("/revoke"):
            if self._role(household_id, user_id, token) != "owner": raise SupabaseHTTPError(403, "owner access required")
            invitation_id = _uuid(route.removeprefix("/admin/invitations/").removesuffix("/revoke").strip("/"), "invitation id")
            invitation = _first(_supabase_request("PATCH", "/rest/v1/invitations", token=token, query=[("id", f"eq.{invitation_id}"), ("household_id", f"eq.{household_id}")], payload={"revoked_at": _iso_now()})) or {}
            invitation.pop("token_hash", None); self._respond({"invitation": invitation}); return
        self._respond({"error": "not found"}, status=404)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Hearthstate-Household")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._handle_get(self._route())
        except (ValueError, SupabaseHTTPError) as exc:
            status = exc.status if isinstance(exc, SupabaseHTTPError) else 400
            self._respond({"error": str(exc)}, status=status)
        except FileNotFoundError:
            self._respond({"error": "not found"}, status=404)
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
