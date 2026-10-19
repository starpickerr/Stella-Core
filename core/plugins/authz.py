"""Plugin authorization layered on top of existing conversation permission policy."""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
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
    parent_ref: str | None = None
    consumer_plugin_id: str | None = None
    methods: frozenset[str] = frozenset()
    resources: frozenset[str] = frozenset()
    valid_until: str | None = None
    policy_revision: int = 1


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
                    row['methods'] = frozenset(row.get('methods') or [])
                    row['resources'] = frozenset(row.get('resources') or [])
                    grants[ref] = PluginGrant(**row)
                before = dict(grants)
                yield grants
                for ref, grant in grants.items():
                    if before.get(ref) == grant:
                        continue
                    row = asdict(grant)
                    row["capabilities"] = sorted(grant.capabilities)
                    row["purposes"] = sorted(grant.purposes)
                    row['methods'] = sorted(grant.methods)
                    row['resources'] = sorted(grant.resources)
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
            grants[grant_ref] = replace(grant, revoked=True, policy_revision=grant.policy_revision + 1)

    def set_purposes(self, grant_ref: str, purposes: Iterable[str]) -> None:
        """Change an existing grant without restoring revoked capabilities."""
        with self._state() as grants:
            grant = grants.get(grant_ref)
            if grant is not None:
                grants[grant_ref] = replace(grant, purposes=frozenset(purposes), policy_revision=grant.policy_revision + 1)
            for key, child in list(grants.items()):
                if child.parent_ref == grant_ref:
                    grants[key] = replace(child, purposes=child.purposes & frozenset(purposes),
                                          policy_revision=child.policy_revision + 1)

    def get(self, grant_ref: str) -> PluginGrant | None:
        with self._state() as grants:
            return grants.get(grant_ref)

    def issue_scoped(self, *, grant_ref: str, parent_ref: str, plugin_id: str, user_id: str,
                     consumer_plugin_id: str, capability: str, methods: Iterable[str], resources: Iterable[dict],
                     purpose: str, valid_until: str | None = None) -> PluginGrant:
        if purpose not in {'interactive', 'background'}:
            raise ValueError('scoped grant requires a concrete purpose')
        method_set = frozenset(methods)
        resource_set = frozenset(_resource_key(row) for row in resources)
        if not method_set or not resource_set or not capability:
            raise ValueError('scoped grant requires methods and resources')
        if valid_until is not None:
            _expiry(valid_until)
        grant = PluginGrant(grant_ref=grant_ref, plugin_id=plugin_id, user_id=user_id,
                            capabilities=frozenset({capability}), purposes=frozenset({purpose}),
                            parent_ref=parent_ref, consumer_plugin_id=consumer_plugin_id,
                            methods=method_set, resources=resource_set, valid_until=valid_until)
        with self._state() as grants:
            existing = grants.get(grant_ref)
            if existing is not None:
                if existing != grant:
                    raise ValueError('scoped grant identity cannot be replaced')
                return existing
            grants[grant_ref] = grant
        return grant

    def scoped_grants(self, user_id: str, *, plugin_id: str | None = None) -> list[PluginGrant]:
        with self._state() as grants:
            return [grant for grant in grants.values() if grant.parent_ref and grant.user_id == user_id and
                    (plugin_id is None or grant.plugin_id == plugin_id)]

    def policy_revision(self, user_id: str) -> int:
        with self._state() as grants:
            return 1 + sum(grant.policy_revision for grant in grants.values() if grant.user_id == user_id)

    def check_scoped(self, *, grant_ref: str, plugin_id: str, user_id: str, consumer_plugin_id: str,
                     method: str, required_capabilities: Iterable[str], resources: Iterable[dict], purpose: str):
        required = frozenset(_resource_key(row) for row in resources)
        all_user = _resource_key({'kind': 'user', 'id': user_id})
        now = datetime.now(timezone.utc)
        with self._state() as grants:
            candidates = [grant for grant in grants.values() if grant.parent_ref == grant_ref and
                          grant.plugin_id == plugin_id and grant.user_id == user_id and
                          grant.consumer_plugin_id == consumer_plugin_id and not grant.revoked and
                          purpose in grant.purposes and method in grant.methods and
                          (grant.valid_until is None or _expiry(grant.valid_until) > now)]
            for capability in required_capabilities:
                if not any(capability in grant.capabilities and
                           (all_user in grant.resources or required <= grant.resources) for grant in candidates):
                    raise PermissionError(f'scoped grant denied: {capability} / {purpose} / {method}')

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


def _resource_key(resource: dict) -> str:
    if (not isinstance(resource, dict) or set(resource) != {'kind', 'id'} or
            not all(isinstance(value, str) and value for value in resource.values())):
        raise ValueError('invalid stable resource reference')
    return json.dumps(resource, sort_keys=True, separators=(',', ':'))


def _expiry(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('grant expiry must include a timezone')
    return parsed


def _authorization_path() -> Path:
    from common.state_dir import shared_root

    return shared_root() / "plugin-packages" / "management" / "authorization.sqlite"


DEFAULT_AUTHZ = PluginAuthorizationStore(path=_authorization_path)
