"""One execution-time permission gate for model and scheduled tool calls."""

from __future__ import annotations

from typing import Any, Dict, Optional
from contextvars import ContextVar
from contextlib import contextmanager
import os
import json

from agent.permission import global_mode, normalize_mode
from agent.permission.gateway import DecisionKind, Scope, SecurityGateway
from common.log import logger


_tool_call_id = ContextVar("stella_tool_call_id", default=None)
_shell_expansion = ContextVar("stella_shell_expansion", default=None)
_browser_file_expansion = ContextVar("stella_browser_file_expansion", default=None)
_permission_limit = ContextVar("stella_permission_limit", default=None)


class ApprovalRejectedError(Exception):
    """The user rejected the pending action; this run must stop."""


def current_tool_call_id():
    return _tool_call_id.get()


def approved_shell_target(command: str) -> str | None:
    record = _shell_expansion.get()
    return record[1] if record and record[0] == command.strip() else None


def approved_browser_file(url: str) -> str | None:
    record = _browser_file_expansion.get()
    return record[1] if record and record[0] == url else None


@contextmanager
def permission_limit_scope(policy: dict, roots: tuple[str, ...]):
    parent = _permission_limit.get()
    if parent:
        from agent.permission.security_policy import intersect
        policy = intersect(policy, parent[0])
        roots = tuple(path for path in roots if any(
            os.path.commonpath((os.path.realpath(path), os.path.realpath(root))) == os.path.realpath(root)
            for root in parent[1]))
    token = _permission_limit.set((policy, roots))
    try:
        yield
    finally:
        _permission_limit.reset(token)


@contextmanager
def invocation_scope(tool_call_id):
    token = _tool_call_id.set(tool_call_id)
    try:
        yield
    finally:
        _tool_call_id.reset(token)


def execution_workspace(session_id=None, agent_id=None, workspace=None):
    from agent.workspace import project_store
    from common.state_dir import personal_work_dir
    from common.runtime_identity import current_identity
    workspace = workspace or str(personal_work_dir(current_identity().derive(agent_id=agent_id)))
    project = project_store.get_project_dir(session_id, agent_id) if session_id else None
    active = project or workspace
    return active, [active]


def _current_authorization(agent, agent_id, session_id, workspace, wait_for_approval):
    from common.runtime_identity import current_identity
    from common.state_dir import personal_work_dir
    from config import conf
    from agent.permission.security_policy import legacy_policy, resolve
    from agent.workspace import project_store

    identity = current_identity()
    if agent is not None:
        mode = agent.effective_permission_mode()
        cwd, roots = agent.effective_cwd(), agent.write_roots()
    else:
        mode = global_mode()
        default = workspace or str(personal_work_dir(identity.derive(agent_id=agent_id)))
        cwd, roots = execution_workspace(session_id, agent_id, default)
    project_dir = project_store.get_project_dir(session_id, agent_id) if session_id else None
    policy = resolve(mode, project_dir=project_dir, session_id=session_id, agent_id=agent_id)
    if agent is not None and not session_id and mode != global_mode():
        policy = legacy_policy(mode)
    limit = _permission_limit.get()
    if limit:
        from agent.permission.security_policy import intersect
        policy = intersect(policy, limit[0])
        allowed_roots = tuple(os.path.realpath(path) for path in limit[1])
        roots = [path for path in roots if any(os.path.commonpath((os.path.realpath(path), root)) == root
                                               for root in allowed_roots)]
    configured_allowlist = conf().get("agent_tool_allowlist")
    allowlist = configured_allowlist if isinstance(configured_allowlist, list) and configured_allowlist else None
    configured_accounts = conf().get("agent_account_allowlist")
    accounts = tuple(str(value) for value in configured_accounts) if isinstance(configured_accounts, list) else ()
    kwargs = dict(cwd=cwd, scope=Scope(write_roots=tuple(roots), accounts=accounts),
                  session_id=session_id, allowlist=allowlist, policy=policy,
                  agent_id=agent_id, project_dir=project_dir, reserve_for_waiter=wait_for_approval)
    binding = (identity.user_id, identity.run_id, agent_id, session_id, project_dir,
               cwd, tuple(roots), accounts, tuple(allowlist or ()),
               json.dumps(policy, sort_keys=True, ensure_ascii=False))
    return mode, kwargs, binding


