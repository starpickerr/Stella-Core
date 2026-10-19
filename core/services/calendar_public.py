"""Public Calendar collaboration surface (M slice)."""

from __future__ import annotations

from typing import Iterable


def source_key_is_tombstoned(source_keys: Iterable[str], *, service=None) -> bool:
    if service is None:
        from agent.calendar import CalendarService

        service = CalendarService()
    return service.has_source_tombstone(source_keys)
