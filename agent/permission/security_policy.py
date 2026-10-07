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
    "approval": {"managed": "allow", "workspace_read": "allow", "workspace_write": "confirm",
                 "workspace_outside": "confirm", "shell": "confirm", "git": "confirm", "network": "allow",
                 "install": "confirm", "background": "confirm", "external": "allow", "high_risk": "confirm"},
    "project-full": {"managed": "allow", "workspace_read": "allow", "workspace_write": "allow",
                     "workspace_outside": "confirm", "shell": "allow", "git": "allow", "network": "allow",
                     "install": "allow", "background": "allow", "external": "allow", "high_risk": "confirm"},
    "full-access": {"managed": "allow", "workspace_read": "allow", "workspace_write": "allow",
                    "workspace_outside": "allow", "shell": "allow", "git": "allow", "network": "allow",
                    "install": "allow", "background": "allow", "external": "allow", "high_risk": "confirm"},
}
PRESETS["custom"] = dict(PRESETS["project-full"])
MODE_DEFINITIONS = [
    {"id": "approval", "name": {"zh": "审批模式", "en": "Approval mode"},
     "description": {"zh": "日常读取直接执行，修改和命令逐次确认。",
                     "en": "Read normally; confirm changes and commands one at a time."}},
    {"id": "project-full", "name": {"zh": "项目内完全访问", "en": "Full project access"},
     "description": {"zh": "在当前工作区自主开发，重要外部操作需确认。",
                     "en": "Work freely in this workspace; confirm important external actions."}},
    {"id": "full-access", "name": {"zh": "完全访问", "en": "Full access"},
     "description": {"zh": "扩大到项目外目录，重要外部操作仍需确认。",
                     "en": "Access outside this project; important external actions still need approval."}},
    {"id": "custom", "name": {"zh": "自定义", "en": "Custom"},
     "description": {"zh": "从当前规则复制并按需调整，保存后生效。",
                     "en": "Copy the current rules, adjust them, and apply on save."}},
]
for _mode in MODE_DEFINITIONS:
    _mode["rules"] = dict(PRESETS[_mode["id"]])

LEGACY_PRESETS = {
    "strict": {**PRESETS["approval"], "workspace_write": "deny", "workspace_outside": "deny",
               "shell": "deny", "git": "deny", "network": "confirm", "install": "deny",
               "background": "deny", "external": "confirm"},
    "standard": {**PRESETS["project-full"], "workspace_outside": "deny",
                 "install": "confirm", "background": "confirm"},
    "custom": {**PRESETS["full-access"]},
}


def default_policy() -> dict:
    return {"preset": "project-full", "rules": {}, "connections": {}}


def legacy_policy(mode: str) -> dict:
    preset = {READ_ONLY: "strict", WORKSPACE_WRITE: "standard", FULL_ACCESS: "custom"}.get(mode, "strict")
    return {"preset": "custom", "base_preset": "project-full",
            "rules": dict(LEGACY_PRESETS[preset]), "connections": {}}


def _migrate_legacy(value: dict) -> dict:
    """Old preset names become exact snapshots, so upgrades never widen access."""
    if value.get("preset") not in LEGACY_PRESETS:
        return value
    snapshot = dict(LEGACY_PRESETS[value["preset"]])
    snapshot.update(value.get("rules") or {})
    return {**value, "preset": "custom", "base_preset": "project-full", "rules": snapshot}


def validate_patch(value: Any, *, global_policy: bool = False) -> dict:
    if not isinstance(value, dict):
        raise ValueError("security policy must be an object")
    value = _migrate_legacy(value)
    unknown = set(value) - {"preset", "base_preset", "rules", "connections", "extra_roots"}
    if unknown:
        raise ValueError(f"unknown security policy fields: {', '.join(sorted(unknown))}")
    result = {}
    if "preset" in value:
        if value["preset"] not in PRESETS:
            raise ValueError("unknown security preset")
        result["preset"] = value["preset"]
    if "base_preset" in value:
        if value["base_preset"] not in PRESETS or value["base_preset"] == "custom":
            raise ValueError("unknown custom base preset")
        result["base_preset"] = value["base_preset"]
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
    if "base_preset" in patch:
        result["base_preset"] = patch["base_preset"]
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
    base = default_policy()
    if isinstance(global_value, dict):
        try:
            base = merge(base, validate_patch(global_value, global_policy=True))
        except ValueError:
            return {"preset": "custom", "rules": {name: "deny" for name in RULES},
                    "connections": {}, "error": "Global security policy is invalid."}
    if project_dir:
        from agent.workspace import project_store
        try:
            base = merge(base, validate_patch(project_store.get_security_policy(project_dir)))
        except ValueError:
            return {"preset": "custom", "rules": {name: "deny" for name in RULES},
                    "connections": {}, "error": "Project security policy is invalid."}
    if session_id:
        from agent.workspace import session_prefs
        try:
            pref = session_prefs.get_prefs(session_id, agent_id)
        except ValueError:
            return {"preset": "custom", "rules": {name: "deny" for name in RULES},
                    "connections": {}, "error": "Conversation security preferences are invalid."}
        if pref.get("security_policy"):
            try:
                base = merge(base, validate_patch(pref["security_policy"]))
            except ValueError:
                return {"preset": "custom", "rules": {name: "deny" for name in RULES},
                        "connections": {}, "error": "Conversation security policy is invalid."}
    return base


