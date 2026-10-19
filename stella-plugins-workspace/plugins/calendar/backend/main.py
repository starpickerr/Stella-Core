"""Calendar plugin entry — no Stella agent.calendar imports."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from domain.service import CalendarService

# (name, effect, permission, idempotent)
_METHODS = (
    ("categories", "query", "calendar.read", False),
    ("get_category", "query", "calendar.read", False),
    ("get_event", "query", "calendar.read", False),
    ("list_events", "query", "calendar.read", False),
    ("has_source_tombstone", "query", "calendar.read", False),
    ("create_category", "domainWrite", "calendar.write", True),
    ("update_category", "domainWrite", "calendar.write", True),
    ("delete_category", "domainWrite", "calendar.write", True),
    ("set_event_category", "domainWrite", "calendar.write", True),
    ("create_event", "domainWrite", "calendar.write", True),
    ("update_event", "domainWrite", "calendar.write", True),
    ("delete_event", "domainWrite", "calendar.write", True),
    ("upsert_external_event", "domainWrite", "calendar.write", True),
    ("exclude_occurrence", "domainWrite", "calendar.write", True),
    ("import_china_holidays", "domainWrite", "calendar.write", True),
    ("create_special_date", "domainWrite", "calendar.write", True),
    ("import_special_dates", "domainWrite", "calendar.write", True),
    ("ingest_briefing_revision", "domainWrite", "calendar.write", True),
    ("sync_briefing_facts", "domainWrite", "calendar.write", True),
)
WRITE_METHODS = frozenset(name for name, effect, _p, _i in _METHODS if effect == "domainWrite")

SERVICE_DESCRIPTORS = [
    {
        "contract": "stella.calendar@1",
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
            for name, effect, perm, idem in _METHODS
        ],
    }
]


def _service(invoke_params: dict[str, Any]) -> CalendarService:
    handle = invoke_params.get("_hostDataHandle") or {}
    db_path = handle.get("dbPath")
    if not db_path:
        raise RuntimeError("host data handle with dbPath required")
    return CalendarService(Path(db_path))


def _dispatch(svc: CalendarService, method: str, p: dict[str, Any]) -> Any:
    if method == "categories":
        return svc.categories()
    if method == "get_category":
        return svc.get_category(p["id"])
    if method == "create_category":
        return svc.create_category(p)
    if method == "update_category":
        return svc.update_category(p["id"], dict(p.get("patch") or {}))
    if method == "delete_category":
        svc.delete_category(p["id"])
        return {"deleted": True, "id": p["id"]}
    if method == "set_event_category":
        return svc.set_event_category(p["id"], p.get("category_id"))
    if method == "get_event":
        return svc.get_event(p["id"])
    if method == "list_events":
        return svc.list_events(p.get("start"), p.get("end"), p.get("category_id"))
    if method == "create_event":
        body = dict(p)
        briefing_key = body.pop("_briefing_key", None)
        return svc.create_event(body, _briefing_key=briefing_key)
    if method == "update_event":
        return svc.update_event(p["id"], dict(p.get("patch") or {}))
    if method == "delete_event":
        svc.delete_event(p["id"])
        return {"deleted": True, "id": p["id"]}
    if method == "upsert_external_event":
        return svc.upsert_external_event(
            p["provider"],
            p["source_key"],
            dict(p.get("payload") or {}),
            event_id=p.get("event_id"),
            reconciled=bool(p.get("reconciled", False)),
        )
    if method == "exclude_occurrence":
        svc.exclude_occurrence(p["series_id"], p["occurrence_on"])
        return {"excluded": True, "series_id": p["series_id"], "occurrence_on": p["occurrence_on"]}
    if method == "import_china_holidays":
        return svc.import_china_holidays(p.get("year"))
    if method == "create_special_date":
        return svc.create_special_date(p)
    if method == "import_special_dates":
        return svc.import_special_dates(p.get("content"), p.get("format"), p.get("timezone"))
    if method == "ingest_briefing_revision":
        detail = {"briefing": {"id": p["briefing_id"]}}
        return {"count": svc.ingest_briefing_revision(detail, int(p["revision"]))}
    if method == "has_source_tombstone":
        return {"tombstoned": svc.has_source_tombstone(list(p.get("source_keys") or []))}
    if method == "sync_briefing_facts":
        row, conflicts = svc.sync_briefing_facts(
            p["id"],
            dict(p.get("changes") or {}),
            dict(p.get("baseline") or {}),
            force=bool(p.get("force", False)),
        )
        return {"event": row, "conflicts": conflicts}
    raise LookupError(method)


def handle_invoke(invoke_params: dict[str, Any]) -> dict[str, Any]:
    method = invoke_params["method"]
    params = dict(invoke_params.get("input") or {})
    idem = invoke_params.get("idempotencyKey")
    if method not in {name for name, *_ in _METHODS}:
        return _failed("not_found", f"unknown method: {method}")
    try:
        svc = _service(invoke_params)
        value = _dispatch(svc, method, params)
    except KeyError as exc:
        return _failed("not_found", str(exc.args[0]) if exc.args else "not found")
    except ValueError as exc:
        return _failed("invalid_argument", str(exc))
    if method in WRITE_METHODS:
        op_id = idem or (value.get("id") if isinstance(value, dict) else None) or method
        return {
            "status": "succeeded",
            "sideEffects": "committed",
            "value": value,
            "operationId": op_id,
        }
    return {"status": "succeeded", "sideEffects": "none", "value": value}


def _failed(code: str, message: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "sideEffects": "none",
        "error": {"code": code, "message": message},
    }
