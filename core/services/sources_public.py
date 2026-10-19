"""Core-managed source directory descriptors (D20) — metadata only, no body content."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any

from core.plugins.caller import plugin_user_id


@dataclass(frozen=True)
class SourceDescriptor:
    source_id: str
    plugin_id: str
    kind: str
    label: str
    status: str = "available"


class SourceDirectory:
    """Holds discoverable source references for Briefing / Agent authorization UI."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._items: dict[tuple[str, str], SourceDescriptor] = {}

    def upsert(self, descriptor: SourceDescriptor) -> None:
        with self._lock:
            self._items[(plugin_user_id(), descriptor.source_id)] = descriptor

    def remove(self, source_id: str) -> None:
        with self._lock:
            self._items.pop((plugin_user_id(), source_id), None)

    def list_for_user(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "sourceId": item.source_id,
                    "pluginId": item.plugin_id,
                    "kind": item.kind,
                    "label": item.label,
                    "status": item.status,
                }
                for (user, _), item in self._items.items() if user == plugin_user_id()
            ]


DEFAULT_SOURCE_DIRECTORY = SourceDirectory()
