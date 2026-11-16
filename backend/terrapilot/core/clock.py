"""The business clock: wall time, or the demo override `TP_NOW` (ISO timestamp or local "HH:MM" today)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from terrapilot.core.settings import get_settings
from terrapilot.core.timeutil import parse_hhmm, utcnow


def site_tz(cfg_app_calendar: dict[str, object]) -> ZoneInfo:
    return ZoneInfo(str(cfg_app_calendar.get("timezone") or "UTC"))


def now(tz: ZoneInfo | None = None, override: str | None = None) -> datetime:
    """Current business time in UTC. `override` (or TP_NOW) pins it for demos and tests."""
    value = override if override is not None else get_settings().tp_now
    if not value:
        return utcnow()
    if ":" in value and len(value) <= len("HH:MM"):
        zone = tz or ZoneInfo("UTC")
        today = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
        return (today + parse_hhmm(value)).astimezone(UTC)
    ts = datetime.fromisoformat(value)
    return (ts if ts.tzinfo else ts.replace(tzinfo=tz or UTC)).astimezone(UTC)
