"""
Shared timezone utilities for all scrapers.

Convention: every scraper must store datetimes as TRUE UTC ISO strings
(e.g. "2026-06-18T22:00:00+00:00"). The frontend converts to Pacific for display.

Use local_to_utc() for times that arrive as naive local Pacific times.
Use ensure_utc() for times that are already timezone-aware.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def local_to_utc(dt: datetime) -> datetime:
    """Attach Pacific timezone to a naive datetime, then convert to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PACIFIC)
    return dt.astimezone(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Convert any tz-aware datetime to UTC. Naive datetimes assumed Pacific."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PACIFIC)
    return dt.astimezone(timezone.utc)
