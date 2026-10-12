"""Read and update the Security Center's real persisted state."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from agent.permission import global_mode
from agent.permission.audit import activity_counts, record, recent
from agent.permission.security_policy import MODE_DEFINITIONS, effective_mode, effective_rules, resolve, validate_patch
from common.state_dir import mcp_config_file

_KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,79}$")


def global_policy() -> dict:
    from config import conf
    raw = conf().get("security_policy")
    return resolve(global_mode(), global_value=raw)


def save_global_policy(value: dict) -> dict:
    from config import conf, get_data_root, read_config_template
    clean = validate_patch(value, global_policy=True)
    current = conf()
    path = Path(get_data_root()) / "config.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else read_config_template()
    data["security_policy"] = clean
    _write_config(path, data)
    current["security_policy"] = clean
    record(operation="update", resource="global policy", decision="policy_change", reason="Global security policy updated.")
    return clean


def _write_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".security-tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(tmp, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=4)
    os.replace(tmp, path)


def _env_path() -> Path:
    from common.utils import expand_path
    return Path(expand_path("~/.stella/.env"))


def _env_keys() -> set[str]:
    path = _env_path()
    if not path.is_file():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name = line.split("=", 1)[0].strip()
            if _KEY.fullmatch(name):
                names.add(name)
    return names


def secrets() -> list[dict]:
    from config import MODEL_CONFIG_TO_ENV, conf
    names = {name: "credential store" for name in _env_keys()}
    cfg = conf()
    for key, value in cfg.items():
        if isinstance(key, str) and (key.endswith("_api_key") or key.endswith("_token")) and value:
            name = MODEL_CONFIG_TO_ENV.get(key, key.upper())
            names[name] = "model configuration" if name not in names else "model configuration + credential store"
    for entry in cfg.get("custom_providers") or []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("api_key") or "").strip()
        provider_id = str(entry.get("id") or "").strip()
        if not key or not provider_id:
            continue
        names[f"CUSTOM:{provider_id}"] = "custom model provider"
    return [{"name": name, "source": source, "configured": True} for name, source in sorted(names.items())]


def set_secret(name: str, value: str | None) -> None:
    if not _KEY.fullmatch(name):
        raise ValueError("invalid credential name")
    if value is not None and (not isinstance(value, str) or "\n" in value or "\r" in value):
        raise ValueError("invalid credential value")
    from config import MODEL_CONFIG_TO_ENV, conf, get_data_root, read_config_template, sync_model_config_to_env
    config_key = next((key for key, env_key in MODEL_CONFIG_TO_ENV.items() if env_key == name), name.lower())
    current = conf()
    if config_key in current and (config_key.endswith("_api_key") or config_key.endswith("_token")):
        if name in _env_keys():
            from agent.tools.env_config.env_config import EnvConfig
            env_tool = EnvConfig()
            entries = env_tool._read_env_file()
            entries.pop(name, None)
            env_tool._write_env_file(entries)
        current[config_key] = value or ""
        path = Path(get_data_root()) / "config.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else read_config_template()
        data[config_key] = value or ""
        _write_config(path, data)
        sync_model_config_to_env(current, overwrite=True)
        record(operation="delete" if value is None else "set", resource=f"credential:{name}", risk="L3",
               decision="policy_change", reason="Model credential status changed.")
        return
    from agent.tools.env_config.env_config import EnvConfig
    tool = EnvConfig()
    tool._ensure_env_file()
    entries = tool._read_env_file()
    if value is None:
        entries.pop(name, None)
        os.environ.pop(name, None)
    else:
        entries[name] = value
        os.environ[name] = value
    tool._write_env_file(entries)
    record(operation="delete" if value is None else "set", resource=f"credential:{name}", risk="L3",
           decision="policy_change", reason="Credential status changed in the credential store.")


def _connection_row(entry_id: str, name: str, *, configured: bool, available: bool,
                    scopes: list | None = None, detail: str = "") -> dict:
    return {
        "id": entry_id, "name": name, "configured": configured, "available": available,
        "connected": available, "scopes": list(scopes or []), "detail": detail,
    }


def connections(policy: dict | None = None) -> list[dict]:
    from config import conf
    policy = policy or global_policy()
    cfg = conf()
    github_token = bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or cfg.get("github_token"))
    github_verified = bool(github_token and cfg.get("github_verified_at"))
    try:
        from agent.briefing.settings import public_mailboxes
        mail = public_mailboxes()
        email_configured = bool(mail.get("configured"))
    except Exception:
        email_configured = bool(cfg.get("email_password") or os.environ.get("EMAIL_PASSWORD"))
    try:
        from agent.calendar.apple_sync import AppleCalendarSync
        calendar_status = AppleCalendarSync().status()
        calendar_configured = bool(calendar_status.get("connected") or calendar_status.get("authorization") == "full_access")
        calendar_available = bool(
            calendar_status.get("connected") and calendar_status.get("authorization") == "full_access"
        )
    except Exception:
        calendar_configured = bool(cfg.get("calendar_token") or os.environ.get("CALENDAR_TOKEN"))
        calendar_available = calendar_configured
    try:
        from agent.tools.browser.browser_env import capability_summary
        browser_ready = bool(capability_summary().get("ready"))
    except Exception:
        browser_ready = False
    try:
        from plugins import PluginManager
        plugins_ready = bool(getattr(PluginManager(), "instances", None))
    except Exception:
        plugins_ready = False
    entries = {
        "github": _connection_row(
            "github", "GitHub", configured=github_token, available=github_verified,
            detail="verified" if github_verified else ("configured" if github_token else ""),
        ),
        "email": _connection_row("email", "Email", configured=email_configured, available=email_configured),
        "calendar": _connection_row(
            "calendar", "Calendar", configured=calendar_configured, available=calendar_available,
        ),
        "browser": _connection_row("browser", "Browser", configured=browser_ready, available=browser_ready),
        "plugins": _connection_row("plugins", "Plugins", configured=plugins_ready, available=plugins_ready),
        "external_api": _connection_row("external_api", "External API", configured=False, available=False),
    }
    path = mcp_config_file()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            from agent.tools.tool_manager import ToolManager, _normalize_mcp_configs
            servers = _normalize_mcp_configs(raw.get("mcpServers", raw.get("mcp_servers", raw)))
            statuses = {}
            for manager in ToolManager.instances():
                statuses.update(manager.list_mcp_status())
            for item in servers:
                name = str(item.get("name") or "")
                if name:
                    ready = statuses.get(name) == "ready"
                    entries[f"mcp:{name}"] = _connection_row(
                        f"mcp:{name}", name, configured=True, available=ready,
                    )
        except (ValueError, OSError, TypeError):
            pass
    for key, value in entries.items():
        grant = policy.get("connections", {}).get(key, {})
        policy_scopes = grant.get("scopes")
        value.update({
            "allowed": grant.get("allowed", True),
            "scopes": list(policy_scopes) if isinstance(policy_scopes, list) else value["scopes"],
            "last_access": None,
        })
    for row in recent(limit=500, filters={"decision": "allow"}):
        resource = row.get("resource")
        if resource in entries and entries[resource]["last_access"] is None:
            entries[resource]["last_access"] = row.get("at")
    return list(entries.values())


def describe_task_permission(task: dict) -> dict:
    """Resolve one background task's effective run permission for display."""
    action = task.get("action") if isinstance(task.get("action"), dict) else {}
    session_id = (
        action.get("execution_session_id")
        or action.get("source_session_id")
        or None
    )
    project = action.get("execution_project_dir") or None
    if project:
        project = str(project)
    if session_id and not project:
        from agent.workspace import project_store
        try:
            project = project_store.get_project_dir(session_id)
        except ValueError:
            project = None
    explicit = task.get("run_permission_mode")
    conversation_mode = action.get("conversation_mode")
    base = {
        "id": task.get("id"),
        "name": task.get("name") or task.get("id") or "",
        "enabled": bool(task.get("enabled")),
        "conversation_mode": conversation_mode,
        "execution_session_id": session_id,
        "execution_project_dir": project,
        "run_permission_mode": explicit if explicit in {"read-only", "workspace-write", "full-access"} else None,
    }
    if explicit in {"read-only", "workspace-write", "full-access"}:
        return {**base, "effective_mode": explicit, "permission_source": "independent", "unknown": False,
                "policy_error": None}
    if not session_id and not project:
        return {**base, "effective_mode": None, "permission_source": "unspecified", "unknown": True,
                "policy_error": "Task has no bound conversation or independent permission."}
    try:
        policy = resolve(global_mode(), project_dir=project, session_id=session_id)
    except (ValueError, OSError) as error:
        return {**base, "effective_mode": None, "permission_source": "unknown", "unknown": True,
                "policy_error": str(error)}
    if policy.get("error"):
        return {**base, "effective_mode": None, "permission_source": "unknown", "unknown": True,
                "policy_error": policy.get("error")}
    source = "project" if project else ("conversation" if session_id else "global")
    return {**base, "effective_mode": effective_mode(policy), "permission_source": source,
            "unknown": False, "policy_error": None}


