"""One execution-time permission gate for model and scheduled tool calls."""

from __future__ import annotations

from typing import Any, Dict, Optional
from contextvars import ContextVar
from contextlib import contextmanager

from agent.permission import global_mode, normalize_mode
from agent.permission.gateway import Scope, SecurityGateway
from common.log import logger


_tool_call_id = ContextVar("stella_tool_call_id", default=None)


def current_tool_call_id():
    return _tool_call_id.get()


@contextmanager
def invocation_scope(tool_call_id):
    token = _tool_call_id.set(tool_call_id)
    try:
        yield
    finally:
        _tool_call_id.reset(token)


def execution_workspace(session_id=None, agent_id=None, workspace=None):
    from agent.workspace import project_store
    from common.state_dir import state_root
    from common.runtime_identity import current_identity
    workspace = workspace or str(state_root(current_identity().derive(agent_id=agent_id)))
    project = project_store.get_project_dir(session_id, agent_id) if session_id else None
    active = project or workspace
    return active, [active]


def permission_denial(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    agent=None,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Optional[str]:
    """Return a refusal reason, resolving the current mode at call time.

    Scheduled calls may not have a live Agent. In that case the session
    preference and current workspace are read directly, with no mutable Agent
    instance shared with an interactive turn.
    """
    mode = None
    try:
        if agent is not None:
            mode = agent.effective_permission_mode()
            cwd = agent.effective_cwd()
            roots = agent.write_roots()
        else:
            from agent.workspace import session_prefs

            pref = session_prefs.get_prefs(session_id, agent_id) if session_id else {}
            mode = normalize_mode(pref.get("permission"), global_mode())
            if workspace is None:
                from common.state_dir import state_root
                from common.runtime_identity import current_identity

                workspace = str(state_root(current_identity().derive(agent_id=agent_id)))
            cwd, roots = execution_workspace(session_id, agent_id, workspace)
        from config import conf
        from common.runtime_identity import current_identity
        configured_allowlist = conf().get("agent_tool_allowlist")
        allowlist = configured_allowlist if isinstance(configured_allowlist, list) and configured_allowlist else None
        configured_accounts = conf().get("agent_account_allowlist")
        accounts = tuple(str(value) for value in configured_accounts) if isinstance(configured_accounts, list) else ()
        decision = SecurityGateway.check(
            mode, tool_name, arguments, cwd=cwd,
            scope=Scope(write_roots=tuple(roots), accounts=accounts),
            session_id=session_id or current_identity().session_id, allowlist=allowlist,
        )
        return None if decision.allowed else decision.reason
    except Exception as exc:
        logger.error(f"[Permission] Failed to check {tool_name}: {exc}")
        # A failed policy check is never an authorization to run a tool.
        return f"Permission check failed for {tool_name}; the tool did not run."
