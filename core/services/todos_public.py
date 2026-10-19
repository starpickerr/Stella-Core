"""Public Tasks collaboration surface for cross-plugin reads (M first slice)."""

from __future__ import annotations

from typing import Iterable


def default_service():
    """Ambient Tasks service: the plugin facade when STELLA_TODOS_PLUGIN is on.

    Keeps callers such as Briefing from holding a private ``agent.todos`` handle
    as the only path once Tasks is served by ``stella.tasks``.
    """
    from core.services.todos_gateway import todos_plugin_enabled

    if todos_plugin_enabled():
        from core.services.todos_facade import TodosPluginFacade

        return TodosPluginFacade()
    from agent.todos.service import TodoService

    return TodoService()


def source_key_is_tombstoned(source_keys: Iterable[str], *, service=None) -> bool:
    """Return True if any candidate source_key is tombstoned in Tasks.

    Prefer calling ``has_source_tombstone`` on the owning instance. Without a
    handle this helper resolves the ambient service (plugin facade when enabled).
    """
    if service is None:
        service = default_service()
    return service.has_source_tombstone(source_keys)
