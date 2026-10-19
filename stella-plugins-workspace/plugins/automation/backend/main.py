"""Automation plugin entry — task rules, mutations and handler planning.

No Stella ``agent.*`` imports. Core keeps the scheduler tick, occurrence leases,
dispatch and delivery; this worker owns what a task *is* and which mutations are
legal. Host capabilities arrive through ``_hostDataHandle`` (JSON only):
  dbPath    required path of the shared ``automation.db``
  agentId   required owner agent id
  userId    owner user id ("" for the single local user)
Destination catalogs, route normalization and conversation-scope validation need
live channels/projects, so the host resolves them and passes ``resolved`` to
``update_task`` / pre-resolved ``action`` to ``create_task``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from domain.service import AutomationService, TaskNotFound
from domain.store import TaskRuleStore

CONTRACT = "stella.automation@1"
R, W = "automation.read", "automation.write"

# name -> (effect, permission, idempotent, ordered parameter names)
METHODS: dict[str, tuple[str, str, bool, tuple[str, ...]]] = {
    "get_task": ("query", R, False, ("task_id",)),
    "list_tasks": ("query", R, False, ("enabled_only",)),
    "calculate_next_run": ("query", R, False, ("task", "from_time")),
    "validate_task": ("query", R, False, ("task", "origin")),
    "resolve_handler": ("query", R, False, ("task",)),
    "create_task": ("domainWrite", W, True, ("task", "origin")),
    "update_task": ("domainWrite", W, True, ("task_id", "patch", "resolved", "origin")),
    "delete_task": ("domainWrite", W, True, ("task_id",)),
    "enable_task": ("domainWrite", W, True, ("task_id", "enabled")),
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


def _service(invoke_params: dict[str, Any]) -> AutomationService:
    handle = invoke_params.get("_hostDataHandle") or {}
    db_path = handle.get("dbPath")
    agent_id = handle.get("agentId")
    if not db_path or not agent_id:
        raise RuntimeError("host data handle with dbPath and agentId required")
    return AutomationService(TaskRuleStore(Path(db_path), agent_id, handle.get("userId") or ""))


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
        value = getattr(_service(invoke_params), method)(**params)
    except TaskNotFound as exc:
        return _fail("not_found", str(exc))
    except (ValueError, TypeError) as exc:
        return _fail("invalid_argument", str(exc))
    if effect == "query":
        return {"status": "succeeded", "sideEffects": "none", "value": value}
    return {
        "status": "succeeded",
        "sideEffects": "committed",
        "value": value,
        "operationId": invoke_params.get("idempotencyKey") or method,
    }


def _fail(code: str, message: str) -> dict[str, Any]:
    return {"status": "failed", "sideEffects": "none", "error": {"code": code, "message": message}}
