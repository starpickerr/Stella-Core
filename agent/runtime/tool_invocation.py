"""One execution-time permission gate for model and scheduled tool calls."""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent.permission import FULL_ACCESS, check_tool_call, global_mode, normalize_mode
from common.log import logger


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
            cwd = workspace
            roots = [workspace]
        if mode == FULL_ACCESS:
            return None
        decision = check_tool_call(mode, tool_name, arguments, cwd=cwd, write_roots=roots)
        return None if decision.allowed else decision.reason
    except Exception as exc:
        logger.error(f"[Permission] Failed to check {tool_name}: {exc}")
        # A failed policy check is never an authorization to run a tool.
        return f"Permission check failed for {tool_name}; the tool did not run."
