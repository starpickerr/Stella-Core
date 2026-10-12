"""Persisted security policy and scoped inheritance for tool execution."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from typing import Any

from agent.permission.policy import FULL_ACCESS, READ_ONLY, WORKSPACE_WRITE

RULES = (
    "managed", "workspace_read", "workspace_write", "workspace_outside",
    "shell", "git", "network", "install", "background", "external", "high_risk",
)
VALUES = {"allow", "confirm", "deny"}
_READ_ONLY = {
    "managed": "allow", "workspace_read": "allow", "workspace_write": "deny",
    "workspace_outside": "deny", "shell": "deny", "git": "deny", "network": "confirm",
    "install": "deny", "background": "deny", "external": "confirm", "high_risk": "confirm",
}
_WORKSPACE_WRITE = {
    "managed": "allow", "workspace_read": "allow", "workspace_write": "allow",
    "workspace_outside": "confirm", "shell": "allow", "git": "allow", "network": "allow",
    "install": "allow", "background": "allow", "external": "allow", "high_risk": "confirm",
}
_FULL_ACCESS = {
    "managed": "allow", "workspace_read": "allow", "workspace_write": "allow",
    "workspace_outside": "allow", "shell": "allow", "git": "allow", "network": "allow",
    "install": "allow", "background": "allow", "external": "allow", "high_risk": "allow",
}
_APPROVAL = {
    "managed": "allow", "workspace_read": "allow", "workspace_write": "confirm",
    "workspace_outside": "confirm", "shell": "confirm", "git": "confirm", "network": "allow",
    "install": "confirm", "background": "confirm", "external": "allow", "high_risk": "confirm",
}
PRESETS = {
    "read-only": dict(_READ_ONLY),
    "workspace-write": dict(_WORKSPACE_WRITE),
    "full-access": dict(_FULL_ACCESS),
}
PRESETS["custom"] = dict(PRESETS["workspace-write"])
MODE_DEFINITIONS = [
    {"id": "read-only", "name": {"zh": "只读", "en": "Read Only"},
     "description": {"zh": "在授权范围内读取；未授权的写入会被拒绝。",
                     "en": "Read authorized files; unauthorized writes are denied."}},
    {"id": "workspace-write", "name": {"zh": "工作区写入", "en": "Workspace Write"},
     "description": {"zh": "当前工作区内可自主修改，工作区外操作需要授权。",
                     "en": "Change files in this workspace; authorize anything outside it."}},
    {"id": "full-access", "name": {"zh": "完全访问", "en": "Full Access"},
     "description": {"zh": "放宽一般文件与命令限制；其他会话私有目录、托管数据和系统授权仍不可越过。",
                     "en": "Relax ordinary file and shell limits; other chats' private files, managed data and OS grants stay blocked."}},
    {"id": "custom", "name": {"zh": "自定义", "en": "Custom"},
     "description": {"zh": "从当前规则复制并按需调整，保存后生效。",
                     "en": "Copy the current rules, adjust them, and apply on save."}},
]
for _mode in MODE_DEFINITIONS:
    _mode["rules"] = dict(PRESETS[_mode["id"]])

LEGACY_PRESETS = {
    "approval": dict(_APPROVAL),
    "strict": {**_APPROVAL, "workspace_write": "deny", "workspace_outside": "deny",
               "shell": "deny", "git": "deny", "network": "confirm", "install": "deny",
               "background": "deny", "external": "confirm"},
    "standard": {**_WORKSPACE_WRITE, "workspace_outside": "deny",
                 "install": "confirm", "background": "confirm"},
    "custom": dict(_FULL_ACCESS),
}
_PRODUCT_ALIASES = {"project-full": "workspace-write"}
_DEFAULT_BASE = "workspace-write"


def _is_private_work_path(path: str) -> bool:
    from common.state_dir import personal_work_dir
    work = os.path.realpath(personal_work_dir(ensure=False))
    real = os.path.realpath(os.path.expanduser(path))
    try:
        inside = os.path.commonpath((real, work)) == work
    except ValueError:
        return False
    if not inside:
        return False
    relative = os.path.relpath(real, work)
    first = relative.split(os.sep, 1)[0]
    return first in {"sessions", "automations", "shared"}


def default_policy() -> dict:
    return {"preset": "workspace-write", "rules": {}, "connections": {}}


def legacy_policy(mode: str) -> dict:
    preset = {READ_ONLY: "strict", WORKSPACE_WRITE: "standard", FULL_ACCESS: "custom"}.get(mode, "strict")
    return {"preset": "custom", "base_preset": _DEFAULT_BASE,
            "rules": dict(LEGACY_PRESETS[preset]), "connections": {}}


def _migrate_legacy(value: dict) -> dict:
    """Old preset names become exact snapshots or product aliases, never wider access."""
    preset = value.get("preset")
    base = _PRODUCT_ALIASES.get(value.get("base_preset"), value.get("base_preset"))
    if base == "approval":
        snapshot = dict(_APPROVAL)
        snapshot.update(value.get("rules") or {})
        return {**value, "preset": "custom", "base_preset": _DEFAULT_BASE, "rules": snapshot}
    if preset == "project-full":
        return {**value, "preset": "workspace-write",
                **({"base_preset": base} if "base_preset" in value else {})}
    if preset == "custom" and (value.get("base_preset") or value.get("rules")):
        rewritten = {**value, "base_preset": base or _DEFAULT_BASE}
        return rewritten
    if preset not in LEGACY_PRESETS:
        return {**value, **({"base_preset": base} if "base_preset" in value else {})}
    snapshot = dict(LEGACY_PRESETS[preset])
    snapshot.update(value.get("rules") or {})
    return {**value, "preset": "custom", "base_preset": _DEFAULT_BASE, "rules": snapshot}


def snapshot_policy(policy: dict) -> dict:
    """Materialize a complete storeable policy that no longer depends on a parent layer."""
    mode = effective_mode(policy)
    connections = deepcopy(policy.get("connections") or {})
    if mode == "custom":
        base = policy.get("base_preset", _DEFAULT_BASE)
        if base not in PRESETS or base == "custom":
            base = _DEFAULT_BASE
        result = {"preset": "custom", "base_preset": base,
                  "rules": effective_rules(policy), "connections": connections}
    else:
        result = {"preset": mode, "rules": {}, "connections": connections}
    if "extra_roots" in policy:
        result["extra_roots"] = list(policy["extra_roots"])
    return result


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
        if global_policy and value["preset"] == "custom":
            raise ValueError("global security policy cannot use the custom preset")
        result["preset"] = value["preset"]
    if "base_preset" in value:
        if global_policy:
            raise ValueError("global security policy cannot store a custom base preset")
        if value["base_preset"] not in PRESETS or value["base_preset"] == "custom":
            raise ValueError("unknown custom base preset")
        result["base_preset"] = value["base_preset"]
    if "rules" in value:
        rules = value["rules"]
        if not isinstance(rules, dict) or any(k not in RULES or v not in VALUES for k, v in rules.items()):
            raise ValueError("invalid security rule")
        if global_policy and rules:
            raise ValueError("global security policy cannot store custom rules")
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
        if any(_is_private_work_path(path) for path in roots):
            raise ValueError("extra roots cannot name private Work paths")
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


def _load_global(mode: str, global_value: dict | None) -> dict:
    if global_value is None:
        from config import conf
        global_value = conf().get("security_policy")
    if not isinstance(global_value, dict):
        return legacy_policy(mode)
    try:
        # Existing installs may still store a custom global snapshot; read it, but
        # validate_patch(..., global_policy=True) rejects new custom defaults.
        if global_value.get("preset") == "custom" or global_value.get("preset") in LEGACY_PRESETS:
            return merge(default_policy(), validate_patch(global_value, global_policy=False))
        return merge(default_policy(), validate_patch(global_value, global_policy=True))
    except ValueError:
        return {"preset": "custom", "rules": {name: "deny" for name in RULES},
                "connections": {}, "error": "Global security policy is invalid."}


def resolve(mode: str, *, project_dir: str | None = None, session_id: str | None = None,
            agent_id: str | None = None, global_value: dict | None = None) -> dict:
    """Complete project or standalone-conversation policies win; global is only the default seed."""
    global_base = _load_global(mode, global_value)
    if project_dir:
        from agent.workspace import project_store
        try:
            stored = project_store.get_security_policy(project_dir)
        except ValueError:
            return {"preset": "custom", "rules": {name: "deny" for name in RULES},
                    "connections": {}, "error": "Project security policy is invalid."}
        if stored:
            try:
                patch = validate_patch(stored)
            except ValueError:
                return {"preset": "custom", "rules": {name: "deny" for name in RULES},
                        "connections": {}, "error": "Project security policy is invalid."}
            # Only a complete project snapshot replaces the global seed. Paths-only
            # records keep inheriting the current global default.
            if any(key in patch for key in ("preset", "base_preset", "rules", "connections")):
                base = merge(default_policy(), patch)
            else:
                base = deepcopy(global_base)
                if "extra_roots" in patch:
                    base["extra_roots"] = list(patch["extra_roots"])
        else:
            base = deepcopy(global_base)
        if session_id:
            from agent.workspace import session_prefs
            try:
                pref = session_prefs.get_prefs(session_id, agent_id)
            except ValueError:
                return {"preset": "custom", "rules": {name: "deny" for name in RULES},
                        "connections": {}, "error": "Conversation security preferences are invalid."}
            roots = (pref.get("security_policy") or {}).get("extra_roots")
            if roots is not None:
                try:
                    validated = validate_patch({"extra_roots": roots})
                except ValueError:
                    return {"preset": "custom", "rules": {name: "deny" for name in RULES},
                            "connections": {}, "error": "Conversation security policy is invalid."}
                base["extra_roots"] = list(validated["extra_roots"])
        return base
    if session_id:
        from agent.workspace import session_prefs
        try:
            pref = session_prefs.get_prefs(session_id, agent_id)
        except ValueError:
            return {"preset": "custom", "rules": {name: "deny" for name in RULES},
                    "connections": {}, "error": "Conversation security preferences are invalid."}
        stored = pref.get("security_policy")
        if stored:
            try:
                return merge(default_policy(), validate_patch(stored))
            except ValueError:
                return {"preset": "custom", "rules": {name: "deny" for name in RULES},
                        "connections": {}, "error": "Conversation security policy is invalid."}
    return global_base


def migrate_project_conversation_policies(project_dir: str, *, global_value: dict | None = None,
                                          mode: str = WORKSPACE_WRITE) -> dict:
    """Unify project-internal conversation overrides into one complete project policy."""
    from agent.workspace import project_store, session_prefs

    stored = project_store.get_security_policy(project_dir)
    if stored:
        try:
            current = merge(default_policy(), validate_patch(stored))
        except ValueError as error:
            raise ValueError("Project security policy is invalid.") from error
    else:
        current = _load_global(mode, global_value)
        # Preserve pre-migration conversation overlays when the project had no snapshot yet.
        for session_id in project_store.list_project_session_ids(project_dir):
            pref = session_prefs.get_prefs(session_id)
            patch = pref.get("security_policy") or {}
            rule_patch = {key: value for key, value in patch.items() if key != "extra_roots"}
            if rule_patch:
                current = merge(current, validate_patch(rule_patch))
    snapshot = snapshot_policy(current)
    project_store.set_security_policy(project_dir, snapshot)
    for session_id in project_store.list_project_session_ids(project_dir):
        pref = session_prefs.get_prefs(session_id)
        patch = dict(pref.get("security_policy") or {})
        roots = patch.get("extra_roots")
        if patch:
            session_prefs.set_prefs(session_id, security_policy=(
                {"extra_roots": roots} if roots is not None else None
            ))
    return snapshot


def rule(policy: dict, name: str) -> str:
    preset = _PRODUCT_ALIASES.get(policy.get("preset", _DEFAULT_BASE), policy.get("preset", _DEFAULT_BASE))
    if preset == "custom":
        base = policy.get("base_preset", _DEFAULT_BASE)
        preset = _PRODUCT_ALIASES.get(base, base)
    return policy.get("rules", {}).get(name, PRESETS.get(preset, PRESETS["read-only"])[name])


def effective_rules(policy: dict) -> dict:
    return {name: rule(policy, name) for name in RULES}


def effective_mode(policy: dict) -> str:
    preset = policy.get("preset", _DEFAULT_BASE)
    if preset not in PRESETS or preset == "custom":
        return "custom"
    return "custom" if effective_rules(policy) != PRESETS[preset] else preset


def copy_custom(policy: dict) -> dict:
    base = policy.get("preset", _DEFAULT_BASE)
    if base == "custom":
        base = policy.get("base_preset", _DEFAULT_BASE)
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
    return {"preset": "custom", "base_preset": _DEFAULT_BASE, "rules": rules,
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
            lines.append("eLearning file sync is not ready; the user must connect the account and select courses "
                         "in briefing sources, then authorize a save folder in Agent settings."
                         if english else "eLearning 文件同步未就绪；需要先在简报来源中连接账号并选择课程，再在 Agent 设置中授权保存目录。")
    lines.extend([
        ("Create or update custom skills with the skill tool. Full access permits this managed operation; "
         "project access may require confirmation for the system skill store."
         if english else "创建或更新自定义技能请使用 skill 工具；完全访问可直接执行，项目内访问可能需确认系统技能库的授权。"),
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
