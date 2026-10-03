"""Persisted security policy and scoped inheritance for tool execution."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.permission.policy import FULL_ACCESS, READ_ONLY, WORKSPACE_WRITE

RULES = (
    "managed", "workspace_read", "workspace_write", "workspace_outside",
    "shell", "git", "network", "install", "background", "external", "high_risk",
)
VALUES = {"allow", "confirm", "deny"}
PRESETS = {
    "strict": {"managed": "allow", "workspace_read": "allow", "workspace_write": "deny",
               "workspace_outside": "deny", "shell": "deny", "git": "deny", "network": "confirm",
               "install": "deny", "background": "deny", "external": "confirm", "high_risk": "confirm"},
    "standard": {"managed": "allow", "workspace_read": "allow", "workspace_write": "allow",
                 "workspace_outside": "deny", "shell": "allow", "git": "allow", "network": "allow",
                 "install": "confirm", "background": "confirm", "external": "allow", "high_risk": "confirm"},
    "custom": {"managed": "allow", "workspace_read": "allow", "workspace_write": "allow",
               "workspace_outside": "allow", "shell": "allow", "git": "allow", "network": "allow",
               "install": "allow", "background": "allow", "external": "allow", "high_risk": "confirm"},
}


def legacy_policy(mode: str) -> dict:
    preset = {READ_ONLY: "strict", WORKSPACE_WRITE: "standard", FULL_ACCESS: "custom"}.get(mode, "strict")
    return {"preset": preset, "rules": {}, "connections": {}}


def validate_patch(value: Any, *, global_policy: bool = False) -> dict:
    if not isinstance(value, dict):
        raise ValueError("security policy must be an object")
    unknown = set(value) - {"preset", "rules", "connections", "extra_roots"}
    if unknown:
        raise ValueError(f"unknown security policy fields: {', '.join(sorted(unknown))}")
    result = {}
    if "preset" in value:
        if value["preset"] not in PRESETS:
            raise ValueError("unknown security preset")
        result["preset"] = value["preset"]
    if "rules" in value:
        rules = value["rules"]
        if not isinstance(rules, dict) or any(k not in RULES or v not in VALUES for k, v in rules.items()):
            raise ValueError("invalid security rule")
        result["rules"] = dict(rules)
    if "connections" in value:
        connections = value["connections"]
        if not isinstance(connections, dict) or any(
            not isinstance(k, str) or not k or not isinstance(v, dict)
            or set(v) - {"allowed", "scopes"}
            or not isinstance(v.get("allowed", True), bool)
            or not isinstance(v.get("scopes", []), list)
            or any(not isinstance(s, str) for s in v.get("scopes", []))
            for k, v in connections.items()
        ):
            raise ValueError("invalid connection grant")
        result["connections"] = deepcopy(connections)
    if "extra_roots" in value:
        roots = value["extra_roots"]
        if global_policy or not isinstance(roots, list) or any(not isinstance(p, str) or not p.strip() for p in roots):
            raise ValueError("extra roots are only valid for a project or conversation")
        result["extra_roots"] = list(dict.fromkeys(roots))
    return result


def merge(base: dict, patch: dict) -> dict:
    result = deepcopy(base)
    if "preset" in patch:
        if patch["preset"] != result.get("preset"):
            result["rules"] = {}
        result["preset"] = patch["preset"]
    for key in ("rules", "connections"):
        result.setdefault(key, {}).update(deepcopy(patch.get(key) or {}))
    if "extra_roots" in patch:
        result["extra_roots"] = list(patch["extra_roots"])
    return result


def resolve(mode: str, *, project_dir: str | None = None, session_id: str | None = None,
            agent_id: str | None = None, global_value: dict | None = None) -> dict:
    """Global -> project difference -> conversation difference."""
    if global_value is None:
        from config import conf
        global_value = conf().get("security_policy")
    base = legacy_policy(mode)
    if isinstance(global_value, dict):
        try:
            base = merge(base, validate_patch(global_value, global_policy=True))
        except ValueError:
            return legacy_policy(READ_ONLY)
    if project_dir:
        from agent.workspace import project_store
        try:
            base = merge(base, validate_patch(project_store.get_security_policy(project_dir)))
        except ValueError:
            return legacy_policy(READ_ONLY)
    if session_id:
        from agent.workspace import session_prefs
        pref = session_prefs.get_prefs(session_id, agent_id)
        if pref.get("security_policy"):
            try:
                base = merge(base, validate_patch(pref["security_policy"]))
            except ValueError:
                return legacy_policy(READ_ONLY)
    return base


def rule(policy: dict, name: str) -> str:
    return policy.get("rules", {}).get(name, PRESETS[policy.get("preset", "standard")][name])


def describe(policy: dict, language: str = "zh", workspace: str | None = None) -> list[str]:
    """Short prompt guidance from the same resolved policy used by tool execution."""
    if language == "en":
        lines = ["## Security policy", "", f"Preset: {policy.get('preset', 'standard')}.",
                 f"Agent-managed Skills and internal state: {rule(policy, 'managed')}.",
                 f"Workspace reads: {rule(policy, 'workspace_read')}; writes: {rule(policy, 'workspace_write')}.",
                 f"Access outside the authorized workspace: {rule(policy, 'workspace_outside')}.",
                 f"Shell: {rule(policy, 'shell')}; Git: {rule(policy, 'git')}; network: {rule(policy, 'network')}; high risk: {rule(policy, 'high_risk')}."]
    else:
        lines = ["## 安全策略", "", f"模式：{policy.get('preset', 'standard')}。",
                 f"Agent 内部 Skills 与状态：{rule(policy, 'managed')}。",
                 f"工作区读取：{rule(policy, 'workspace_read')}；写入：{rule(policy, 'workspace_write')}。",
                 f"授权工作区外访问：{rule(policy, 'workspace_outside')}。",
                 f"终端：{rule(policy, 'shell')}；Git：{rule(policy, 'git')}；网络：{rule(policy, 'network')}；高风险：{rule(policy, 'high_risk')}。"]
    if workspace:
        lines.append(f"Workspace: {workspace}")
    return lines + [""]
