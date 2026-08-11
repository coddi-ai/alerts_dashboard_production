"""Temporal context helpers for Campbell AI."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "America/Santiago"

_WEEKDAYS_ES = (
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
)


def _zoneinfo(timezone_name: str) -> ZoneInfo:
    name = str(timezone_name or "").strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def current_temporal_context(timezone_name: str = DEFAULT_TIMEZONE) -> dict[str, str]:
    """Return the single clock context the API and agents should share."""
    zone = _zoneinfo(timezone_name)
    now = datetime.now(zone)
    return {
        "today": now.date().isoformat(),
        "now": now.isoformat(timespec="seconds"),
        "timezone": getattr(zone, "key", "UTC"),
        "weekday": _WEEKDAYS_ES[now.weekday()],
    }
