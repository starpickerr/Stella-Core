"""Plugin authorization layered on top of existing conversation permission policy."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Iterable


@dataclass(frozen=True)
class PluginGrant:
    grant_ref: str
    plugin_id: str
    user_id: str
    capabilities: frozenset[str]
    purposes: frozenset[str]
    revoked: bool = False


class PluginAuthorizationStore:
    """Persistent-in-process grant registry. Install/enable ≠ authorization."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._grants: dict[str, PluginGrant] = {}

    def issue(
        self,
        *,
        grant_ref: str,
        plugin_id: str,
        user_id: str,
        capabilities: Iterable[str],
        purposes: Iterable[str] = ("interactive",),
    ) -> PluginGrant:
        grant = PluginGrant(
            grant_ref=grant_ref,
            plugin_id=plugin_id,
            user_id=user_id,
            capabilities=frozenset(capabilities),
            purposes=frozenset(purposes),
        )
        with self._lock:
            self._grants[grant_ref] = grant
        return grant

    def revoke(self, grant_ref: str) -> None:
        with self._lock:
            grant = self._grants.get(grant_ref)
            if grant is None:
                return
            self._grants[grant_ref] = PluginGrant(
                grant_ref=grant.grant_ref,
                plugin_id=grant.plugin_id,
                user_id=grant.user_id,
                capabilities=grant.capabilities,
                purposes=grant.purposes,
                revoked=True,
            )

    def get(self, grant_ref: str) -> PluginGrant | None:
        with self._lock:
            return self._grants.get(grant_ref)

    def check(
        self,
        *,
        grant_ref: str,
        plugin_id: str,
        user_id: str,
        required_capabilities: Iterable[str],
        purpose: str,
        generation: int,
        context_generation: int,
    ) -> None:
        if generation != context_generation:
            raise PermissionError("stale generation in host context")
        grant = self.get(grant_ref)
        if grant is None:
            raise PermissionError("unknown grantRef")
        if grant.revoked:
            raise PermissionError("grant revoked")
        if grant.plugin_id != plugin_id or grant.user_id != user_id:
            raise PermissionError("grant identity mismatch")
        if purpose not in grant.purposes and "any" not in grant.purposes:
            raise PermissionError(f"purpose not authorized: {purpose}")
        missing = set(required_capabilities) - set(grant.capabilities)
        if missing:
            raise PermissionError(f"missing capabilities: {sorted(missing)}")


DEFAULT_AUTHZ = PluginAuthorizationStore()