def rule(policy: dict, name: str) -> str:
    preset = policy.get("preset", "project-full")
    if preset == "custom":
        preset = policy.get("base_preset", "project-full")
    return policy.get("rules", {}).get(name, PRESETS.get(preset, PRESETS["approval"])[name])


def effective_rules(policy: dict) -> dict:
    return {name: rule(policy, name) for name in RULES}


def effective_mode(policy: dict) -> str:
    preset = policy.get("preset", "project-full")
    if preset not in PRESETS or preset == "custom":
        return "custom"
    return "custom" if effective_rules(policy) != PRESETS[preset] else preset


def copy_custom(policy: dict) -> dict:
    base = policy.get("preset", "project-full")
    if base == "custom":
        base = policy.get("base_preset", "project-full")
    return {"preset": "custom", "base_preset": base,
            "rules": effective_rules(policy),
            "connections": deepcopy(policy.get("connections") or {}),
            **({"extra_roots": list(policy["extra_roots"])} if "extra_roots" in policy else {})}


def intersect(current: dict, ceiling: dict) -> dict:
    """A child run can only keep or reduce each parent permission."""
    order = {"deny": 0, "confirm": 1, "allow": 2}
    rules = {name: min((rule(current, name), rule(ceiling, name)), key=order.get) for name in RULES}
    connections = deepcopy(current.get("connections") or {})
    for name, parent in (ceiling.get("connections") or {}).items():
        child = connections.get(name, {})
        scopes = child.get("scopes") or []
        parent_scopes = parent.get("scopes") or []
        if parent_scopes and "*" not in parent_scopes:
            scopes = parent_scopes if not scopes or "*" in scopes else [scope for scope in scopes if scope in parent_scopes]
        connections[name] = {"allowed": parent.get("allowed", True) and child.get("allowed", True),
                             "scopes": scopes}
    return {"preset": "custom", "base_preset": "project-full", "rules": rules,
            "connections": connections}


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
        lines.append(
            "The built-in eLearning tool reads its saved login session internally, even when workspace_outside=deny. "
            "A refusal to read the raw session file does not block this connector. Never request workspace_outside "
            "access to inspect cookies; it cannot grant credential access. If the connector reports login timeout "
            "or HTTP 401, report an authentication/network problem and direct the user to eLearning settings."
            if english else
            "内置 elearning 工具会在内部读取已保存的登录状态，不受 workspace_outside=deny 对原始文件读取的限制。"
            "会话文件读取被拒绝不代表连接器被拒绝；不要建议开放 workspace_outside 来查看 Cookie，"
            "该权限也不能开放凭据。若连接器报告登录超时或 HTTP 401，应说明是登录或网络问题，"
            "引导用户到 eLearning 设置重新登录。"
        )
        lines.append(
            "For a live, complete Canvas file inventory use elearning list_files with pagination and "
            "file_extensions; use elearning sync_files with the same filter and layout=courseware when the "
            "user wants original names under each course's 课件 folder. Do not read cookies, "
            "call Canvas through scripts, or export tool results into intermediate files."
            if english else
            "获取 Canvas 实时完整文件清单时使用 elearning list_files 分页及 file_extensions 筛选；"
            "下载使用 elearning sync_files 并传相同筛选；需要按课程中文名/课件/原名保存时传 layout=courseware。"
            "不要读取 Cookie、用脚本直连 Canvas，"
            "也不要为对比而把工具结果另存中间文件。"
        )
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
