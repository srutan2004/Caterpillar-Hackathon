"""Time helpers. History is anchored to the run date so demo data always looks current (§7.1)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(UTC)


def local_midnight(d: date, tz: str) -> datetime:
    return datetime.combine(d, time(0, 0), tzinfo=ZoneInfo(tz))


def anchor_date(tz: str, override: str | date | None = None) -> date:
    """The 'today' that generated data is anchored to (local date in the world timezone)."""
    if override is None:
        return datetime.now(ZoneInfo(tz)).date()
    if isinstance(override, date):
        return override
    return date.fromisoformat(override)


def parse_hhmm(value: str) -> timedelta:
    hh, mm = value.split(":")
    return timedelta(hours=int(hh), minutes=int(mm))
