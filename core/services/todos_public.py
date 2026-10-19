"""Public Tasks collaboration surface for cross-plugin reads (M first slice)."""

from __future__ import annotations

from typing import Iterable


def source_key_is_tombstoned(source_keys: Iterable[str], *, service=None) -> bool:
    """Return True if any candidate source_key is tombstoned in Tasks.

    Prefer calling ``TodoService.has_source_tombstone`` on the owning instance.
    This helper uses the ambient service when callers lack a handle.
    """
    if service is None:
        from agent.todos.service import TodoService

        service = TodoService()
    return service.has_source_tombstone(source_keys)
