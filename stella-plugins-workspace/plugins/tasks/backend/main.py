"""Tasks plugin entry — no Stella agent.todos / agent.scheduler imports.

Host-provided capabilities arrive through ``_hostDataHandle`` (JSON only):
  dbPath                 required SQLite path for this user's Tasks data
  legacyCalendarDbPath   optional; enables one-time calendar-affairs migration
Scheduler and notification adapters are not available across the worker boundary,
so reminder sync is a no-op here and the host reconciles ``pending_scheduler_links``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from domain.service import TodoService

CONTRACT = "stella.tasks@1"

# name -> (effect, permission, idempotent, ordered parameter names)
METHODS: dict[str, tuple[str, str, bool, tuple[str, ...]]] = {
    "get_todo": ("query", "tasks.read", False, ("todo_id",)),
    "list_todos": ("query", "tasks.read", False, ("start", "end", "include_completed")),
    "list_todos_focus": ("query", "tasks.read", False, ("today",)),
    "list_uncertain_reminders": ("query", "tasks.read", False, ()),
    "categories": ("query", "tasks.read", False, ()),
    "get_category": ("query", "tasks.read", False, ("category_id",)),
    "has_source_tombstone": ("query", "tasks.read", False, ("source_keys",)),
    "pending_scheduler_links": ("query", "tasks.read", False, ()),
    "complete_scheduler_link": (
        "domainWrite",
        "tasks.write",
        True,
        ("todo_id", "desired_at", "outcome", "error"),
    ),
    "create_todo": ("domainWrite", "tasks.write", True, ("payload",)),
    "update_todo": ("domainWrite", "tasks.write", True, ("todo_id", "payload")),
    "delete_todo": ("domainWrite", "tasks.write", True, ("todo_id", "preserve_children")),
    "complete_todo": ("domainWrite", "tasks.write", True, ("todo_id", "completed", "force")),
    "complete_checklist_item": ("domainWrite", "tasks.write", True, ("todo_id", "item_id", "completed")),
    "change_todo_status": ("domainWrite", "tasks.write", True, ("todo_id", "status", "force")),
    "add_subtask": ("domainWrite", "tasks.write", True, ("parent_id", "payload")),
    "move_todo": ("domainWrite", "tasks.write", True, ("todo_id", "parent_id", "position")),
    "add_dependency": ("domainWrite", "tasks.write", True, ("todo_id", "prerequisite_id")),
    "remove_dependency": ("domainWrite", "tasks.write", True, ("todo_id", "prerequisite_id")),
    "claim_due_todo_notifications": ("domainWrite", "tasks.write", False, ("now",)),
    "claim_desktop_reminders": ("domainWrite", "tasks.write", False, ("now", "limit")),
    "acknowledge_desktop_reminder": ("domainWrite", "tasks.write", True, ("delivery_id", "claim_id", "shown", "error")),
    "retry_uncertain_reminder": ("domainWrite", "tasks.write", True, ("delivery_id",)),
    "queue_scheduled_reminder": ("domainWrite", "tasks.write", True, ("todo_id", "expected_at", "now")),
    "ingest_briefing_revision": ("domainWrite", "tasks.write", True, ("detail", "revision")),
    "sync_briefing_facts": ("domainWrite", "tasks.write", True, ("todo_id", "changes", "baseline", "force")),
    "upsert_external_todo": ("domainWrite", "tasks.write", True, ("source_key", "payload", "todo_id", "reconciled")),
    "delete_external_todo": ("domainWrite", "tasks.write", True, ("source_key", "confirm")),
    "create_category": ("domainWrite", "tasks.write", True, ("payload",)),
    "update_category": ("domainWrite", "tasks.write", True, ("category_id", "payload")),
    "delete_category": ("domainWrite", "tasks.write", True, ("category_id",)),
    "set_todo_category": ("domainWrite", "tasks.write", True, ("todo_id", "category_id")),
}

SERVICE_DESCRIPTORS = [
    {
        "contract": CONTRACT,
        "methods": [
            {
                "name": name,
                "inputSchema": {
                    "type": "object",
                    "properties": {param: {} for param in params},
                    "additionalProperties": False,
                },
                "outputSchema": {},
                "effect": effect,
                "permissions": [perm],
                "resourceScope": ["user"],
                "idempotency": idem,
                "timeoutMs": 30000,
            }
            for name, (effect, perm, idem, params) in METHODS.items()
        ],
    }
]


def _service(invoke_params: dict[str, Any]) -> TodoService:
    handle = invoke_params.get("_hostDataHandle") or {}
    db_path = handle.get("dbPath")
    if not db_path:
        raise RuntimeError("host data handle with dbPath required")
    return TodoService(
        Path(db_path),
        legacy_calendar_db_path=handle.get("legacyCalendarDbPath"),
    )


def _pending_scheduler_links(svc: TodoService) -> list[dict[str, Any]]:
    with svc._connect() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT l.todo_id,l.task_id,l.desired_at,l.state,l.error,"
                "t.title,t.remind_at,t.status,t.reminder_delivery,t.source_type "
                "FROM todo_scheduler_links l LEFT JOIN todos t ON t.id=l.todo_id "
                "WHERE l.state='pending'"
            )
        ]


def _complete_scheduler_link(svc: TodoService, params: dict[str, Any]) -> dict[str, Any]:
    """Host marks a pending reminder link after applying Core TaskStore sync."""
    from datetime import datetime, timezone

    todo_id = params["todo_id"]
    desired_at = params.get("desired_at")
    outcome = params.get("outcome") or "synced"
    error = params.get("error") or ""
    now = datetime.now(timezone.utc).isoformat()
    with svc._connect() as db:
        if outcome == "synced" and desired_at:
            db.execute(
                """UPDATE todo_scheduler_links SET state='synced',error='',updated_at=?
                   WHERE todo_id=? AND desired_at=?""",
                (now, todo_id, desired_at),
            )
        elif outcome == "cleared":
            db.execute(
                "DELETE FROM todo_scheduler_links WHERE todo_id=? AND desired_at IS ?",
                (todo_id, desired_at),
            )
        else:
            db.execute(
                "UPDATE todo_scheduler_links SET error=?,updated_at=? WHERE todo_id=?",
                (str(error), now, todo_id),
            )
    return {"todo_id": todo_id, "outcome": outcome}


def handle_invoke(invoke_params: dict[str, Any]) -> dict[str, Any]:
    method = invoke_params["method"]
    spec = METHODS.get(method)
    if spec is None:
        return _fail("not_found", f"unknown method: {method}")
    effect, _perm, _idem, allowed = spec
    params = dict(invoke_params.get("input") or {})
    unknown = sorted(set(params) - set(allowed))
    if unknown:
        return _fail("invalid_argument", f"unknown parameters for {method}: {', '.join(unknown)}")
    try:
        svc = _service(invoke_params)
        if method == "pending_scheduler_links":
            return _ok(_pending_scheduler_links(svc))
        if method == "complete_scheduler_link":
            value = _complete_scheduler_link(svc, params)
            return {
                "status": "succeeded",
                "sideEffects": "committed",
                "value": value,
                "operationId": invoke_params.get("idempotencyKey") or method,
            }
        value = getattr(svc, method)(**params)
        if method == "delete_todo":
            value = {"deleted": True, "id": params["todo_id"]}
        elif method == "sync_briefing_facts":
            value = list(value)
    except KeyError as exc:
        return _fail("not_found", str(exc.args[0]) if exc.args else "not found")
    except ValueError as exc:
        text = str(exc)
        code = "conflict" if "conflict" in text or text.startswith("unfinished_dependencies") else "invalid_argument"
        return _fail(code, text)
    if effect == "query":
        return _ok(value)
    return {
        "status": "succeeded",
        "sideEffects": "committed",
        "value": value,
        "operationId": invoke_params.get("idempotencyKey") or method,
    }


def _ok(value: Any) -> dict[str, Any]:
    return {"status": "succeeded", "sideEffects": "none", "value": value}


def _fail(code: str, message: str) -> dict[str, Any]:
    return {"status": "failed", "sideEffects": "none", "error": {"code": code, "message": message}}
