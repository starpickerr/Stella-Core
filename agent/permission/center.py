"""Read and update the Security Center's real persisted state."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from agent.permission import global_mode
from agent.permission.audit import record, recent
from agent.permission.security_policy import legacy_policy, resolve, validate_patch
from common.state_dir import mcp_config_file

_KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,79}$")


def global_policy() -> dict:
    from config import conf
    raw = conf().get("security_policy")
    return resolve(global_mode(), global_value=raw) if isinstance(raw, dict) else legacy_policy(global_mode())


def save_global_policy(value: dict) -> dict:
    from config import conf, get_data_root, read_config_template
    clean = validate_patch(value, global_policy=True)
    current = conf()
    current["security_policy"] = clean
    path = Path(get_data_root()) / "config.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else read_config_template()
    data["security_policy"] = clean
    _write_config(path, data)
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
    for key, value in conf().items():
        if isinstance(key, str) and (key.endswith("_api_key") or key.endswith("_token")) and value:
            name = MODEL_CONFIG_TO_ENV.get(key, key.upper())
            names[name] = "model configuration" if name not in names else "model configuration + credential store"
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


def connections(policy: dict | None = None) -> list[dict]:
    from config import conf
    policy = policy or global_policy()
    cfg = conf()
    entries = {
        "github": {"name": "GitHub", "connected": bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or cfg.get("github_token")), "scopes": []},
        "email": {"name": "Email", "connected": bool(cfg.get("email_password") or os.environ.get("EMAIL_PASSWORD")), "scopes": []},
        "calendar": {"name": "Calendar", "connected": bool(cfg.get("calendar_token") or os.environ.get("CALENDAR_TOKEN")), "scopes": []},
        "browser": {"name": "Browser", "connected": True, "scopes": ["*"]},
        "plugins": {"name": "Plugins", "connected": False, "scopes": []},
        "external_api": {"name": "External API", "connected": False, "scopes": ["*"]},
    }
    path = mcp_config_file()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            from agent.tools.tool_manager import _normalize_mcp_configs
            servers = _normalize_mcp_configs(raw.get("mcpServers", raw.get("mcp_servers", raw)))
            from agent.tools.tool_manager import ToolManager
            statuses = {}
            for manager in ToolManager.instances():
                statuses.update(manager.list_mcp_status())
            for item in servers:
                name = str(item.get("name") or "")
                if name:
                    entries[f"mcp:{name}"] = {"name": name, "connected": statuses.get(name) == "ready", "scopes": []}
        except (ValueError, OSError, TypeError):
            pass
    for key, value in entries.items():
        grant = policy.get("connections", {}).get(key, {})
        value.update({"id": key, "allowed": grant.get("allowed", True),
                      "scopes": grant.get("scopes") or value["scopes"], "last_access": None})
    for row in recent(limit=500, filters={"decision": "allow"}):
        resource = row.get("resource")
        if resource in entries and entries[resource]["last_access"] is None:
            entries[resource]["last_access"] = row.get("at")
    return list(entries.values())


def overview(session_id: str | None = None, agent_id: str | None = None) -> dict:
    from agent.workspace import project_store, session_prefs
    project = project_store.get_project_dir(session_id, agent_id) if session_id else None
    mode = global_mode()
    effective = resolve(mode, project_dir=project, session_id=session_id, agent_id=agent_id)
    from agent.permission.gateway import SecurityGateway
    activity = [row for row in recent(limit=200) if row.get("at", 0) >= time.time() - 7 * 86400]
    denials = [row for row in activity if row.get("decision") == "deny"]
    high = [row for row in activity if row.get("risk") in ("L3", "L4")]
    active_pending = SecurityGateway.pending()
    all_connections = connections()
    all_secrets = secrets()
    return {
        "global_policy": global_policy(), "effective_policy": effective,
        "project": project, "project_policy": project_store.get_security_policy(project) if project else {},
        "projects": [{**item, "policy": project_store.get_security_policy(item["path"])}
                     for item in project_store.list_known_projects()],
        "conversation_policy": session_prefs.get_prefs(session_id, agent_id).get("security_policy", {}) if session_id else {},
        "connections": all_connections, "secrets": all_secrets,
        "summary": {"status": "attention" if denials or active_pending else "normal",
                    "app_password_set": bool(__import__("config").conf().get("web_password")),
                    "connection_count": sum(1 for item in all_connections if item["connected"] and item["allowed"]),
                    "secret_count": len(all_secrets), "recent_high_risk": high[:5], "recent_denials": denials[:5]},
    }
