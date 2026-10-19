"""Core facade that routes Bills calls to the plugin worker when enabled."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from core.plugins.authz import DEFAULT_AUTHZ
from core.plugins.host import PluginSession
from core.plugins.runtime_hub import DEFAULT_REGISTRY

_SESSION: PluginSession | None = None
_GRANT_REF = "bills-default-grant"


def bills_plugin_enabled() -> bool:
    return os.environ.get("STELLA_BILLS_PLUGIN", "").strip() in {"1", "true", "yes"}


def ensure_bills_session(db_path: Path | None = None) -> PluginSession:
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    sibling = Path(__file__).resolve().parents[3] / "Stella-Plugins" / "plugins" / "bills"
    workspace = (
        Path(__file__).resolve().parents[2]
        / "stella-plugins-workspace"
        / "plugins"
        / "bills"
    )
    root = Path(
        os.environ.get("STELLA_BILLS_PLUGIN_ROOT")
        or (sibling if sibling.is_dir() else workspace)
    )
    user_id = os.environ.get("STELLA_PLUGIN_USER", "local-default")
    session = PluginSession(
        root,
        source_label="first-party-external",
        registry=DEFAULT_REGISTRY,
        user_id=user_id,
    )
    # Self-contained Stella-Plugins packages must not import Stella agent.* .
    if os.environ.get("STELLA_ALLOW_REPO_IMPORT") in {"1", "true", "yes"}:
        os.environ.setdefault("STELLA_REPO_ROOT", str(Path(__file__).resolve().parents[2]))
    DEFAULT_AUTHZ.issue(
        grant_ref=_GRANT_REF,
        plugin_id="stella.bills",
        user_id=user_id,
        capabilities=["bills.read", "bills.write", "plugin.invoke"],
        purposes=["interactive", "tool", "job", "any"],
    )
    session.start()
    _SESSION = session
    return session


def invoke_bills(method: str, params: dict[str, Any], *, db_path: Path) -> dict[str, Any]:
    session = ensure_bills_session(db_path)
    write_methods = {"create_ledger", "update_ledger", "delete_ledger"}
    permissions = ("bills.write",) if method in write_methods else ("bills.read",)
    payload = dict(params)
    idem = payload.pop("idempotencyKey", None)
    return session.invoke_contract(
        contract="stella.bills@1",
        method=method,
        input_payload=payload,
        origin="system",
        grant_ref=_GRANT_REF,
        permissions=permissions,
        purpose="interactive",
        idempotency_key=idem or (uuid.uuid4().hex if method in write_methods else None),
        data_handle={"dbPath": str(db_path), "namespace": "stella.bills"},
    )


def shutdown_bills_session() -> None:
    global _SESSION
    if _SESSION is not None:
        _SESSION.dispose()
        _SESSION = None
