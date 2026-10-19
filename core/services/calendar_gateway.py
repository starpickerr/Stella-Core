"""Core gateway that routes Calendar calls to the stella.calendar plugin worker when enabled."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from core.plugins.authz import DEFAULT_AUTHZ
from core.plugins.caller import plugin_user_id, serialized_gateway, user_grant_ref
from core.plugins.host import PluginSession
from core.plugins.runtime_hub import DEFAULT_REGISTRY

_SESSION: PluginSession | None = None
_GRANT_REF = "calendar-default-grant"

READ_METHODS = frozenset({
    "categories", "get_category", "get_event", "list_events", "has_source_tombstone",
})
WRITE_METHODS = frozenset({
    "create_category", "update_category", "delete_category", "set_event_category",
    "create_event", "update_event", "delete_event", "upsert_external_event",
    "exclude_occurrence", "import_china_holidays", "create_special_date",
    "import_special_dates", "ingest_briefing_revision", "sync_briefing_facts",
})


def calendar_plugin_enabled() -> bool:
    return os.environ.get("STELLA_CALENDAR_PLUGIN", "").strip() in {"1", "true", "yes"}


@serialized_gateway
def ensure_calendar_session(db_path: Path | None = None) -> PluginSession:
    global _SESSION
    if _SESSION is not None and (_SESSION.user_id != plugin_user_id() or not _SESSION.is_running):
        shutdown_calendar_session()
    if _SESSION is not None:
        return _SESSION
    from core.plugins.roots import resolve_plugin_package_root

    root = resolve_plugin_package_root(
        plugin_id="stella.calendar",
        env_var="STELLA_CALENDAR_PLUGIN_ROOT",
        folder_name="calendar",
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
    DEFAULT_AUTHZ.issue(
        grant_ref=user_grant_ref(_GRANT_REF),
        plugin_id="stella.calendar",
        user_id=user_id,
        capabilities=["calendar.read", "calendar.write", "plugin.invoke"],
        purposes=["interactive", "tool", "job", "any"],
        replace_existing=False,
    )
    session.start()
    _SESSION = session
    return session


@serialized_gateway
def invoke_calendar(method: str, params: dict[str, Any], *, db_path: Path) -> dict[str, Any]:
    if method not in READ_METHODS and method not in WRITE_METHODS:
        raise ValueError(f"unknown calendar plugin method: {method}")
    session = ensure_calendar_session(db_path)
    write = method in WRITE_METHODS
    permissions = ("calendar.write",) if write else ("calendar.read",)
    payload = dict(params)
    idem = payload.pop("idempotencyKey", None)
    return session.invoke_contract(
        contract="stella.calendar@1",
        method=method,
        input_payload=payload,
        origin="system",
        grant_ref=user_grant_ref(_GRANT_REF),
        permissions=permissions,
        purpose="interactive",
        idempotency_key=idem or (uuid.uuid4().hex if write else None),
        data_handle={"dbPath": str(db_path), "namespace": "stella.calendar"},
    )


@serialized_gateway
def shutdown_calendar_session() -> None:
    global _SESSION
    if _SESSION is not None:
        _SESSION.dispose()
        _SESSION = None
