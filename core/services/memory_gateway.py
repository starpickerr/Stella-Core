"""Core facade that routes Memory calls to the plugin worker when enabled."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from core.plugins.authz import DEFAULT_AUTHZ
from core.plugins.caller import issue_compatibility_grant, managed_plugin_route, plugin_user_id, serialized_gateway, user_grant_ref
from core.plugins.host import PluginSession
from core.plugins.runtime_hub import DEFAULT_REGISTRY

_SESSION: PluginSession | None = None
_GRANT_REF = "memory-default-grant"


def memory_plugin_enabled() -> bool:
    return managed_plugin_route("stella.memory", os.environ.get("STELLA_MEMORY_PLUGIN", ""))


@serialized_gateway
def ensure_memory_session(data_dir: Path | None = None) -> PluginSession:
    global _SESSION
    if _SESSION is not None and (_SESSION.user_id != plugin_user_id() or not _SESSION.is_running):
        shutdown_memory_session()
    if _SESSION is not None:
        return _SESSION
    from core.plugins.roots import resolve_plugin_package_root

    root = resolve_plugin_package_root(
        plugin_id="stella.memory",
        env_var="STELLA_MEMORY_PLUGIN_ROOT",
        folder_name="memory",
    )
    user_id = plugin_user_id()
    session = PluginSession(
        root,
        source_label="first-party-external",
        registry=DEFAULT_REGISTRY,
        user_id=user_id,
        authz=DEFAULT_AUTHZ,
    )
    # Self-contained Stella-Plugins packages must not import Stella agent.* .
    if os.environ.get("STELLA_ALLOW_REPO_IMPORT") in {"1", "true", "yes"}:
        os.environ.setdefault("STELLA_REPO_ROOT", str(Path(__file__).resolve().parents[2]))
    issue_compatibility_grant(DEFAULT_AUTHZ,
        grant_ref=user_grant_ref(_GRANT_REF),
        plugin_id="stella.memory",
        user_id=user_id,
        capabilities=["memory.read", "memory.write", "plugin.invoke"],
        purposes=["interactive", "tool", "job", "any"],
        replace_existing=False,
    )
    session.start()
    _SESSION = session
    return session


@serialized_gateway
def invoke_memory(method: str, params: dict[str, Any], *, data_dir: Path) -> dict[str, Any]:
    if not memory_plugin_enabled():
        raise PermissionError('memory plugin is not installed or enabled')
    session = ensure_memory_session(data_dir)
    write_methods = {'begin_snapshot', 'restore_snapshot', 'write', 'dispatch', 'sync', 'flush_memory', 'write_daily_summary', 'deep_dream'}
    permissions = ("memory.write",) if method in write_methods else ("memory.read",)
    payload = dict(params)
    idem = payload.pop("idempotencyKey", None)
    return session.invoke_contract(
        contract="stella.memory@1",
        method=method,
        input_payload=payload,
        origin="system",
        grant_ref=user_grant_ref(_GRANT_REF),
        permissions=permissions,
        purpose="interactive",
        idempotency_key=idem or (uuid.uuid4().hex if method in write_methods else None),
        data_handle={"dataDir": str(data_dir), "namespace": "stella.memory"},
    )


@serialized_gateway
def shutdown_memory_session() -> None:
    global _SESSION
    if _SESSION is not None:
        _SESSION.dispose()
        _SESSION = None
