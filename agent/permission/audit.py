"""Security decisions as bounded, value-free JSONL records."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path

_lock = threading.RLock()
_ALLOWED = {"allow", "confirm", "deny", "policy_change", "secret_use", "external_access"}


def _path() -> Path:
    from common.state_dir import shared_root
    return Path(shared_root()) / "security-activity.jsonl"


def record(**fields) -> None:
    """The caller supplies labels only. Never pass arguments or credential values."""
    from common.runtime_identity import current_identity
    ident = current_identity()
    row = {
        "at": time.time(), "agent": fields.get("agent") or ident.agent_id or "default",
        "conversation": fields.get("conversation") or ident.session_id,
        "project": fields.get("project"), "tool": fields.get("tool", "security"),
        "operation": fields.get("operation", "policy"), "resource": fields.get("resource", "policy"),
        "event": fields.get("event", "tool_decision"),
        "risk": fields.get("risk", "L0"), "decision": fields.get("decision", "allow"),
        "reason": fields.get("reason", ""), "trace": fields.get("trace", []),
    }
    operation_id = fields.get("operation_id") or fields.get("request_id")
    if operation_id:
        row["operation_id"] = str(operation_id)
    if row["decision"] not in _ALLOWED:
        raise ValueError("invalid audit decision")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            os.chmod(path, 0o600)
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def activity_counts(*, days: int = 7, now: float | None = None) -> dict:
    """Count final permission decisions in a half-open recent window."""
    until = time.time() if now is None else float(now)
    since = until - max(int(days), 1) * 86400
    path = _path()
    if not path.exists():
        return {"auto_allow": 0, "user_authorized": 0, "denied": 0, "uncertain": False,
                "since": since, "until": until}
    with _lock, path.open(encoding="utf-8") as stream:
        lines = deque(stream, maxlen=5000)
    finals: dict[str, dict] = {}
    uncertain = False
    for line in lines:
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        at = row.get("at")
        if not isinstance(at, (int, float)) or not (since <= at < until):
            continue
        decision = row.get("decision")
        if decision == "confirm":
            continue
        if decision not in {"allow", "deny"}:
            continue
        operation_id = row.get("operation_id")
        if not operation_id:
            uncertain = True
            operation_id = f"legacy:{at}:{row.get('tool')}:{row.get('conversation')}:{decision}:{row.get('event')}"
        previous = finals.get(operation_id)
        if previous is None or at >= previous.get("at", 0):
            finals[operation_id] = row
    auto_allow = user_authorized = denied = 0
    for row in finals.values():
        if row.get("decision") == "deny":
            denied += 1
        elif row.get("event") == "confirmation":
            user_authorized += 1
        else:
            auto_allow += 1
    return {"auto_allow": auto_allow, "user_authorized": user_authorized, "denied": denied,
            "uncertain": uncertain, "since": since, "until": until}


def recent(*, limit: int = 100, filters: dict | None = None) -> list[dict]:
    path = _path()
    if not path.exists():
        return []
    filters = filters or {}
    limit = min(max(int(limit), 1), 500)
    with _lock, path.open(encoding="utf-8") as stream:
        lines = deque(stream, maxlen=5000)
    rows = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
            if any(str(row.get(key) or "") != str(value) for key, value in filters.items() if value not in (None, "")):
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
        except (ValueError, TypeError):
            continue
    return rows
