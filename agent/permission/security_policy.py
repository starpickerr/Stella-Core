"""Persisted security policy and scoped inheritance for tool execution."""

from __future__ import annotations

from copy import deepcopy
import json
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


def describe(policy: dict, language: str = "zh", workspace: str | None = None,
             *, tool_allowlist: list[str] | None = None,
             elearning_sync: dict | None = None) -> list[str]:
    """Explain the effective policy to the model; the gateway remains authoritative."""
    english = language == "en"
    lines = ["## Security context" if english else "## 本次会话的安全边界", ""]
    lines.append(("Effective preset: " if english else "有效预设：") +
                 str(policy.get("preset", "standard")) + ".")
    groups = (
        (("Managed state", "托管状态"), ("managed",)),
        (("Workspace read/write/outside", "工作区读取/写入/区外访问"),
         ("workspace_read", "workspace_write", "workspace_outside")),
        (("Shell/Git/network/install/background", "终端/Git/网络/安装/后台运行"),
         ("shell", "git", "network", "install", "background")),
        (("External/high-risk", "外部连接/高风险操作"), ("external", "high_risk")),
    )
    for labels, names in groups:
        lines.append(f"{labels[0 if english else 1]}: " +
                     ", ".join(f"{name}={rule(policy, name)}" for name in names) + ".")
    if workspace:
        lines.append(("Active workspace: " if english else "当前工作区：") +
                     json.dumps(workspace, ensure_ascii=False) + ".")
    extra_roots = policy.get("extra_roots") or []
    if extra_roots:
        lines.append(("Additional authorized paths: " if english else "额外授权路径：") +
                     json.dumps(extra_roots, ensure_ascii=False) + ".")
    if tool_allowlist:
        lines.append(("Available tool allowlist: " if english else "工具白名单：") +
                     json.dumps(tool_allowlist, ensure_ascii=False) + ".")
    for name, grant in sorted((policy.get("connections") or {}).items()):
        if grant.get("allowed") is False or grant.get("scopes"):
            status = "denied" if grant.get("allowed") is False else "allowed"
            scopes = grant.get("scopes") or []
            lines.append(("Connection restriction: " if english else "连接限制：") +
                         json.dumps(name, ensure_ascii=False) + f"={status}, scopes=" +
                         json.dumps(scopes, ensure_ascii=False) + ".")
    if elearning_sync is not None:
        enabled = bool(elearning_sync.get("enabled"))
        if enabled:
            root = json.dumps(elearning_sync.get("root", ""), ensure_ascii=False)
            lines.append(("eLearning file sync may write only to the selected folder: " if english else
                          "eLearning 文件同步仅可写入已选目录：") + root + ".")
        else:
            lines.append("eLearning file sync is not ready; the user must configure the account, "
                         "authorize courses and a save folder, and enable file sync in eLearning settings."
                         if english else "eLearning 文件同步未就绪；需要用户在 eLearning 设置中配置账号、授权课程和保存目录，并开启文件同步。")
    lines.extend([
        ("Read actions generally use workspace_read; changing tasks, calendar entries or briefings and "
         "eLearning sync_files use workspace_write. Shell also follows shell plus operation-specific rules."
         if english else "读取操作通常使用 workspace_read；修改事务、日程、简报及 eLearning sync_files 使用 "
                         "workspace_write。终端还要符合 shell 及具体操作规则。"),
        ("allow permits, confirm requires explicit Security Center approval for the exact action, deny forbids it. "
         "Protected credentials and privilege escalation remain unavailable even when a rule says allow."
         if english else "allow 表示可尝试，confirm 表示该次具体操作须经安全中心确认，deny 表示禁止。"
                         "即使规则为 allow，受保护凭据读取和提权仍被禁止。"),
        ("Use built-in tools for credentials and authorized file sync. Never use a script, rename, move, "
         "or equivalent tool to work around a refusal. If denied, explain the required setting or scope. "
         "If confirmation is required, the current call pauses and resumes after approval; do not retry it. "
         "Tool checks use the latest policy."
         if english else "凭据和文件同步使用内置工具；不要用脚本或换工具绕过拒绝，包括借重命名、移动绕过确认。被拒绝时说明需要的设置或授权范围。"
                         "需要确认时当前调用会暂停，批准后继续，不要重新发起。工具执行以当时的最新策略为准。"),
        "",
    ])
    return lines
