"""Single policy gate for interactive, scheduled and direct tool calls."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from agent.permission.policy import MODES
from agent.permission.shell_scope import _parse_segments, _command_name, _redirect_targets, _positional_paths, _DESTINATION_ONLY_COMMANDS, _PATH_MUTATING_COMMANDS
from agent.permission.security_policy import legacy_policy, rule


class Capability(str, Enum):
    READ = "read"
    WORKSPACE_WRITE = "workspace-write"
    EXTERNAL = "external"
    ADMIN = "admin"


class ResourceKind(str, Enum):
    AGENT_MANAGED = "agent-managed"
    USER_WORKSPACE = "user-workspace"
    EXTERNAL = "external"
    SYSTEM = "system"
    CREDENTIAL = "credential"


class DecisionKind(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True)
class Scope:
    write_roots: tuple[str, ...] = ()
    accounts: tuple[str, ...] = ()
    extra_roots: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyDecision:
    kind: DecisionKind
    reason: str
    resource_kind: ResourceKind
    operation: str
    risk: str
    resource: str
    trace: tuple[str, ...]
    request_id: str | None = None

    @property
    def allowed(self) -> bool:
        return self.kind is DecisionKind.ALLOW

    def __bool__(self) -> bool:
        return self.allowed


_READ_TOOLS = frozenset({"read", "ls", "search_files", "memory_search", "memory_get", "web_search", "web_fetch", "vision", "elearning"})
_WRITE_TOOLS = frozenset({"write", "edit", "bash"})
_EXTERNAL_TOOLS = frozenset({"browser", "scheduler", "env_config", "briefing", "calendar", "todos", "bills", "apple", "send", "subagent"})
_ADMIN_TOOLS = frozenset({"evolution_undo", "skill"})
_LOCAL_ACTIONS = {
    "calendar": {"create", "update", "delete", "create_category", "update_category", "delete_category"},
    "todos": {"create", "update", "complete", "delete", "status", "add_subtask", "move", "add_dependency", "remove_dependency"},
    "bills": {"add", "update", "delete"},
    "briefing": {"run", "item_status", "add_rule", "update_rule", "delete_rule", "decide", "authorize", "revoke_authorization", "set_preferences"},
    "scheduler": {"create", "delete", "enable", "disable"},
}
_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
_SECRET_COMMAND = re.compile(r"(?:\.stella/(?:\.env|config\.json|mcp\.json|weixin_credentials\.json)|/briefing/(?:elearning\.json|elearning-sessions/[^\s'\"]+)|/proc/(?:self|\d+)/environ|\b(?:printenv|env|set)\b|\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD)\w*\}?|\b(?:curl|wget)\b[^\n]*\b(?:key|token|secret|password)=)", re.I)
_ESCALATE = re.compile(r"\b(?:sudo|doas|pkexec|su)\b")
_BULK_DELETE = re.compile(r"\b(?:rm\s+-(?:\w*r\w*f|\w*f\w*r)|find\b[^\n]*-delete|git\s+clean\s+-\w*f)\b", re.I)
_PUBLISH = re.compile(r"\b(?:git\s+push|npm\s+publish|gh\s+release|docker\s+push)\b", re.I)
_INSTALL = re.compile(r"\b(?:npm|pnpm|yarn|pip|pip3|brew|apt|apt-get)\s+(?:install|add|upgrade)\b", re.I)
_NETWORK = re.compile(r"\b(?:curl|wget|ssh|scp|git\s+(?:clone|fetch|pull))\b", re.I)
_EXTERNAL_VERB = re.compile(r"(?:^|[_\-.])(create|add|update|edit|delete|remove|send|publish|deploy|revoke|install)(?:$|[_\-.])", re.I)
_lock = threading.RLock()
_condition = threading.Condition(_lock)
_pending: dict[str, dict] = {}
_approved: dict[str, float] = {}
_outcomes: dict[str, tuple[str, float]] = {}
_claims: dict[str, tuple[str, float]] = {}
_claim_assigned: set[str] = set()
_registered: dict[str, Capability] = {}
_connections: dict[str, str] = {}
_mcp_readonly: dict[str, bool] = {}


def register_tool(tool_name: str, capability: Capability, *, connection: str | None = None,
                  read_only: bool = False) -> None:
    if not _SAFE_NAME.fullmatch(tool_name) or not isinstance(capability, Capability):
        raise ValueError("invalid tool declaration")
    with _lock:
        _registered[tool_name] = capability
        if connection:
            _connections[tool_name] = connection
            if connection.startswith("mcp:"):
                _mcp_readonly[tool_name] = read_only


def declared_capability(tool_name: str) -> Optional[Capability]:
    if tool_name in _READ_TOOLS:
        return Capability.READ
    if tool_name in _WRITE_TOOLS:
        return Capability.WORKSPACE_WRITE
    if tool_name in _EXTERNAL_TOOLS:
        return Capability.EXTERNAL
    if tool_name in _ADMIN_TOOLS:
        return Capability.ADMIN
    return _registered.get(tool_name)


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _path(path: str, cwd: str | None) -> str:
    return os.path.realpath(os.path.join(cwd or os.getcwd(), os.path.expanduser(path)))


def _shell_write_targets(command: str, cwd: str | None) -> list[str] | None:
    """Extract explicit targets; the process sandbox covers dynamic effects."""
    segments = _parse_segments(command)
    if segments is None:
        return None
    output = []
    for tokens in segments:
        targets = [p for p in _redirect_targets(tokens) if p not in ("/dev/null", "/dev/stdout", "/dev/stderr", "nul")]
        name, rest = _command_name(tokens)
        if name in _PATH_MUTATING_COMMANDS:
            paths = _positional_paths(rest)
            if name == "dd":
                paths = [item.split("=", 1)[1] for item in rest if item.startswith("of=")]
            elif name in _DESTINATION_ONLY_COMMANDS:
                paths = paths[-1:] if len(paths) > 1 else []
            elif name == "sed" and not any(item.startswith("-i") for item in rest):
                paths = []
            targets.extend(paths)
        for target in targets:
            if target and target not in ("/dev/null", "nul"):
                output.append(_path(target, cwd))
    return output


def _shell_boundary(command: str, roots: tuple[str, ...], cwd: str | None) -> str | None:
    targets = _shell_write_targets(command, cwd)
    if targets is None:
        return "Shell command could not be parsed for workspace boundaries."
    return next((target for target in targets if not any(
        _inside(target, _path(root, cwd)) for root in roots)), None)


def _skill_store(path: str) -> bool:
    from common.state_dir import skills_dir, shared_root, state_root
    roots = [skills_dir(), shared_root() / "skills", state_root() / "skills"]
    return any(_inside(path, os.path.realpath(root)) for root in roots)


def _managed(path: str) -> bool:
    from common.state_dir import state_root
    if _skill_store(path):
        return True
    root = state_root()
    # Exact persona/config files and named internal stores. The root as a whole
    # remains a user workspace on single-Agent installations.
    if path in {os.path.realpath(root / name) for name in ("AGENT.md", "RULE.md", "BOOTSTRAP.md")}:
        return True
    return any(_inside(path, os.path.realpath(root / name)) for name in ("cache", "index", "internal", "registry"))


def _trusted_skill_init(command: str, cwd: str | None) -> bool:
    """The bundled Skill template generator writes only into the Skill Store."""
    try:
        tokens = shlex.split(command)
        if len(tokens) < 5 or os.path.basename(tokens[0]) not in ("python", "python3"):
            return False
        script = _path(tokens[1], cwd)
        bundled = os.path.realpath(Path(__file__).parents[2] / "skills" / "skill-creator" / "scripts" / "init_skill.py")
        if script != bundled or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", tokens[2]):
            return False
        if tokens[3] != "--path" or not _skill_store(_path(tokens[4], cwd)):
            return False
        return len(tokens) == 5 or (len(tokens) >= 7 and tokens[5] == "--resources"
                 and re.fullmatch(r"[a-z,]+", tokens[6]) is not None and
                 (len(tokens) == 7 or tokens[7:] == ["--examples"]))
    except (ValueError, IndexError):
        return False


def _fingerprint(tool_name: str, arguments: Mapping[str, Any], session_id: Optional[str], project: str | None,
                 agent_id: str | None, cwd: str | None, scope: Scope) -> str:
    from common.runtime_identity import current_identity
    identity = current_identity()
    payload = json.dumps([identity.user_id, agent_id, session_id, identity.run_id, project,
                          cwd, scope.write_roots, scope.extra_roots, tool_name, arguments],
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _summary(tool_name: str, arguments: Mapping[str, Any]) -> str:
    from common.log import _redact
    if tool_name == "bash":
        detail = str(arguments.get("command") or "")
    elif tool_name == "browser":
        detail = str(arguments.get("script") or arguments.get("expression") or arguments.get("action") or "")
    elif tool_name == "send":
        detail = str(arguments.get("path") or "")
    else:
        detail = str(arguments.get("action") or "execute")
    return _redact(detail).replace("\n", " ")[:240]


class SecurityGateway:
    @staticmethod
    def check(
        mode: str, tool_name: str, arguments: Mapping[str, Any], *, cwd: Optional[str] = None,
        scope: Optional[Scope] = None, session_id: Optional[str] = None,
        allowlist: Optional[Sequence[str]] = None, capability: Optional[Capability] = None,
        policy: Optional[dict] = None, agent_id: str | None = None, project_dir: str | None = None,
        approval_request_id: str | None = None,
        reserve_for_waiter: bool = False,
        create_pending: bool = True,
    ) -> PolicyDecision:
        declared = declared_capability(tool_name)
        scope = scope or Scope()
        policy = policy or legacy_policy(mode)
        args = arguments if isinstance(arguments, Mapping) else {}
        action = str(args.get("action") or "").lower()
        operation = action or ("write" if tool_name in ("write", "edit") else "read" if declared == Capability.READ else "execute")
        resource_kind = ResourceKind.EXTERNAL if declared == Capability.EXTERNAL else ResourceKind.SYSTEM if tool_name == "bash" else ResourceKind.USER_WORKSPACE
        resource = tool_name
        risk = "L0" if declared == Capability.READ else "L1"
        policy_key = "workspace_read" if declared == Capability.READ else "workspace_write"
        hard_reason = None
        prerequisites: list[str] = []
        path_arg = str(args.get("path") or "")
        event = "tool_decision"
        if tool_name in ("read", "write", "edit", "ls", "search_files", "send") and path_arg and not path_arg.lower().startswith(("http://", "https://")):
            real = _path(path_arg, cwd)
            from agent.tools.utils.credentials import credential_denial_message, is_credential_path
            if is_credential_path(real):
                resource_kind, resource, risk = ResourceKind.CREDENTIAL, "protected credential", "L4"
                hard_reason = credential_denial_message(real)
            elif _managed(real):
                resource_kind, policy_key = ResourceKind.AGENT_MANAGED, "managed"
                resource = "Agent Skill Store" if _skill_store(real) else "Agent Config/Internal State"
                risk = "L0" if declared == Capability.READ else "L1"
                if tool_name in ("write", "edit"):
                    event = ("skill_modify" if os.path.exists(real) else "skill_install") if _skill_store(real) else "agent_config_change"
                    hard_reason = ("Use the skill tool to create or update skills; generic file writes are blocked."
                                   if _skill_store(real) else
                                   "Long-term instructions require their dedicated settings flow.")
            else:
                resource = real
                roots = tuple(scope.write_roots) + tuple(scope.extra_roots) + tuple(policy.get("extra_roots") or ())
                if not any(_inside(real, _path(root, cwd)) for root in roots):
                    policy_key = "workspace_outside"
                risk = "L0" if declared == Capability.READ else "L1"
                if policy_key == "workspace_outside":
                    risk = "L2" if declared == Capability.READ else "L3"
                if tool_name in ("write", "edit"):
                    event = "file_modify"
                if tool_name == "send":
                    resource_kind, resource, risk, policy_key = ResourceKind.EXTERNAL, "send", "L3", "high_risk"
                    event = "external_access"
                    prerequisites.append("workspace_read")
                    if not any(_inside(real, _path(root, cwd)) for root in roots):
                        prerequisites.append("workspace_outside")
        elif tool_name == "bash":
            command = str(args.get("command") or "")
            resource, policy_key, risk = "shell", "shell", "L2"
            event = "shell_execution"
            segments = _parse_segments(command)
            git_command = bool(segments and len(segments) == 1 and _command_name(segments[0])[0] == "git")
            if _trusted_skill_init(command, cwd):
                resource_kind, resource, policy_key, risk = ResourceKind.AGENT_MANAGED, "Agent Skill Store", "managed", "L3"
                event = "skill_install"
                hard_reason = "Use the skill tool to create skills; shell writes to the skill store are blocked."
            elif _SECRET_COMMAND.search(command):
                resource_kind, resource, risk = ResourceKind.CREDENTIAL, "protected credential", "L4"
                from agent.tools.utils.credentials import ELEARNING_DENIED_MESSAGE
                hard_reason = (ELEARNING_DENIED_MESSAGE if re.search(
                    r"/briefing/(?:elearning\.json|elearning-sessions/)", command, re.I)
                    else "Shell access to credential data or environment variables is blocked.")
            elif _ESCALATE.search(command):
                risk, hard_reason = "L4", "Privilege escalation is blocked."
            elif _BULK_DELETE.search(command):
                # Destructive changes inside the selected workspace are part of
                # project access. The boundary check below still rejects or
                # confirms targets outside the authorized roots.
                risk, policy_key = "L2", "workspace_write"
                event = "file_modify"
            elif _PUBLISH.search(command):
                risk, policy_key = "L3", "high_risk"
                resource_kind = ResourceKind.EXTERNAL
                resource = "github" if re.search(r"\b(?:git\s+push|gh\s+release)\b", command) else "external_api"
            elif _INSTALL.search(command):
                risk, policy_key = "L2", "install"
            elif _NETWORK.search(command):
                risk, policy_key, resource = "L2", "network", "external_api"
                resource_kind = ResourceKind.EXTERNAL
            elif args.get("run_in_background"):
                risk, policy_key = "L2", "background"
            elif git_command:
                policy_key = "git"
            if resource_kind != ResourceKind.AGENT_MANAGED:
                if policy_key != "shell":
                    prerequisites.append("shell")
                if git_command and policy_key != "git":
                    prerequisites.append("git")
                if _NETWORK.search(command) and policy_key != "network":
                    prerequisites.append("network")
                if _INSTALL.search(command) and policy_key != "install":
                    prerequisites.append("install")
                if args.get("run_in_background") and policy_key != "background":
                    prerequisites.append("background")
                if _PUBLISH.search(command) and policy_key != "high_risk":
                    prerequisites.append("high_risk")
            if not hard_reason and resource_kind != ResourceKind.AGENT_MANAGED:
                outside = _shell_boundary(command, scope.write_roots + scope.extra_roots +
                                          tuple(policy.get("extra_roots") or ()), cwd)
                if outside:
                    if outside.startswith("Shell command could not"):
                        hard_reason = outside
                    else:
                        resource_kind, resource, risk = ResourceKind.USER_WORKSPACE, outside, "L3"
                        if policy_key != "workspace_outside":
                            prerequisites.append("workspace_outside")
        elif tool_name == "env_config":
            resource_kind, resource = ResourceKind.CREDENTIAL, "Credential Store"
            event = "secret_use"
            if action in ("set", "delete"):
                risk, policy_key = "L3", "high_risk"
            else:
                risk, policy_key = "L0", "managed"
        elif tool_name == "skill":
            resource_kind, resource, policy_key = ResourceKind.AGENT_MANAGED, "Agent Skill Store", "managed"
            event = "skill_install" if action == "create" else "skill_modify"
            if action in ("create", "update", "write_resource"):
                risk = "L2"
                prerequisites.extend(("workspace_write", "workspace_outside"))
            else:
                hard_reason = "Unknown skill action; the tool did not run."
        elif tool_name in _LOCAL_ACTIONS:
            resource_kind, resource = ResourceKind.USER_WORKSPACE, tool_name
            mutating = action in _LOCAL_ACTIONS[tool_name]
            risk, policy_key = ("L1", "workspace_write") if mutating else ("L0", "workspace_read")
        elif tool_name == "elearning" and action == "sync_files":
            # The tool itself restricts writes to the folder granted in eLearning settings.
            resource_kind, resource, risk, policy_key = (
                ResourceKind.USER_WORKSPACE, "eLearning selected course folder", "L1", "workspace_write")
            event = "file_modify"
        elif tool_name == "subagent":
            resource_kind, resource, risk, policy_key = ResourceKind.AGENT_MANAGED, "Agent subagent", "L1", "managed"
        elif tool_name == "browser":
            resource_kind, resource, risk, policy_key = ResourceKind.EXTERNAL, "browser", "L2", "external"
            event = "external_access"
            url = str(args.get("url") or "")
            if action == "navigate" and url.lower().startswith("file://"):
                from urllib.parse import urlparse, unquote
                from agent.tools.utils.credentials import is_credential_path, credential_denial_message
                parsed = urlparse(url)
                local = _path(unquote(parsed.path), cwd)
                resource_kind, resource, risk, policy_key = ResourceKind.USER_WORKSPACE, local, "L0", "workspace_read"
                if parsed.netloc not in ("", "localhost"):
                    hard_reason = "Remote file URLs are not allowed."
                elif is_credential_path(local):
                    hard_reason = credential_denial_message(local)
                elif not any(_inside(local, _path(root, cwd)) for root in (
                        *scope.write_roots, *scope.extra_roots, *(policy.get("extra_roots") or ()))):
                    policy_key, risk = "workspace_outside", "L2"
            elif action in ("click", "fill", "select", "press", "evaluate"):
                from agent.tools.browser.browser_tool import BrowserTool
                service = BrowserTool._shared_service
                resource = getattr(service, "_last_url", None) or "current browser page / signed-in profile"
                risk, policy_key = "L3", "high_risk"
                prerequisites.append("external")
            elif action == "navigate" and url.split(":", 1)[0].lower() in ("data", "javascript", "blob"):
                resource, risk, policy_key = "browser inline content", "L3", "high_risk"
                prerequisites.append("external")
            elif action in ("navigate", "back", "forward"):
                resource = url or "current browser page"
                prerequisites.append("network")
            elif action not in ("snapshot", "get_text", "screenshot", "scroll", "wait"):
                risk, policy_key = "L3", "high_risk"
                prerequisites.append("external")
        elif declared == Capability.EXTERNAL or declared == Capability.ADMIN:
            resource_kind, resource = ResourceKind.EXTERNAL, _connections.get(tool_name, tool_name)
            event = "external_access"
            risk, policy_key = "L2", "external"
            inferred = _EXTERNAL_VERB.search(tool_name)
            operation = action or (inferred.group(1).lower() if inferred else operation)
            if tool_name in ("send",) or operation in ("send", "publish", "delete", "remove", "revoke", "deploy", "evaluate") or declared == Capability.ADMIN:
                risk, policy_key = "L3", "high_risk"
            if _connections.get(tool_name, "").startswith("mcp:") and not _mcp_readonly.get(tool_name, False):
                risk, policy_key = "L3", "high_risk"
        elif tool_name in ("web_fetch", "web_search"):
            resource_kind, resource, risk, policy_key = ResourceKind.EXTERNAL, "external_api", "L2", "network"
            event = "external_access"

        if capability is not None and (not isinstance(capability, Capability) or capability != declared):
            hard_reason = "Unknown or mismatched capability; the tool did not run."
        elif declared is None or mode not in MODES:
            hard_reason = "Unknown tool capability or permission mode; the tool did not run."
        elif allowlist is not None and tool_name not in allowlist:
            hard_reason = "Tool is outside the current allowlist; it did not run."
        elif scope.accounts and resource_kind == ResourceKind.EXTERNAL and str(args.get("account_id") or args.get("account") or "") not in scope.accounts:
            hard_reason = "Account is outside the current scope; the tool did not run."
        connection = _connections.get(tool_name, resource if resource in ("github", "external_api") else tool_name if resource_kind == ResourceKind.EXTERNAL else "")
        grant = policy.get("connections", {}).get(connection, {})
        if not hard_reason and grant.get("allowed") is False:
            hard_reason = f"Connection {connection} was revoked."
        if not hard_reason and grant.get("scopes") and "*" not in grant["scopes"]:
            requested = str(args.get("scope") or (operation if operation not in ("execute", "read") else "read"))
            if requested not in grant["scopes"]:
                hard_reason = f"Connection {connection} does not grant scope {requested}."
        if resource_kind == ResourceKind.EXTERNAL and policy_key != "external":
            prerequisites.append("external")
        if risk == "L3" and policy_key != "high_risk":
            prerequisites.append("high_risk")
        selected = rule(policy, policy_key)
        required = {name: rule(policy, name) for name in prerequisites}
        trace = (f"Action: {operation}", f"Resource classification: {resource_kind.value} ({resource})",
                 f"Risk evaluation: {risk}", f"Policy: {policy_key}={selected}") + tuple(
                     f"Required policy: {name}={value}" for name, value in required.items())
        if hard_reason:
            kind, reason = DecisionKind.DENY, hard_reason
        elif selected == "deny":
            kind, reason = DecisionKind.DENY, f"Policy denied {operation} on {resource_kind.value} ({resource}); rule {policy_key}."
        elif "deny" in required.values():
            refused = next(name for name, value in required.items() if value == "deny")
            kind, reason = DecisionKind.DENY, f"Policy denied {operation} on {resource_kind.value} ({resource}); required rule {refused}."
        elif not create_pending and (selected == "confirm" or "confirm" in required.values()):
            kind, reason = DecisionKind.CONFIRM, "Authorization required. Adjust the policy and rerun this task manually; it will not resume automatically."
        elif selected == "confirm" or "confirm" in required.values():
            key = _fingerprint(tool_name, args, session_id, project_dir, agent_id, cwd, scope)
            with _lock:
                claim = _claims.get(approval_request_id) if approval_request_id else None
                if claim and claim[0] == key and claim[1] >= time.time():
                    del _claims[approval_request_id]
                    kind, reason = DecisionKind.ALLOW, "Approved once for this exact action."
                elif _approved.pop(key, 0) >= time.time():
                    kind, reason = DecisionKind.ALLOW, "Approved once for this exact action."
                else:
                    reserved_id = next((rid for rid, claim in _claims.items()
                                        if claim[0] == key and claim[1] >= time.time()), None)
                    if reserved_id is not None:
                        if reserve_for_waiter:
                            request_id = reserved_id
                            kind, reason = DecisionKind.CONFIRM, "An identical approved action is resuming."
                        else:
                            kind, reason = DecisionKind.DENY, "An identical approval is reserved for the waiting conversation."
                    else:
                        request_id = next((rid for rid, pending in _pending.items()
                                           if pending["key"] == key and pending["expires"] >= time.time()), None)
                        if request_id is None:
                            request_id = uuid.uuid4().hex
                            from common.log import _redact
                            from common.runtime_identity import current_identity
                            _pending[request_id] = {"key": key, "tool": tool_name, "session": session_id,
                                                    "summary": _summary(tool_name, args), "resource": _redact(resource),
                                                    "risk": risk, "reason": f"Policy requires confirmation for {operation}.",
                                                    "agent": agent_id, "project": project_dir, "operation": operation,
                                                    "user": current_identity().user_id,
                                                    "expanded_scope": _redact(resource) if "workspace_outside" in required else "",
                                                    "effect": "May change files or external state" if risk in ("L2", "L3", "L4") else "Read-only",
                                                    "interactive": reserve_for_waiter,
                                                    "expires": time.time() + 3600}
                        elif reserve_for_waiter:
                            _pending[request_id]["interactive"] = True
                        kind, reason = DecisionKind.CONFIRM, f"Confirmation required for {tool_name}. Request {request_id} is waiting in Security."
        else:
            kind, reason = DecisionKind.ALLOW, f"Policy allowed {operation} on {resource_kind.value}; rule {policy_key}."
        from common.log import _redact
        safe_trace = tuple(_redact(value) for value in trace + (f"Decision: {kind.value}",))
        result = PolicyDecision(kind, _redact(reason), resource_kind, operation, risk, resource,
                                safe_trace, locals().get("request_id"))
        try:
            from agent.permission.audit import record
            record(agent=agent_id, conversation=session_id, project=project_dir, tool=tool_name,
                   operation=operation, resource=_redact(resource), event=event, risk=risk, decision=kind.value,
                   reason=_redact(reason), trace=result.trace)
        except Exception:
            if result.request_id:
                with _lock:
                    _pending.pop(result.request_id, None)
            return PolicyDecision(DecisionKind.DENY, "Security audit is unavailable; the tool did not run.",
                                  resource_kind, operation, risk, resource,
                                  trace + ("Decision: deny (audit unavailable)",))
        return result

    @staticmethod
    def pending() -> list[dict]:
        now = time.time()
        with _lock:
            for request_id, request in list(_pending.items()):
                if request["expires"] < now:
                    del _pending[request_id]
            for key, expires in list(_approved.items()):
                if expires < now:
                    del _approved[key]
            for request_id, (_, expires) in list(_outcomes.items()):
                if expires < now:
                    del _outcomes[request_id]
                    _claim_assigned.discard(request_id)
            for request_id, (_, expires) in list(_claims.items()):
                if expires < now:
                    del _claims[request_id]
            return [{"id": request_id, **{k: request[k] for k in ("tool", "session", "summary", "resource", "risk", "reason", "expanded_scope", "effect")}}
                    for request_id, request in _pending.items()]

    @staticmethod
    def has_pending_session(session_id: str | None) -> bool:
        if not session_id:
            return False
        with _lock:
            now = time.time()
            return any(request["session"] == session_id and request["expires"] >= now
                       for request in _pending.values())

    @staticmethod
    def approve(request_id: str, *, session_id: str | None = None, user_id: str | None = None) -> bool:
        with _lock:
            request = _pending.get(request_id)
            if (not request or request["expires"] < time.time()
                    or (session_id is not None and request["session"] != session_id)
                    or (user_id is not None and request["user"] != user_id)):
                return False
            from agent.permission.audit import record
            record(agent=request["agent"], conversation=request["session"], project=request["project"],
                   tool=request["tool"], operation=request["operation"], resource=request["resource"],
                   risk=request["risk"], decision="allow", event="confirmation",
                   reason="User approved this exact action once.")
            del _pending[request_id]
            for other_id, other in list(_pending.items()):
                if other["key"] == request["key"]:
                    del _pending[other_id]
                    _outcomes[other_id] = ("superseded", time.time() + 300)
            if request.get("interactive"):
                _claims[request_id] = (request["key"], time.time() + 300)
            else:
                _approved[request["key"]] = time.time() + 300
            _outcomes[request_id] = ("approved", time.time() + 300)
            _condition.notify_all()
            return True

    @staticmethod
    def reject(request_id: str, *, session_id: str | None = None, user_id: str | None = None) -> bool:
        with _lock:
            request = _pending.get(request_id)
            if (not request or request["expires"] < time.time()
                    or (session_id is not None and request["session"] != session_id)
                    or (user_id is not None and request["user"] != user_id)):
                return False
            from agent.permission.audit import record
            record(agent=request["agent"], conversation=request["session"], project=request["project"],
                   tool=request["tool"], operation=request["operation"], resource=request["resource"],
                   risk=request["risk"], decision="deny", event="confirmation",
                   reason="User rejected this action.")
            del _pending[request_id]
            _outcomes[request_id] = ("rejected", time.time() + 300)
            _condition.notify_all()
            return True

    @staticmethod
    def wait_for_decision(request_id: str, cancel_event=None, policy_allows=None) -> str:
        """Pause one tool call until the exact request is approved, rejected, or cancelled."""
        with _condition:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    _pending.pop(request_id, None)
                    _claims.pop(request_id, None)
                    _outcomes[request_id] = ("cancelled", time.time() + 300)
                    _condition.notify_all()
                    return "cancelled"
                outcome = _outcomes.get(request_id)
                if outcome:
                    if outcome[0] == "approved" and request_id in _claims:
                        if request_id in _claim_assigned:
                            return "superseded"
                        _claim_assigned.add(request_id)
                    return outcome[0]
                request = _pending.get(request_id)
                if request is None or request["expires"] < time.time():
                    _pending.pop(request_id, None)
                    return "expired"
                if policy_allows is not None and policy_allows():
                    _pending.pop(request_id, None)
                    _outcomes[request_id] = ("policy_allowed", time.time() + 300)
                    _condition.notify_all()
                    return "policy_allowed"
                _condition.wait(timeout=0.1 if cancel_event is not None else 1)
