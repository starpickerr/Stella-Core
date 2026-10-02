"""Execution-time security gate shared by chat, scheduled work and commands."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from agent.permission.policy import Decision, MODES, check_tool_call


class Capability(str, Enum):
    READ = "read"
    WORKSPACE_WRITE = "workspace-write"
    EXTERNAL = "external"
    ADMIN = "admin"


@dataclass(frozen=True)
class Scope:
    write_roots: tuple[str, ...] = ()
    accounts: tuple[str, ...] = ()


_READ_TOOLS = frozenset({
    "read", "ls", "search_files", "memory_search", "memory_get", "web_search",
    "web_fetch", "vision", "elearning",
})
_WRITE_TOOLS = frozenset({"write", "edit", "bash"})
_EXTERNAL_TOOLS = frozenset({
    "browser", "scheduler", "env_config", "briefing", "calendar", "todos",
    "bills", "send", "subagent",
})
_ADMIN_TOOLS = frozenset({"evolution_undo"})
_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")
_lock = threading.RLock()
_pending: dict[str, dict] = {}
_approved: set[str] = set()
_registered: dict[str, Capability] = {}


def register_tool(tool_name: str, capability: Capability) -> None:
    if not _SAFE_NAME.fullmatch(tool_name) or not isinstance(capability, Capability):
        raise ValueError("invalid tool declaration")
    with _lock:
        _registered[tool_name] = capability


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


def _fingerprint(tool_name: str, arguments: Mapping[str, Any], session_id: Optional[str]) -> str:
    payload = json.dumps([session_id, tool_name, arguments], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _risky(tool_name: str, arguments: Mapping[str, Any]) -> bool:
    action = str(arguments.get("action") or "").lower()
    if tool_name == "browser" and action == "evaluate":
        return True
    if tool_name == "evolution_undo":
        return True
    if tool_name == "bash":
        command = str(arguments.get("command") or "")
        return bool(re.search(r"\b(?:rm\s+-(?:\w*r\w*f|\w*f\w*r)|sudo|doas)\b", command))
    return False


def _summary(tool_name: str, arguments: Mapping[str, Any]) -> str:
    from common.log import _redact
    if tool_name == "bash":
        detail = str(arguments.get("command") or "")
    elif tool_name == "browser":
        detail = str(arguments.get("script") or arguments.get("expression") or "")
    else:
        detail = str(arguments.get("action") or tool_name)
    return _redact(detail)[:240]


def _audit(tool_name: str, capability: Optional[Capability], allowed: bool, reason: str) -> None:
    """Persist only fixed labels; arguments, paths and credentials never enter the log."""
    try:
        from common.state_dir import shared_root
        from common.runtime_identity import current_identity

        identity = current_identity()
        row = {
            "at": time.time(),
            "tool": tool_name if _SAFE_NAME.fullmatch(tool_name) else "unknown",
            "capability": capability.value if capability else "unknown",
            "decision": "allow" if allowed else "deny",
            "reason": reason,
            "session": identity.session_id,
        }
        path = Path(shared_root()) / "security-audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        # Audit failure must not turn a denial into authorization.
        pass


class SecurityGateway:
    @staticmethod
    def check(
        mode: str, tool_name: str, arguments: Mapping[str, Any], *,
        cwd: Optional[str] = None, scope: Optional[Scope] = None,
        session_id: Optional[str] = None, allowlist: Optional[Sequence[str]] = None,
        capability: Optional[Capability] = None,
    ) -> Decision:
        declared = declared_capability(tool_name)
        if capability is not None and (not isinstance(capability, Capability) or capability != declared):
            decision = Decision(False, "Unknown or mismatched capability; the tool did not run.")
        elif declared is None or mode not in MODES:
            decision = Decision(False, "Unknown tool capability or permission mode; the tool did not run.")
        elif allowlist is not None and tool_name not in allowlist:
            decision = Decision(False, "Tool is outside the current allowlist; it did not run.")
        elif scope and scope.accounts and arguments.get("account") not in scope.accounts:
            decision = Decision(False, "Account is outside the current scope; the tool did not run.")
        else:
            roots = scope.write_roots if scope else None
            decision = check_tool_call(mode, tool_name, dict(arguments), cwd=cwd, write_roots=roots)
            if decision.allowed and _risky(tool_name, arguments):
                key = _fingerprint(tool_name, arguments, session_id)
                with _lock:
                    if key in _approved:
                        _approved.remove(key)
                    else:
                        request_id = uuid.uuid4().hex
                        _pending[request_id] = {
                            "key": key, "tool": tool_name, "session": session_id,
                            "summary": _summary(tool_name, arguments),
                            "expires": time.time() + 300,
                        }
                        decision = Decision(False, f"Confirmation required for {tool_name}. Request {request_id} is waiting in Security; retry after approval.")
        _audit(tool_name, declared, decision.allowed, "allowed" if decision.allowed else "policy")
        return decision

    @staticmethod
    def pending() -> list[dict]:
        now = time.time()
        with _lock:
            for request_id, request in list(_pending.items()):
                if request["expires"] < now:
                    del _pending[request_id]
            return [
                {"id": request_id, "tool": request["tool"], "session": request["session"],
                 "summary": request["summary"]}
                for request_id, request in _pending.items()
            ]

    @staticmethod
    def approve(request_id: str) -> bool:
        with _lock:
            request = _pending.pop(request_id, None)
            if not request or request["expires"] < time.time():
                return False
            for other_id, other in list(_pending.items()):
                if other["key"] == request["key"]:
                    del _pending[other_id]
            _approved.add(request["key"])
            return True
