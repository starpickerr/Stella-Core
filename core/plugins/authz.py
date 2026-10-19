"""Plugin authorization layered on top of existing conversation permission policy."""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Callable, Iterable


@dataclass(frozen=True)
class PluginGrant:
    grant_ref: str
    plugin_id: str
    user_id: str
    capabilities: frozenset[str]
    purposes: frozenset[str]
    revoked: bool = False


class PluginAuthorizationStore:
    """Grant registry with transactional persistence in the production store."""

    def __init__(self, *, path: Path | Callable[[], Path] | None = None) -> None:
        self._path = path
        self._lock = RLock()
        self._grants: dict[str, PluginGrant] = {}

    @contextmanager
    def _state(self):
        with self._lock:
            path = self._path() if callable(self._path) else self._path
            if path is None:
                yield self._grants
                return
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(path, timeout=30)) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS grants (ref TEXT PRIMARY KEY, value TEXT NOT NULL)")
                db.execute("BEGIN IMMEDIATE")
                grants = {}
                for ref, raw in db.execute("SELECT ref, value FROM grants"):
                    row = json.loads(raw)
                    row["capabilities"] = frozenset(row["capabilities"])
                    row["purposes"] = frozenset(row["purposes"])
                    grants[ref] = PluginGrant(**row)
                before = dict(grants)
                yield grants
                for ref, grant in grants.items():
                    if before.get(ref) == grant:
                        continue
                    row = asdict(grant)
                    row["capabilities"] = sorted(grant.capabilities)
                    row["purposes"] = sorted(grant.purposes)
                    db.execute("INSERT INTO grants VALUES (?, ?) ON CONFLICT(ref) DO UPDATE SET value=excluded.value",
                               (ref, json.dumps(row)))

    def issue(
        self,
        *,
        grant_ref: str,
        plugin_id: str,
        user_id: str,
        capabilities: Iterable[str],
        purposes: Iterable[str] = ("interactive",),
        replace_existing: bool = True,
    ) -> PluginGrant:
        grant = PluginGrant(
            grant_ref=grant_ref,
            plugin_id=plugin_id,
            user_id=user_id,
            capabilities=frozenset(capabilities),
            purposes=frozenset(purposes),
        )
        with self._state() as grants:
            if not replace_existing and grant_ref in grants:
                return grants[grant_ref]
            grants[grant_ref] = grant
        return grant

    def revoke(self, grant_ref: str) -> None:
        with self._state() as grants:
            grant = grants.get(grant_ref)
            if grant is None:
                return
            grants[grant_ref] = PluginGrant(
                grant_ref=grant.grant_ref,
                plugin_id=grant.plugin_id,
                user_id=grant.user_id,
                capabilities=grant.capabilities,
                purposes=grant.purposes,
                revoked=True,
            )

    def set_purposes(self, grant_ref: str, purposes: Iterable[str]) -> None:
        """Change an existing grant without restoring revoked capabilities."""
        with self._state() as grants:
            grant = grants.get(grant_ref)
            if grant is not None:
                grants[grant_ref] = replace(grant, purposes=frozenset(purposes))

    def get(self, grant_ref: str) -> PluginGrant | None:
        with self._state() as grants:
            return grants.get(grant_ref)

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


def _authorization_path() -> Path:
    from common.state_dir import shared_root

    return shared_root() / "plugin-packages" / "management" / "authorization.sqlite"


DEFAULT_AUTHZ = PluginAuthorizationStore(path=_authorization_path)
