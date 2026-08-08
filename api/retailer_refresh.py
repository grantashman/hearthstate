from __future__ import annotations

import json
import ipaddress
import math
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


# Live refresh is intentionally limited to the two supported retailers. The
# endpoint must be an approved provider rather than an arbitrary retailer page.
LIVE_RETAILERS = ("coles", "woolworths")
RETAILER_DOMAINS = {
    "coles": ("coles.com.au",),
    "woolworths": ("woolworths.com.au",),
}
LIVE_ENDPOINT_ENV = "HEARTHSTATE_LIVE_RETAILER_URL"
LIVE_API_KEY_ENV = "HEARTHSTATE_LIVE_RETAILER_API_KEY"
LIVE_QUOTE_MAX_AGE = timedelta(hours=48)
_MAX_RESPONSE_BYTES = 512 * 1024
_MAX_ITEMS = 100
_MAX_MATCHES = 300
_MIN_REFRESH_INTERVAL_SECONDS = 30
_RATE_LOCK = threading.Lock()
_LAST_REFRESH_BY_KEY: dict[str, float] = {}


class _NoRedirectHandler(HTTPRedirectHandler):
    """Do not forward provider bearer credentials to another host."""

    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


_NO_REDIRECT_OPENER = build_opener(_NoRedirectHandler)
LIVE_SEARCH_POLICY = {
    "mode": "live",
    "preserve_user_query": True,
    "preserve_explicit_constraints": True,
    "prefer_retailer_own_brand_when_generic": True,
    "retailer_brands": {"coles": ["Coles"], "woolworths": ["Woolworths"]},
}


class LiveRetailerRefreshError(Exception):
    """A safe, non-sensitive live retailer provider failure."""


@dataclass(frozen=True)
class LiveRefreshResult:
    enabled: bool
    matches: dict[str, dict[str, dict]]
    statuses: dict[str, str]
    checked_at: str | None = None
    error: str | None = None


def _provider_endpoint() -> str | None:
    endpoint = os.environ.get(LIVE_ENDPOINT_ENV, "").strip()
    if not endpoint:
        return None
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise LiveRetailerRefreshError("live retailer provider must use an HTTPS URL without embedded credentials")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as exc:
        raise LiveRetailerRefreshError("live retailer provider must use a public HTTPS hostname") from exc
    if not hostname or port not in {None, 443, 8443}:
        raise LiveRetailerRefreshError("live retailer provider must use a public HTTPS hostname")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise LiveRetailerRefreshError("live retailer provider must use a public HTTPS hostname")
    if hostname in {"localhost", "localhost.localdomain"}:
        raise LiveRetailerRefreshError("live retailer provider must use a public HTTPS hostname")
    return endpoint


def live_refresh_configured() -> bool:
    try:
        return _provider_endpoint() is not None
    except LiveRetailerRefreshError:
        return False


