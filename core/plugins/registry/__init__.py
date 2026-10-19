"""In-memory contribution snapshot and generation tracking."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class ContributionSnapshot:
    plugin_id: str
    generation: int
    source_label: str
    package_digest: str
    contributes: dict[str, Any]
    services: tuple[str, ...] = ()


class PluginRegistry:
    """Tracks published contributions; rejects stale generation invokes."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._by_plugin: dict[str, ContributionSnapshot] = {}
        self._generations: dict[str, int] = {}
        self._service_owner: dict[str, str] = {}

    def next_generation(self, plugin_id: str) -> int:
        with self._lock:
            generation = self._generations.get(plugin_id, 0) + 1
            self._generations[plugin_id] = generation
            return generation

    def publish(self, snapshot: ContributionSnapshot) -> None:
        with self._lock:
            for service in snapshot.services:
                owner = self._service_owner.get(service)
                if owner is not None and owner != snapshot.plugin_id:
                    raise ValueError(f"service already owned: {service} by {owner}")
            old = self._by_plugin.get(snapshot.plugin_id)
            if old is not None:
                for service in old.services:
                    self._service_owner.pop(service, None)
            self._by_plugin[snapshot.plugin_id] = snapshot
            for service in snapshot.services:
                self._service_owner[service] = snapshot.plugin_id

    def revoke(self, plugin_id: str, generation: int | None = None) -> None:
        with self._lock:
            snap = self._by_plugin.get(plugin_id)
            if snap is None:
                return
            if generation is not None and snap.generation != generation:
                return
            for service in snap.services:
                if self._service_owner.get(service) == plugin_id:
                    del self._service_owner[service]
            del self._by_plugin[plugin_id]

    def get(self, plugin_id: str) -> ContributionSnapshot | None:
        with self._lock:
            return self._by_plugin.get(plugin_id)

    def require_generation(self, plugin_id: str, generation: int) -> ContributionSnapshot:
        snap = self.get(plugin_id)
        if snap is None:
            raise LookupError(f"plugin not published: {plugin_id}")
        if snap.generation != generation:
            raise PermissionError(
                f"stale generation for {plugin_id}: have {snap.generation}, got {generation}"
            )
        return snap

    def owner_of(self, service: str) -> str | None:
        with self._lock:
            return self._service_owner.get(service)

    def list_snapshots(self) -> list[ContributionSnapshot]:
        with self._lock:
            return list(self._by_plugin.values())


__all__ = ["ContributionSnapshot", "PluginRegistry"]
