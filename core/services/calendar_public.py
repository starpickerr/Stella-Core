"""Public Calendar collaboration surface (M slice)."""

from __future__ import annotations

from typing import Iterable


def default_service():
    """Ambient Calendar service; stella.calendar is the only domain owner."""
    from core.services.calendar_gateway import calendar_plugin_enabled

    if not calendar_plugin_enabled():
        raise RuntimeError('calendar domain requires the stella.calendar plugin (STELLA_CALENDAR_PLUGIN=1)')
    from core.services.calendar_facade import CalendarPluginFacade

    return CalendarPluginFacade()


def source_key_is_tombstoned(source_keys: Iterable[str], *, service=None) -> bool:
    if service is None:
        service = default_service()
    return service.has_source_tombstone(source_keys)
