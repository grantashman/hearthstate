"""Explicit local timezone policy for the Hearthstate."""

from datetime import datetime
from zoneinfo import ZoneInfo

PROJECT_TIMEZONE_NAME = "Australia/Sydney"
PROJECT_TIMEZONE = ZoneInfo(PROJECT_TIMEZONE_NAME)


def local_now() -> datetime:
    """Return Sydney local time as a naive datetime for existing planner APIs."""
    return datetime.now(PROJECT_TIMEZONE).replace(tzinfo=None)
