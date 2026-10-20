"""Core facade that routes Knowledge calls to the plugin worker when enabled."""

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
_GRANT_REF = "knowledge-default-grant"


def knowledge_plugin_enabled() -> bool:
    return managed_plugin_route("stella.knowledge", os.environ.get("STELLA_KNOWLEDGE_PLUGIN", ""))


@serialized_gateway
def ensure_knowledge_session(data_dir: Path | None = None) -> PluginSession:
    global _SESSION
    if _SESSION is not None and (_SESSION.user_id != plugin_user_id() or not _SESSION.is_running):
        shutdown_knowledge_session()
    if _SESSION is not None:
        return _SESSION
    from core.plugins.roots import resolve_plugin_package_root

    root = resolve_plugin_package_root(
        plugin_id="stella.knowledge",
        env_var="STELLA_KNOWLEDGE_PLUGIN_ROOT",
        folder_name="knowledge",
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
        plugin_id="stella.knowledge",
        user_id=user_id,
        capabilities=["knowledge.read", "knowledge.write", "plugin.invoke"],
        purposes=["interactive", "tool", "job", "any"],
        replace_existing=False,
    )
    session.start()
    _SESSION = session
    return session


@serialized_gateway
def invoke_knowledge(method: str, params: dict[str, Any], *, data_dir: Path) -> dict[str, Any]:
    if not knowledge_plugin_enabled():
        raise PermissionError('knowledge plugin is not installed or enabled')
    session = ensure_knowledge_session(data_dir)
    write_methods = {'dispatch'}
    permissions = ("knowledge.write",) if method in write_methods else ("knowledge.read",)
    payload = dict(params)
    idem = payload.pop("idempotencyKey", None)
    return session.invoke_contract(
        contract="stella.knowledge@1",
        method=method,
        input_payload=payload,
        origin="system",
        grant_ref=user_grant_ref(_GRANT_REF),
        permissions=permissions,
        purpose="interactive",
        idempotency_key=idem or (uuid.uuid4().hex if method in write_methods else None),
        data_handle={"dataDir": str(data_dir), "namespace": "stella.knowledge"},
    )


@serialized_gateway
def shutdown_knowledge_session() -> None:
    global _SESSION
    if _SESSION is not None:
        _SESSION.dispose()
        _SESSION = None