def permission_denial(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    agent=None,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    workspace: Optional[str] = None,
    wait_for_approval: bool = False,
    noninteractive: bool = False,
    cancel_event=None,
) -> Optional[str]:
    """Return a refusal reason, resolving the current mode at call time.

    Scheduled calls may not have a live Agent. In that case the session
    preference and current workspace are read directly, with no mutable Agent
    instance shared with an interactive turn.
    """
    try:
        _shell_expansion.set(None)
        _browser_file_expansion.set(None)
        from common.runtime_identity import current_identity
        identity = current_identity()
        session_id = session_id or identity.session_id
        agent_id = agent_id or identity.agent_id
        mode, check_kwargs, binding = _current_authorization(
            agent, agent_id, session_id, workspace, wait_for_approval)
        decision = SecurityGateway.check(mode, tool_name, arguments,
                                         create_pending=not noninteractive, **check_kwargs)
        if decision.kind is DecisionKind.CONFIRM and wait_for_approval:
            outcome = SecurityGateway.wait_for_decision(decision.request_id, cancel_event)
            if outcome == "approved":
                if cancel_event is not None and cancel_event.is_set():
                    from agent.protocol.cancel import AgentCancelledError
                    raise AgentCancelledError("cancelled while waiting for approval")
                # A queued approval cannot follow a different project/run or a
                # changed resource grant. Re-resolve every policy input as well.
                mode, fresh_kwargs, fresh_binding = _current_authorization(
                    agent, agent_id, session_id, workspace, wait_for_approval)
                if fresh_binding != binding:
                    raise ApprovalRejectedError("审批期间工作区或授权范围已变化，本轮已停止。")
                decision = SecurityGateway.check(mode, tool_name, arguments,
                                                 approval_request_id=decision.request_id, **fresh_kwargs)
                if cancel_event is not None and cancel_event.is_set():
                    from agent.protocol.cancel import AgentCancelledError
                    raise AgentCancelledError("cancelled while waiting for approval")
                if not decision.allowed:
                    raise ApprovalRejectedError(
                        f"审批后安全策略仍不允许 {tool_name} 操作，本轮已停止。{decision.reason}")
            elif outcome in ("rejected", "superseded"):
                message = (f"用户拒绝了 {tool_name} 操作，本轮已停止。" if outcome == "rejected" else
                           f"{tool_name} 的一次性审批已由另一轮使用，本轮已停止。")
                raise ApprovalRejectedError(message)
            elif outcome == "cancelled":
                from agent.protocol.cancel import AgentCancelledError
                raise AgentCancelledError("cancelled while waiting for approval")
            else:
                raise ApprovalRejectedError(f"{tool_name} 审批已过期，本轮已停止；操作未执行。")
        if decision.allowed:
            if tool_name == "bash" and decision.resource.startswith("/"):
                _shell_expansion.set((str(arguments.get("command") or "").strip(), decision.resource))
            if tool_name == "browser" and decision.resource.startswith("/"):
                _browser_file_expansion.set((str(arguments.get("url") or ""), decision.resource))
            return None
        if decision.kind is DecisionKind.CONFIRM:
            if noninteractive:
                return decision.reason
            return (decision.reason + " Wait for approval before retrying this exact action; "
                    "do not try a different tool to avoid confirmation.")
        return (decision.reason + " The action did not run. Do not bypass the refusal "
                "with a script or equivalent tool. Use a supported connector or explain the "
                "required policy or resource grant to the user.")
    except ApprovalRejectedError:
        raise
    except Exception as exc:
        from agent.protocol.cancel import AgentCancelledError
        if isinstance(exc, AgentCancelledError):
            raise
        logger.error(f"[Permission] Failed to check {tool_name}: {exc}")
        # A failed policy check is never an authorization to run a tool.
        return f"Permission check failed for {tool_name}; the tool did not run."
