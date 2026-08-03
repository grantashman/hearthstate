from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from typing import Callable

from .briefings import _current_time, compose_briefing
from .store import PlannerStore


_RETRY_DELAY = timedelta(minutes=5)
_MAX_ATTEMPTS = 3


def _clock_minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def _is_quiet_for_preferences(current: datetime, quiet_start: str, quiet_end: str) -> bool:
    now = current.hour * 60 + current.minute
    start = _clock_minutes(quiet_start)
    end = _clock_minutes(quiet_end)
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def _is_before_preferred_time(current: datetime, preferred_time: str) -> bool:
    return current.hour * 60 + current.minute < _clock_minutes(preferred_time)


def _provider_message_id(response: object) -> str | None:
    if not isinstance(response, dict):
        return None
    value = response.get("message_id") or response.get("id")
    return str(value)[:200] if value else None


def deliver_briefing(
    store: PlannerStore,
    viewer: str,
    recipient: str,
    transport: Callable[[dict[str, str]], object],
    now: datetime | None = None,
    *,
    briefing_type: str = "morning",
) -> dict[str, object]:
    """Deliver one briefing with preference filtering, atomic claiming, and retry state."""
    recipient = str(recipient or "").strip()
    if not recipient or len(recipient) > 320:
        raise ValueError("briefing recipient is required")
    current = _current_time(now)
    preferences = store.get_notification_preferences(viewer, briefing_type)
    if not preferences["enabled"]:
        return {"status": "skipped", "reason": "disabled"}
    if _is_quiet_for_preferences(current, preferences["quiet_start"], preferences["quiet_end"]):
        return {"status": "skipped", "reason": "quiet_hours"}
    if _is_before_preferred_time(current, preferences["preferred_time"]):
        return {"status": "skipped", "reason": "before_preferred_time"}
    message_text = compose_briefing(store, viewer, current, enforce_quiet_hours=False)
    if message_text is None:
        return {"status": "skipped", "reason": "quiet_hours"}
    run_date = current.date().isoformat()
    claim = store.claim_briefing_delivery(
        viewer,
        briefing_type,
        run_date,
        now=current,
        max_attempts=_MAX_ATTEMPTS,
    )
    if claim is None:
        return {"status": "duplicate", "run_date": run_date}
    outbound = {
        "to": recipient,
        "subject": f"Your Hearthstate {briefing_type} briefing",
        "text": message_text,
        "briefing_type": briefing_type,
    }
    try:
        response = transport(outbound)
    except Exception as exc:
        retry_at = current + _RETRY_DELAY if int(claim["attempt_count"]) < _MAX_ATTEMPTS else None
        safe_error = f"{type(exc).__name__}: briefing delivery provider failed"
        record = store.mark_briefing_delivery_failed(
            viewer,
            briefing_type,
            run_date,
            str(claim["claim_id"]),
            safe_error,
            retry_at=retry_at,
            now=current,
        )
        return {
            "status": "failed",
            "run_date": run_date,
            "attempt_count": record["attempt_count"],
            "retry_at": record["next_attempt_at"],
        }
    record = store.mark_briefing_delivery_sent(
        viewer,
        briefing_type,
        run_date,
        str(claim["claim_id"]),
        _provider_message_id(response),
        now=current,
    )
    return {
        "status": "sent",
        "run_date": run_date,
        "attempt_count": record["attempt_count"],
        "provider_message_id": record["provider_message_id"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Deliver one Hearthstate household briefing.")
    parser.add_argument("--database", default=os.environ.get("HEARTHSTATE_DB", "hearthstate.db"))
    parser.add_argument("--accounts-database", default=os.environ.get("HEARTHSTATE_ACCOUNTS_DB"))
    parser.add_argument("--household-id", default=os.environ.get("HEARTHSTATE_HOUSEHOLD_ID", "default"))
    parser.add_argument("--viewer", default="grant")
    parser.add_argument("--briefing-type", default="morning")
    parser.add_argument("--agentmail", action="store_true")
    args = parser.parse_args()
    if not args.agentmail:
        parser.error("--agentmail is required for briefing delivery")
    if not args.accounts_database or args.household_id == "default":
        parser.error("--accounts-database and --household-id are required with --agentmail")

    from .accounts import HouseholdDirectory
    from .agentmail import send_briefing_email

    accounts = HouseholdDirectory(args.accounts_database)
    store = PlannerStore(args.database, household_id=args.household_id)
    try:
        contact = accounts.get_member_contact(args.household_id, args.viewer)
        recipient = str(contact.get("email") or "").strip()
        if not recipient:
            parser.error("briefing recipient email is missing")
        result = deliver_briefing(
            store,
            args.viewer,
            recipient,
            send_briefing_email,
            briefing_type=args.briefing_type,
        )
        print(json.dumps(result, sort_keys=True))
    finally:
        store.close()
        accounts.close()


if __name__ == "__main__":
    main()
