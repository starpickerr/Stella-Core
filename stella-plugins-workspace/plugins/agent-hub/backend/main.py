"""Agent Hub plugin entry — provider config, probe, external mapping.

No Stella ``agent.*`` / ``core.*`` imports. Core owns ExecutionService status;
this worker owns Provider configs and external session/run refs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from domain.service import AgentHubService, ProviderNotFound  # noqa: E402
from domain.store import AgentHubStore  # noqa: E402

CONTRACT = "stella.agent-hub@1"
R, W = "agent_hub.read", "agent_hub.write"

METHODS: dict[str, tuple[str, str, bool, tuple[str, ...]]] = {
    "list_catalog": ("query", R, False, ()),
    "status_overview": ("query", R, False, ()),
    "list_providers": ("query", R, False, ("enabled_only",)),
    "get_provider": ("query", R, False, ("provider_config_id",)),
    "probe_provider": ("query", R, False, ("provider_config_id",)),
    "ensure_defaults": ("domainWrite", W, True, ()),
    "upsert_provider": ("domainWrite", W, True, ("provider",)),
    "delete_provider": ("domainWrite", W, True, ("provider_config_id",)),
    "select_provider": ("query", R, False, ("selector",)),
    "map_external_run": ("domainWrite", W, True, ("mapping",)),
    "get_external_run": ("query", R, False, ("execution_id",)),
    "list_external_runs": ("query", R, False, ("limit",)),
    "provider_start": ("domainWrite", W, True, ("provider_config_id", "task")),
    "provider_observe": ("query", R, False, ("execution_id",)),
    "provider_cancel": ("domainWrite", W, True, ("execution_id",)),
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
                "timeoutMs": 120000 if name.startswith("provider_") else 30000,
            }
            for name, (effect, perm, idem, params) in METHODS.items()
        ],
    }
]


_SERVICES: dict[str, AgentHubService] = {}


def _service(invoke_params: dict[str, Any]) -> AgentHubService:
    handle = invoke_params.get("_hostDataHandle") or {}
    db_path = handle.get("dbPath")
    if not db_path:
        raise RuntimeError("host data handle with dbPath required")
    key = str(Path(db_path).resolve())
    if key not in _SERVICES:
        _SERVICES[key] = AgentHubService(AgentHubStore(Path(key)))
    return _SERVICES[key]


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
    if method == "provider_start":
        task = (invoke_params.get("_hostDataHandle") or {}).get("executionTask")
        if not task:
            return _fail("invalid_argument", "Core execution lease required")
        params["task"] = dict(task)
    try:
        value = getattr(_service(invoke_params), method)(**params)
    except ProviderNotFound as exc:
        return _fail("not_found", str(exc))
    except (ValueError, TypeError, KeyError) as exc:
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
