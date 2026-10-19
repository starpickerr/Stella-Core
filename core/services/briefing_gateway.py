"""Core gateway that routes Briefing calls to the stella.briefing plugin worker."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from core.plugins.authz import DEFAULT_AUTHZ
from core.plugins.caller import issue_compatibility_grant, managed_plugin_route, plugin_user_id, serialized_gateway, user_grant_ref
from core.plugins.host import PluginSession
from core.plugins.runtime_hub import DEFAULT_REGISTRY

CONTRACT = "stella.briefing@1"
PLUGIN_ID = "stella.briefing"

_SESSION: PluginSession | None = None
_GRANT_REF = "briefing-default-grant"

# Positional parameter names per method; must match the plugin's SERVICE_DESCRIPTORS
# (tests/test_briefing_plugin_gateway.py enforces this).
BRIEFING_READ_METHODS: dict[str, tuple[str, ...]] = {
    "list_briefings": ("status",),
    "get_briefing": ("briefing_id",),
    "get_revision": ("briefing_id", "number"),
    "briefing_for_date": ("briefing_date",),
    "list_rules": ("enabled_only", "source"),
    "get_rule": ("rule_id",),
    "get_cursor": ("source", "account_id", "cursor_key"),
    "build_source_item": ("payload",),
    "list_action_rules": (),
    "get_preferences": (),
    "get_overview": (),
    "get_action_targets": ("kind", "query"),
    "list_revisions": ("briefing_id",),
    "window_candidates": ("start", "end", "accounts"),
    "staged_window_candidates": ("run_id", "start", "end", "accounts"),
    "list_sources": (),
    "select_sources": ("selectors",),
}
BRIEFING_WRITE_METHODS: dict[str, tuple[str, ...]] = {
    "start_briefing": ("briefing_date", "title"),
    "complete_briefing": ("briefing_id", "payload"),
    "update_item_status": ("item_id", "status"),
    "upsert_source_item": ("payload",),
    "create_rule": ("payload",),
    "update_rule": ("rule_id", "payload"),
    "delete_rule": ("rule_id",),
    "set_cursor": ("source", "cursor_key", "cursor_value", "account_id"),
    "update_action": ("item_id", "payload"),
    "create_action_rule": ("payload",),
    "delete_action_rule": ("rule_id",),
    "update_preferences": ("payload",),
    "stage_source_items": ("run_id", "rows"),
    "stage_source_errors": ("run_id", "source", "account_id", "errors"),
    "dispatch_outbox": ("limit",),
    "run_pipeline": ("briefing_date", "operation", "trigger", "sources", "draft", "run_at"),
}
BRIEFING_METHOD_PARAMS = {**BRIEFING_READ_METHODS, **BRIEFING_WRITE_METHODS}
_SOURCE_DIRECTORY_METHODS = frozenset({"list_sources", "select_sources"})


def briefing_plugin_enabled() -> bool:
    return managed_plugin_route("stella.briefing", os.environ.get("STELLA_BRIEFING_PLUGIN", ""))


def _plugin_root() -> Path:
    from core.plugins.roots import resolve_plugin_package_root

    return resolve_plugin_package_root(
        plugin_id=PLUGIN_ID,
        env_var="STELLA_BRIEFING_PLUGIN_ROOT",
        folder_name="briefing",
    )


@serialized_gateway
def ensure_briefing_session() -> PluginSession:
    global _SESSION
    if _SESSION is not None and (_SESSION.user_id != plugin_user_id() or not _SESSION.is_running):
        shutdown_briefing_session()
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
        capabilities=["briefing.read", "briefing.write", "plugin.invoke"],
        purposes=["interactive", "tool", "job", "any"],
        replace_existing=False,
    )
    session.start()
    _SESSION = session
    return session


@serialized_gateway
def invoke_briefing(
    method: str,
    params: dict[str, Any],
    *,
    db_path: Path,
    source_directory: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if method not in BRIEFING_METHOD_PARAMS:
        raise ValueError(f"unknown briefing plugin method: {method}")
    session = ensure_briefing_session()
    write = method in BRIEFING_WRITE_METHODS
    handle: dict[str, Any] = {"dbPath": str(db_path), "namespace": PLUGIN_ID}
    if method in _SOURCE_DIRECTORY_METHODS:
        if source_directory is None:
            from core.services.sources_public import DEFAULT_SOURCE_DIRECTORY

            source_directory = DEFAULT_SOURCE_DIRECTORY.list_for_user()
        handle["sourceDirectory"] = source_directory
    payload = dict(params)
    idem = payload.pop("idempotencyKey", None)
    return session.invoke_contract(
        contract=CONTRACT,
        method=method,
        input_payload=payload,
        origin="system",
        grant_ref=user_grant_ref(_GRANT_REF),
        permissions=("briefing.write",) if write else ("briefing.read",),
        purpose="interactive",
        idempotency_key=idem or (uuid.uuid4().hex if write else None),
        data_handle=handle,
    )


@serialized_gateway
def shutdown_briefing_session() -> None:
    global _SESSION
    if _SESSION is not None:
        _SESSION.dispose()
        _SESSION = None
