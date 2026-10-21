"""One execution-time permission gate for model and scheduled tool calls."""

from __future__ import annotations

from typing import Any, Dict, Optional
from contextvars import ContextVar
from contextlib import contextmanager
import os
import json

from agent.permission import global_mode
from agent.permission.gateway import DecisionKind, Scope, SecurityGateway
from common.log import logger


_tool_call_id = ContextVar("stella_tool_call_id", default=None)
_shell_expansion = ContextVar("stella_shell_expansion", default=None)
_browser_file_expansion = ContextVar("stella_browser_file_expansion", default=None)
_permission_limit = ContextVar("stella_permission_limit", default=None)
_scheduled_permission = ContextVar("stella_scheduled_permission", default=None)


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
def scheduled_permission_scope(mode):
    """Apply one task's explicit preset for this run, then restore the caller."""
    if mode not in {"read-only", "workspace-write", "full-access"}:
        yield
        return
    token = _scheduled_permission.set(mode)
    try:
        yield
    finally:
        _scheduled_permission.reset(token)


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
    from core.workspace.service import resolve_context
    from common.runtime_identity import current_identity
    identity = current_identity()
    context = resolve_context(identity.execution_session_id or session_id, agent_id,
                              task_id=identity.task_id)
    active = str(context.root)
    return active, [active]


def _current_authorization(agent, agent_id, session_id, workspace, wait_for_approval):
    from common.runtime_identity import current_identity
    from config import conf
    from agent.permission.security_policy import resolve
    from agent.workspace import project_store
    from agent.workspace.shares import grant_version

    identity = current_identity()
    if agent is not None:
        mode = agent.effective_permission_mode()
        cwd, roots = agent.effective_cwd(), agent.write_roots()
    else:
        mode = global_mode()
        cwd, roots = execution_workspace(session_id, agent_id, workspace)
    scope_session_id = identity.execution_session_id or session_id
    project_dir = project_store.get_project_dir(scope_session_id, agent_id) if scope_session_id else None
    policy = resolve(mode, project_dir=project_dir, session_id=scope_session_id, agent_id=agent_id)
    override = _scheduled_permission.get()
    if override:
        policy = {**policy, "preset": override, "base_preset": override, "rules": {}}
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
               grant_version(), json.dumps(policy, sort_keys=True, ensure_ascii=False))
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
    tool=None,
    user_action: bool = False,
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
        from agent.tools.capability_settings import tool_enabled
        capability_scope = dict(tool=tool, agent_id=agent_id,
                                workspace_root=getattr(agent, 'workspace_dir', None))
        if not tool_enabled(tool_name, **capability_scope):
            return f'Tool {tool_name} is disabled.'
        mode, check_kwargs, binding = _current_authorization(
            agent, agent_id, session_id, workspace, wait_for_approval)
        decision = SecurityGateway.check(mode, tool_name, arguments,
                                         create_pending=not noninteractive, **check_kwargs)
        if decision.kind is DecisionKind.CONFIRM and wait_for_approval:
            def policy_now_allows():
                fresh_mode, fresh_kwargs, fresh_binding = _current_authorization(
                    agent, agent_id, session_id, workspace, wait_for_approval)
                # A mode change may authorize this exact action while it waits.
                # Changing the workspace or identity cannot transfer approval.
                if fresh_binding[:-1] != binding[:-1] or fresh_binding[-1] == binding[-1]:
                    return False
                return SecurityGateway.check(fresh_mode, tool_name, arguments,
                                             create_pending=False, **fresh_kwargs).allowed

            outcome = SecurityGateway.wait_for_decision(
                decision.request_id, cancel_event, policy_allows=policy_now_allows)
            if outcome == "policy_allowed":
                mode, fresh_kwargs, fresh_binding = _current_authorization(
                    agent, agent_id, session_id, workspace, wait_for_approval)
                if fresh_binding[:-1] != binding[:-1] or not SecurityGateway.check(
                        mode, tool_name, arguments, create_pending=False, **fresh_kwargs).allowed:
                    raise ApprovalRejectedError("权限或工作区在执行前再次变化，本轮已停止。")
                decision = SecurityGateway.check(mode, tool_name, arguments,
                                                 create_pending=False, **fresh_kwargs)
            elif outcome == "approved":
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
        # A native settings action is explicit confirmation by the authenticated
        # owner, but it cannot override DENY or authorize Agent/background work.
        owner_confirmed = (user_action and not any((identity.agent_id, identity.session_id,
                            identity.task_id, identity.run_id)) and
                           decision.kind is DecisionKind.CONFIRM)
        if decision.allowed or owner_confirmed:
            if not tool_enabled(tool_name, **capability_scope):
                return f'Tool {tool_name} is disabled.'
            if tool_name in {"read", "write", "edit", "ls", "search_files", "bash", "vision"}:
                from core.workspace.service import resolve_context
                context = resolve_context(identity.execution_session_id or session_id, agent_id,
                                          task_id=identity.task_id)
                if context.kind in ("session", "automation"):
                    context.root.mkdir(parents=True, exist_ok=True)
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
