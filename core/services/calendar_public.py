"""Public Calendar collaboration surface (M slice)."""

from __future__ import annotations

from typing import Iterable


def default_service():
    """Ambient Calendar service: the plugin facade when STELLA_CALENDAR_PLUGIN is on."""
    from core.services.calendar_gateway import calendar_plugin_enabled

    if calendar_plugin_enabled():
        from core.services.calendar_facade import CalendarPluginFacade

        return CalendarPluginFacade()
    from agent.calendar import CalendarService

    return CalendarService()


def source_key_is_tombstoned(source_keys: Iterable[str], *, service=None) -> bool:
    if service is None:
        service = default_service()
    return service.has_source_tombstone(source_keys)
