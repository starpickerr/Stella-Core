"""Bills plugin entry — no Stella agent.bills imports."""

from __future__ import annotations

import sys
import base64
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from domain.service import BillsService

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

SERVICE_DESCRIPTORS = [
    {
        "contract": "stella.bills@1",
        "methods": [
            {
                "name": name,
                "inputSchema": {"type": "object"},
                "outputSchema": {"type": "object"},
                "effect": effect,
                "permissions": [perm],
                "resourceScope": ["user"],
                "idempotency": idem,
                "timeoutMs": 30000,
            }
            for name, effect, perm, idem in (
                ("list_ledger", "query", "bills.read", False),
                ("list_ledger_between", "query", "bills.read", False),
                ("get_ledger", "query", "bills.read", False),
                ("create_ledger", "domainWrite", "bills.write", True),
                ("update_ledger", "domainWrite", "bills.write", True),
                ("delete_ledger", "domainWrite", "bills.write", True),
                ("list_statements", "query", "bills.read", False),
                ("get_statement", "query", "bills.read", False),
                ("export_ledger", "query", "bills.read", False),
                ("get_operation", "query", "bills.read", False),
            )
        ],
    }
]


def _service(invoke_params: dict[str, Any]) -> BillsService:
    from domain.service import BillsService
    from domain.store import BillStore

    handle = invoke_params.get("_hostDataHandle") or {}
    db_path = handle.get("dbPath")
    if not db_path:
        raise RuntimeError("host data handle with dbPath required")
    return BillsService(BillStore(Path(db_path)))


def handle_invoke(invoke_params: dict[str, Any]) -> dict[str, Any]:
    method = invoke_params["method"]
    params = dict(invoke_params.get("input") or {})
    idem = invoke_params.get("idempotencyKey")
    svc = _service(invoke_params)
    try:
        if method == "list_ledger":
            return _ok(svc.list_ledger(int(params["year"]), int(params["month"])))
        if method == "list_ledger_between":
            return _ok(svc.list_ledger_between(params["start"], params["end"]))
        if method == "get_ledger":
            return _ok(svc.get_ledger(params["id"]))
        if method == "create_ledger":
            saved = svc.create_ledger(params, idempotency_key=idem)
            return _write_ok(saved, idem or saved["id"])
        if method == "update_ledger":
            entry_id = params["id"]
            patch = dict(params.get("patch") or params)
            expected = patch.pop("expectedRevision", params.get("expectedRevision"))
            patch.pop("id", None)
            saved = svc.update_ledger(
                entry_id,
                patch,
                expected_revision=expected,
                idempotency_key=idem,
            )
            return _write_ok(saved, idem or saved["id"])
        if method == "delete_ledger":
            svc.delete_ledger(
                params["id"],
                expected_revision=params.get("expectedRevision"),
                idempotency_key=idem,
            )
            return {
                "status": "succeeded",
                "sideEffects": "committed",
                "value": {"deleted": True, "id": params["id"]},
                "operationId": idem or params["id"],
            }
        if method == "list_statements":
            return _ok(svc.list_statements(params.get("period_type"), params.get("year")))
        if method == "get_statement":
            return _ok(svc.get_statement(params["id"]))
        if method == "get_operation":
            return _ok(svc.get_operation(params["operationId"]))
        if method == "export_ledger":
            from domain.export import build_ledger_xlsx

            start, end = params["start"], params["end"]
            rows = svc.list_ledger_between(start, end)
            data = build_ledger_xlsx(rows, start, end, params.get("lang", "zh"))
            return _ok({"encoding": "base64", "content": base64.b64encode(data).decode("ascii")})
        return {
            "status": "failed",
            "sideEffects": "none",
            "error": {"code": "not_found", "message": f"unknown method: {method}"},
        }
    except KeyError as exc:
        return {"status": "failed", "sideEffects": "none", "error": {"code": "not_found", "message": str(exc)}}
    except ValueError as exc:
        code = "conflict" if "conflict" in str(exc) else "invalid_argument"
        return {"status": "failed", "sideEffects": "none", "error": {"code": code, "message": str(exc)}}


def _ok(value: Any) -> dict[str, Any]:
    return {"status": "succeeded", "sideEffects": "none", "value": value}


def _write_ok(value: Any, operation_id: str) -> dict[str, Any]:
    return {
        "status": "succeeded",
        "sideEffects": "committed",
        "value": value,
        "operationId": operation_id,
    }