def _iso_datetime(value: object, *, fallback: str | None = None) -> str:
    raw = str(value or fallback or "").strip()
    if not raw:
        raise LiveRetailerRefreshError("provider did not return an observation time")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LiveRetailerRefreshError("provider returned an invalid observation time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if parsed > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise LiveRetailerRefreshError("provider returned a future observation time")
    return parsed.isoformat()


def _require_fresh(timestamp: str, label: str) -> None:
    parsed = datetime.fromisoformat(timestamp)
    if datetime.now(timezone.utc) - parsed > LIVE_QUOTE_MAX_AGE:
        raise LiveRetailerRefreshError(f"provider returned a stale {label}")


def _safe_text(value: object, field: str, maximum: int, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise LiveRetailerRefreshError(f"provider returned an empty {field}")
    if len(text) > maximum:
        raise LiveRetailerRefreshError(f"provider returned an oversized {field}")
    return text


def _product_url(retailer: str, value: object) -> str:
    url = _safe_text(value, "product URL", 2048)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port:
        raise LiveRetailerRefreshError("provider returned an unsafe product URL")
    host = parsed.hostname.lower()
    if not any(host == domain or host.endswith(f".{domain}") for domain in RETAILER_DOMAINS[retailer]):
        raise LiveRetailerRefreshError("provider returned a product URL outside the retailer domain")
    return url


def _safe_price(value: object) -> float:
    if isinstance(value, bool):
        raise LiveRetailerRefreshError("provider returned an invalid price")
    try:
        price = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise LiveRetailerRefreshError("provider returned an invalid price") from exc
    if not math.isfinite(price) or price < 0 or price > 99_999_999.99:
        raise LiveRetailerRefreshError("provider returned an invalid price")
    return price


def normalize_live_match(
    retailer: str,
    raw: dict,
    expected_item_ids: set[str],
    *,
    default_observed_at: str | None = None,
    stale: bool = False,
) -> dict:
    """Validate a provider/quote match before it reaches comparison or storage."""
    if retailer not in LIVE_RETAILERS:
        raise LiveRetailerRefreshError("unsupported live retailer")
    if not isinstance(raw, dict):
        raise LiveRetailerRefreshError("provider returned a malformed match")
    item_id = _safe_text(raw.get("item_id") or raw.get("grocery_item_id"), "item id", 80)
    if item_id not in expected_item_ids:
        raise LiveRetailerRefreshError("provider returned a match for an unknown grocery item")
    size_match = _safe_text(raw.get("size_match") or "exact", "size match", 20).lower()
    if size_match not in {"exact", "closest"}:
        raise LiveRetailerRefreshError("provider returned an invalid size match")
    size_quantity_safe = raw.get("size_quantity_safe", False)
    if not isinstance(size_quantity_safe, bool):
        raise LiveRetailerRefreshError("provider returned an invalid size safety flag")
    comparison_key = _safe_text(raw.get("comparison_key"), "comparison key", 200)
    observed_at = _iso_datetime(raw.get("observed_at"), fallback=default_observed_at)
    if not stale:
        _require_fresh(observed_at, "observation")
    confidence = str(raw.get("confidence") or "live").strip().lower()
    if confidence != "live":
        raise LiveRetailerRefreshError("live provider confidence must be live")
    return {
        "retailer": retailer,
        "retailer_label": {"coles": "Coles", "woolworths": "Woolworths"}[retailer],
        "item_id": item_id,
        "product_key": _safe_text(raw.get("product_key"), "product key", 120),
        "comparison_key": comparison_key,
        "title": _safe_text(raw.get("title") or raw.get("product_title"), "product title", 500),
        "price": _safe_price(raw.get("price")),
        "url": _product_url(retailer, raw.get("url") or raw.get("product_url")),
        "confidence": "live",
        "observed_at": observed_at,
        "note": _safe_text(raw.get("note"), "note", 500, required=False),
        "match_basis": _safe_text(raw.get("match_basis"), "match basis", 120, required=False) or "approved live provider",
        "requested_size": _safe_text(raw.get("requested_size"), "requested size", 40, required=False) or None,
        "product_size": _safe_text(raw.get("product_size"), "product size", 40, required=False) or None,
        "size_match": size_match,
        "size_quantity_safe": size_quantity_safe,
        "stale": stale,
    }


def cached_live_match(row: dict, *, expected_item_ids: set[str]) -> dict | None:
    """Convert a stored live quote into a comparison match, if it remains safe."""
    if str(row.get("confidence") or "").strip().lower() != "live":
        return None
    try:
        observed_at = _iso_datetime(row.get("observed_at"))
        parsed = datetime.fromisoformat(observed_at)
        stale = datetime.now(timezone.utc) - parsed > LIVE_QUOTE_MAX_AGE
        return normalize_live_match(
            str(row.get("retailer") or "").strip().lower(),
            row,
            expected_item_ids,
            default_observed_at=observed_at,
            stale=stale,
        )
    except LiveRetailerRefreshError:
        return None


def _request_payload(items: list[dict]) -> dict:
    if len(items) > _MAX_ITEMS:
        raise LiveRetailerRefreshError("grocery list is too large for live refresh")
    return {
        "version": 1,
        "retailers": list(LIVE_RETAILERS),
        "search_policy": LIVE_SEARCH_POLICY,
        "items": [
            {
                "item_id": str(item.get("id") or ""),
                "name": str(item.get("name") or "").strip(),
                "query": str(item.get("name") or "").strip(),
                "quantity": item.get("quantity") or 1,
                "unit": str(item.get("unit") or "each"),
            }
            for item in items
            if item.get("id") and str(item.get("name") or "").strip()
        ],
    }


def _rate_limited(rate_key: str | None) -> bool:
    if not rate_key:
        return False
    key = str(rate_key).strip()[:160]
    if not key:
        return False
    now = time.monotonic()
    with _RATE_LOCK:
        previous = _LAST_REFRESH_BY_KEY.get(key)
        if previous is not None and now - previous < _MIN_REFRESH_INTERVAL_SECONDS:
            return True
        _LAST_REFRESH_BY_KEY[key] = now
        if len(_LAST_REFRESH_BY_KEY) > 2048:
            cutoff = now - _MIN_REFRESH_INTERVAL_SECONDS
            for old_key, old_time in list(_LAST_REFRESH_BY_KEY.items()):
                if old_time < cutoff:
                    _LAST_REFRESH_BY_KEY.pop(old_key, None)
    return False


def _fetch(endpoint: str, payload: dict) -> dict:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Hearthstate/1.0 retailer-refresh",
    }
    api_key = os.environ.get(LIVE_API_KEY_ENV, "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(endpoint, data=json.dumps(payload, separators=(",", ":")).encode("utf-8"), method="POST", headers=headers)
    try:
        with _NO_REDIRECT_OPENER.open(request, timeout=8) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise LiveRetailerRefreshError(f"live provider returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise LiveRetailerRefreshError("live provider is unavailable") from exc
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise LiveRetailerRefreshError("live provider response is too large")
    try:
        decoded = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise LiveRetailerRefreshError("live provider returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise LiveRetailerRefreshError("live provider returned an invalid response")
    return decoded


def refresh_live_retailers(items: list[dict], *, rate_key: str | None = None) -> LiveRefreshResult:
    """Fetch approved live observations; callers can always fall back to catalog data."""
    try:
        endpoint = _provider_endpoint()
    except LiveRetailerRefreshError as exc:
        return LiveRefreshResult(False, {}, {retailer: "configuration-error" for retailer in LIVE_RETAILERS}, error=str(exc))
    if endpoint is None:
        return LiveRefreshResult(False, {}, {retailer: "curated" for retailer in LIVE_RETAILERS})
    if not items:
        return LiveRefreshResult(True, {}, {retailer: "no-items" for retailer in LIVE_RETAILERS})
    if _rate_limited(rate_key):
        return LiveRefreshResult(True, {}, {retailer: "rate-limited" for retailer in LIVE_RETAILERS})

    try:
        payload = _fetch(endpoint, _request_payload(items))
        checked_at = _iso_datetime(payload.get("checked_at"))
        _require_fresh(checked_at, "check")
        raw_retailers = payload.get("retailers")
        if not isinstance(raw_retailers, dict):
            raise LiveRetailerRefreshError("live provider omitted retailer results")
        expected_ids = {str(item.get("id")) for item in items if item.get("id")}
        matches: dict[str, dict[str, dict]] = {}
        statuses: dict[str, str] = {}
        total_matches = 0
        for retailer in LIVE_RETAILERS:
            bucket = raw_retailers.get(retailer, {})
            raw_matches = bucket.get("matches", []) if isinstance(bucket, dict) else bucket
            if not isinstance(raw_matches, list):
                raise LiveRetailerRefreshError("live provider returned malformed retailer results")
            retailer_matches: dict[str, dict] = {}
            for raw_match in raw_matches:
                total_matches += 1
                if total_matches > _MAX_MATCHES:
                    raise LiveRetailerRefreshError("live provider returned too many matches")
                match = normalize_live_match(retailer, raw_match, expected_ids)
                if match["item_id"] in retailer_matches:
                    raise LiveRetailerRefreshError("live provider returned duplicate item matches")
                retailer_matches[match["item_id"]] = match
            matches[retailer] = retailer_matches
            statuses[retailer] = "live" if retailer_matches else "no-match"
        return LiveRefreshResult(True, matches, statuses, checked_at=checked_at)
    except LiveRetailerRefreshError as exc:
        return LiveRefreshResult(True, {}, {retailer: "curated" for retailer in LIVE_RETAILERS}, error=str(exc))
