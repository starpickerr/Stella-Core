"""Core gateway that routes Tasks (todos) calls to the stella.tasks plugin worker."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from core.plugins.authz import DEFAULT_AUTHZ
from core.plugins.caller import issue_compatibility_grant, managed_plugin_route, plugin_user_id, serialized_gateway, user_grant_ref
from core.plugins.host import PluginSession
from core.plugins.runtime_hub import DEFAULT_REGISTRY

CONTRACT = "stella.tasks@1"
PLUGIN_ID = "stella.tasks"

_SESSION: PluginSession | None = None
_GRANT_REF = "tasks-default-grant"

# Positional parameter names per method; must match the plugin's SERVICE_DESCRIPTORS
# (tests/test_todos_plugin_gateway.py enforces this).
TODOS_READ_METHODS: dict[str, tuple[str, ...]] = {
    "get_todo": ("todo_id",),
    "list_todos": ("start", "end", "include_completed"),
    "list_todos_focus": ("today",),
    "list_uncertain_reminders": (),
    "categories": (),
    "get_category": ("category_id",),
    "has_source_tombstone": ("source_keys",),
    "pending_scheduler_links": (),
}
TODOS_WRITE_METHODS: dict[str, tuple[str, ...]] = {
    "create_todo": ("payload",),
    "update_todo": ("todo_id", "payload"),
    "delete_todo": ("todo_id", "preserve_children"),
    "complete_todo": ("todo_id", "completed", "force"),
    "complete_checklist_item": ("todo_id", "item_id", "completed"),
    "change_todo_status": ("todo_id", "status", "force"),
    "add_subtask": ("parent_id", "payload"),
    "move_todo": ("todo_id", "parent_id", "position"),
    "add_dependency": ("todo_id", "prerequisite_id"),
    "remove_dependency": ("todo_id", "prerequisite_id"),
    "claim_due_todo_notifications": ("now",),
    "claim_desktop_reminders": ("now", "limit"),
    "acknowledge_desktop_reminder": ("delivery_id", "claim_id", "shown", "error"),
    "retry_uncertain_reminder": ("delivery_id",),
    "queue_scheduled_reminder": ("todo_id", "expected_at", "now"),
    "ingest_briefing_revision": ("detail", "revision"),
    "sync_briefing_facts": ("todo_id", "changes", "baseline", "force"),
    "upsert_external_todo": ("source_key", "payload", "todo_id", "reconciled"),
    "delete_external_todo": ("source_key", "confirm"),
    "create_category": ("payload",),
    "update_category": ("category_id", "payload"),
    "delete_category": ("category_id",),
    "set_todo_category": ("todo_id", "category_id"),
    "complete_scheduler_link": ("todo_id", "desired_at", "outcome", "error"),
}
TODOS_METHOD_PARAMS = {**TODOS_READ_METHODS, **TODOS_WRITE_METHODS}


def todos_plugin_enabled() -> bool:
    return managed_plugin_route("stella.tasks", os.environ.get("STELLA_TODOS_PLUGIN", ""))


def _plugin_root() -> Path:
    from core.plugins.roots import resolve_plugin_package_root

    return resolve_plugin_package_root(
        plugin_id=PLUGIN_ID,
        env_var="STELLA_TODOS_PLUGIN_ROOT",
        folder_name="tasks",
    )


@serialized_gateway
def ensure_todos_session() -> PluginSession:
    global _SESSION
    if _SESSION is not None and (_SESSION.user_id != plugin_user_id() or not _SESSION.is_running):
        shutdown_todos_session()
    if _SESSION is not None:
        return _SESSION
    user_id = plugin_user_id()
    session = PluginSession(
        _plugin_root(),
        source_label="first-party-external",
        registry=DEFAULT_REGISTRY,
        user_id=user_id,
        authz=DEFAULT_AUTHZ,
    )
    if os.environ.get("STELLA_ALLOW_REPO_IMPORT") in {"1", "true", "yes"}:
        os.environ.setdefault("STELLA_REPO_ROOT", str(Path(__file__).resolve().parents[2]))
    issue_compatibility_grant(DEFAULT_AUTHZ,
        grant_ref=user_grant_ref(_GRANT_REF),
        plugin_id=PLUGIN_ID,
        user_id=user_id,
        capabilities=["tasks.read", "tasks.write", "plugin.invoke"],
        purposes=["interactive", "tool", "job", "any"],
        replace_existing=False,
    )
    session.start()
    _SESSION = session
    return session


@serialized_gateway
def invoke_todos(
    method: str,
    params: dict[str, Any],
    *,
    db_path: Path,
    legacy_calendar_db_path: Path | None = None,
) -> dict[str, Any]:
    if method not in TODOS_METHOD_PARAMS:
        raise ValueError(f"unknown todos plugin method: {method}")
    session = ensure_todos_session()
    write = method in TODOS_WRITE_METHODS
    handle: dict[str, Any] = {"dbPath": str(db_path), "namespace": PLUGIN_ID}
    if legacy_calendar_db_path is not None:
        handle["legacyCalendarDbPath"] = str(legacy_calendar_db_path)
    payload = dict(params)
    idem = payload.pop("idempotencyKey", None)
    return session.invoke_contract(
        contract=CONTRACT,
        method=method,
        input_payload=payload,
        origin="system",
        grant_ref=user_grant_ref(_GRANT_REF),
        permissions=("tasks.write",) if write else ("tasks.read",),
        purpose="interactive",
        idempotency_key=idem or (uuid.uuid4().hex if write else None),
        data_handle=handle,
    )


@serialized_gateway
def shutdown_todos_session() -> None:
    global _SESSION
    if _SESSION is not None:
        _SESSION.dispose()
        _SESSION = None
