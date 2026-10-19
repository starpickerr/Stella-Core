"""Normalize external timezone labels into keys ZoneInfo accepts."""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import logging

logger = logging.getLogger("stella.calendar")

_ALIASES = {
    "Asia/Beijing": "Asia/Shanghai",
    "Asia/Chungking": "Asia/Chongqing",
    "Asia/Macao": "Asia/Macau",
}

# EventKit fixed-offset zones look like GMT+0800 / GMT+08:00 / GMT-5.
_GMT_OFFSET = re.compile(r"(?i)^GMT([+-])(\d{1,2})(?::?(\d{2}))?$")


def normalize_timezone(value, *, default: str = "UTC") -> str:
    """Return a ZoneInfo-compatible key, falling back to ``default`` when unknown."""
    if not isinstance(value, str):
        return default
    zone = value.strip()
    if not zone:
        return default
    zone = _ALIASES.get(zone, zone)
    if _zoneinfo_ok(zone):
        return zone
    mapped = _from_gmt_offset(zone)
    if mapped and _zoneinfo_ok(mapped):
        return mapped
    logger.warning("[Timezone] unsupported label %r; using %s", value, default)
    return default


def _zoneinfo_ok(zone: str) -> bool:
    try:
        ZoneInfo(zone)
        return True
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return False


def _from_gmt_offset(zone: str) -> str | None:
    match = _GMT_OFFSET.fullmatch(zone)
    if not match:
        return None
    sign = 1 if match.group(1) == "+" else -1
    hours = int(match.group(2))
    minutes = int(match.group(3) or 0)
    if minutes or hours > 14:
        return None
    offset_hours = sign * hours
    if offset_hours == 0:
        return "UTC"
    # IANA Etc/GMT uses the opposite sign of civil UTC offsets.
    inverted = -offset_hours
    return f"Etc/GMT{inverted:+d}"
