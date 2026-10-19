"""Core-managed source directory descriptors (D20) — metadata only, no body content."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any


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
        self._items: dict[str, SourceDescriptor] = {}

    def upsert(self, descriptor: SourceDescriptor) -> None:
        with self._lock:
            self._items[descriptor.source_id] = descriptor

    def remove(self, source_id: str) -> None:
        with self._lock:
            self._items.pop(source_id, None)

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
                for item in self._items.values()
            ]


DEFAULT_SOURCE_DIRECTORY = SourceDirectory()
