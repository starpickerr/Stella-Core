"""Core gateway that routes Agent Hub calls to the stella.agent-hub plugin worker.

Core owns ExecutionService (status/cancel/lease/artifacts). The plugin owns
Provider configs and external session/run mappings only.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from core.plugins.authz import DEFAULT_AUTHZ
from core.plugins.caller import issue_compatibility_grant, managed_plugin_route, plugin_user_id, serialized_gateway, user_grant_ref
from core.plugins.host import PluginSession
from core.plugins.runtime_hub import DEFAULT_REGISTRY

CONTRACT = "stella.agent-hub@1"
PLUGIN_ID = "stella.agent-hub"

_SESSION: PluginSession | None = None
_GRANT_REF = "agent-hub-default-grant"

AGENT_HUB_READ_METHODS: dict[str, tuple[str, ...]] = {
    "list_catalog": (),
    "status_overview": (),
    "list_providers": ("enabled_only",),
    "get_provider": ("provider_config_id",),
    "probe_provider": ("provider_config_id",),
    "select_provider": ("selector",),
    "get_external_run": ("execution_id",),
    "list_external_runs": ("limit",),
    "provider_observe": ("execution_id",),
}
AGENT_HUB_WRITE_METHODS: dict[str, tuple[str, ...]] = {
    "ensure_defaults": (),
    "upsert_provider": ("provider",),
    "delete_provider": ("provider_config_id",),
    "map_external_run": ("mapping",),
    "provider_start": ("provider_config_id", "task"),
    "provider_cancel": ("execution_id",),
}
AGENT_HUB_METHOD_PARAMS = {**AGENT_HUB_READ_METHODS, **AGENT_HUB_WRITE_METHODS}

_SETTINGS_ID = "agent-hub.preferences"
_SETTINGS_CATEGORY = "providers"
_BINARY_KEYS = {
    "codex-app-server": "codex_binary_path",
    "codex-cli": "codex_binary_path",
    "cursor-acp": "cursor_binary_path",
    "cursor-cli": "cursor_binary_path",
    "claude-code": "claude_binary_path",
}


def agent_hub_plugin_enabled() -> bool:
    return managed_plugin_route("stella.agent-hub", os.environ.get("STELLA_AGENT_HUB_PLUGIN", ""))


def read_user_preferences(*, owner_user_id: str = "") -> dict[str, Any]:
    """Read Agent Hub settings from Core management store (empty if not installed)."""
    try:
        from core.plugins.management import default_store
        from core.plugins.settings import PluginSettingsService

        snap = PluginSettingsService(default_store()).read(
            PLUGIN_ID,
            owner_user_id or plugin_user_id(),
            _SETTINGS_ID,
            _SETTINGS_CATEGORY,
        )
        values = snap.get("values") or {}
        return values if isinstance(values, dict) else {}
    except Exception:
        return {}


def apply_user_preferences(**kwargs: Any) -> dict[str, Any]:
    """Ensure default providers exist and sync binary paths / enablement from settings."""
    values = read_user_preferences(owner_user_id=str(kwargs.get("owner_user_id") or ""))
    created = invoke_ok("ensure_defaults", **kwargs)
    new_ids = {row["providerConfigId"] for row in created}
    providers = invoke_ok("list_providers", {}, **kwargs) or []
    updated: list[dict[str, Any]] = []
    for row in providers:
        local_id = row.get("providerLocalId")
        key = _BINARY_KEYS.get(local_id or "")
        if not key:
            continue
        path = (str(values.get(key) or "").strip() or None) if key in values else row.get("binaryPath")
        enabled = bool(row.get("enabled")) or (row["providerConfigId"] in new_ids and bool(path))
        desired = {
            "providerConfigId": row["providerConfigId"],
            "providerLocalId": local_id,
            "displayName": row.get("displayName"),
            "binaryPath": path,
            "enabled": enabled,
            "settings": row.get("settings") or {},
            "lastProbe": row.get("lastProbe"),
        }
        if row.get("binaryPath") == path and bool(row.get("enabled")) == enabled:
            continue
        updated.append(invoke_ok("upsert_provider", {"provider": desired}, **kwargs))
    return {
        "preferences": values,
        "updated": updated,
        "defaultProviderLocalId": str(values.get("default_provider_local_id") or "").strip(),
    }


def resolve_provider_selector(
    selector: dict[str, Any] | None = None,
    *,
    owner_user_id: str = "",
) -> dict[str, Any]:
    """Fill empty selector from settings default_provider_local_id when set."""
    resolved = dict(selector or {})
    if resolved.get("providerConfigId") or resolved.get("providerLocalId"):
        return resolved
    default = str(
        read_user_preferences(owner_user_id=owner_user_id).get("default_provider_local_id") or ""
    ).strip()
    if default:
        resolved["providerLocalId"] = default
    return resolved


def _plugin_root() -> Path:
    from core.plugins.roots import resolve_plugin_package_root

    return resolve_plugin_package_root(
        plugin_id=PLUGIN_ID,
        env_var="STELLA_AGENT_HUB_PLUGIN_ROOT",
        folder_name="agent-hub",
    )


def agent_hub_db_path() -> Path:
    from common.state_dir import agent_hub_db

    return agent_hub_db(ensure=True)


@serialized_gateway
def ensure_agent_hub_session() -> PluginSession:
    global _SESSION
    if _SESSION is not None and (_SESSION.user_id != plugin_user_id() or not _SESSION.is_running):
        shutdown_agent_hub_session()
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
    issue_compatibility_grant(
        DEFAULT_AUTHZ,
        grant_ref=user_grant_ref(_GRANT_REF),
        plugin_id=PLUGIN_ID,
        user_id=user_id,
        capabilities=["agent_hub.read", "agent_hub.write", "plugin.invoke"],
        purposes=["interactive", "tool", "job", "any"],
        replace_existing=False,
    )
    session.start()
    _SESSION = session
    return session


@serialized_gateway
def invoke_agent_hub(
    method: str,
    params: dict[str, Any],
    *,
    db_path: Path | None = None,
    agent_id: str = "default",
    owner_user_id: str = "",
) -> dict[str, Any]:
    if not agent_hub_plugin_enabled():
        raise RuntimeError("stella.agent-hub plugin is disabled")
    if method not in AGENT_HUB_METHOD_PARAMS:
        raise ValueError(f"unknown agent-hub plugin method: {method}")
    execution = None
    if method == "provider_start":
        from common.state_dir import executions_dir
        from core.execution import execution_service
        root = executions_dir(ensure=True)
        service = execution_service(db_path=root / "executions.db", work_root=root / "work")
        task = params.get("task") or {}
        try:
            execution = service.get(task.get("executionId") or "")
        except KeyError as exc:
            raise PermissionError("provider start requires a Core-owned execution lease") from exc
        if (execution["ownerPluginId"] != PLUGIN_ID or execution["status"] != "running"
                or not execution.get("workspaceLeaseRef") or not execution.get("workspacePath")
                or task.get("workspacePath") != execution["workspacePath"]
                or task.get("attemptId") != execution["attemptId"]):
            raise PermissionError("provider task does not match the Core execution lease")
        task = {**task, "goal": execution["goal"], "budget": execution["budget"],
                "workspaceLeaseRef": execution["workspaceLeaseRef"], "acceptance": execution["acceptance"]}
        params = {**params, "task": task}
    session = ensure_agent_hub_session()
    write = method in AGENT_HUB_WRITE_METHODS
    path = Path(db_path) if db_path else agent_hub_db_path()
    handle = {
        "dbPath": str(path),
        "namespace": PLUGIN_ID,
        "agentId": agent_id,
        "userId": owner_user_id or "",
    }
    if execution is not None:
        handle["executionTask"] = dict(params["task"])
    payload = dict(params)
    idem = payload.pop("idempotencyKey", None)
    return session.invoke_contract(
        contract=CONTRACT,
        method=method,
        input_payload=payload,
        origin="system",
        grant_ref=user_grant_ref(_GRANT_REF),
        permissions=("agent_hub.write",) if write else ("agent_hub.read",),
        purpose="interactive",
        idempotency_key=idem or (uuid.uuid4().hex if write else None),
        data_handle=handle,
    )


def invoke_ok(method: str, params: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    result = invoke_agent_hub(method, params or {}, **kwargs)
    if result.get("status") != "succeeded":
        message = (result.get("error") or {}).get("message") or f"agent-hub returned {result.get('status')}"
        raise RuntimeError(message)
    return result.get("value")


@serialized_gateway
def shutdown_agent_hub_session() -> None:
    global _SESSION
    if _SESSION is not None:
        _SESSION.dispose()
        _SESSION = None