def background_tasks() -> list[dict]:
    """List background tasks from the same live store the scheduler API uses."""
    from agent.todos.scheduler_link import default_scheduler_store
    store = default_scheduler_store()
    return [describe_task_permission(task) for task in store.list_tasks()]


def background_task_summary(tasks: list[dict] | None = None) -> dict:
    rows = tasks if tasks is not None else background_tasks()
    modes = {"read-only": 0, "workspace-write": 0, "full-access": 0, "custom": 0}
    unknown = 0
    enabled = paused = 0
    for row in rows:
        if row.get("enabled"):
            enabled += 1
        else:
            paused += 1
        if row.get("unknown") or not row.get("effective_mode"):
            unknown += 1
            continue
        mode = row["effective_mode"]
        if mode in modes:
            modes[mode] += 1
        else:
            modes["custom"] += 1
    return {
        "total": len(rows),
        "enabled": enabled,
        "paused": paused,
        "modes": modes,
        "unknown": unknown,
        "available": True,
    }


def overview(session_id: str | None = None, agent_id: str | None = None) -> dict:
    from agent.workspace import project_store, session_prefs
    project = project_store.get_project_dir(session_id, agent_id) if session_id else None
    mode = global_mode()
    effective = resolve(mode, project_dir=project, session_id=session_id, agent_id=agent_id)
    project_patch = project_store.get_security_policy(project) if project else {}
    conversation_patch = session_prefs.get_prefs(session_id, agent_id).get("security_policy", {}) if session_id else {}
    if project:
        source = "project"
    elif conversation_patch:
        source = "session"
    else:
        source = "global"
    from agent.workspace.context import resolve_context
    work_root = str(resolve_context(session_id, agent_id).root)
    from agent.permission.gateway import SecurityGateway
    from agent.permission.process_sandbox import capability
    isolation = capability()
    if effective_mode(effective) == "full-access" and isolation["status"] == "enabled":
        isolation = {
            **isolation,
            "reason": (isolation.get("reason") or "")
            + " 完全访问仍拦截其他会话的私有工作区、托管数据、凭据和 Apple 系统授权。",
        }
    activity = [row for row in recent(limit=200) if row.get("at", 0) >= time.time() - 7 * 86400]
    denials = [row for row in activity if row.get("decision") == "deny"]
    high = [row for row in activity if row.get("risk") in ("L3", "L4")]
    counts = activity_counts(days=7)
    active_pending = SecurityGateway.pending()
    all_connections = connections()
    all_secrets = secrets()
    try:
        task_rows = background_tasks()
        task_summary = background_task_summary(task_rows)
    except (OSError, ValueError, TypeError):
        task_rows = []
        task_summary = {"total": None, "enabled": None, "paused": None, "modes": None,
                        "unknown": None, "available": False}
    try:
        from agent.permission.privacy import inventory as privacy_inventory
        privacy = privacy_inventory()
    except (OSError, ValueError, TypeError):
        privacy = {"available": False, "categories": []}
    return {
        "global_policy": global_policy(), "effective_policy": effective,
        "effective_mode": effective_mode(effective), "effective_rules": effective_rules(effective),
        "policy_source": source, "mode_definitions": MODE_DEFINITIONS,
        "authorized_roots": [work_root, *(effective.get("extra_roots") or [])],
        "policy_error": effective.get("error"),
        "process_isolation": isolation,
        "project": project, "project_policy": project_patch,
        "projects": [{**item, "policy": project_store.get_security_policy(item["path"])}
                     for item in project_store.list_known_projects()],
        "conversation_policy": conversation_patch,
        "connections": all_connections, "secrets": all_secrets,
        "background_tasks": task_rows,
        "privacy": privacy,
        "summary": {"status": "attention" if denials or active_pending else "normal",
                    "app_password_set": bool(__import__("config").conf().get("web_password")),
                    "connection_count": sum(
                        1 for item in all_connections
                        if item.get("available", item.get("connected")) and item.get("allowed", True)
                    ),
                    "secret_count": len(all_secrets), "recent_high_risk": high[:5], "recent_denials": denials[:5],
                    "activity_counts": counts,
                    "background_tasks": task_summary},
    }
