"""Briefing owner: decisions, snapshots and outbox in one worker.

Peer business calls use the bound Core public channel and independent grants.
The worker receives its own data handle and public source references only.
"""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from peers import PeerService
from domain.actions import AdapterUnavailable, PeerOutcomeUnknown
from domain.models import EmailMessage, SourceItem
from domain.outbox import dispatch_pending
from domain.pipeline import BriefingPipeline
from domain.service import BriefingService
from domain.sources import available_sources, select_sources
from domain.store import get_briefing_store

CONTRACT = "stella.briefing@1"
R, W = "briefing.read", "briefing.write"

# name -> (effect, permission, idempotent, ordered parameter names)
METHODS: dict[str, tuple[str, str, bool, tuple[str, ...]]] = {
    # --- Application _METHODS["briefing"] (25) ---
    "list_briefings": ("query", R, False, ("status",)),
    "get_briefing": ("query", R, False, ("briefing_id",)),
    "get_revision": ("query", R, False, ("briefing_id", "number")),
    "briefing_for_date": ("query", R, False, ("briefing_date",)),
    "list_rules": ("query", R, False, ("enabled_only", "source")),
    "get_rule": ("query", R, False, ("rule_id",)),
    "get_cursor": ("query", R, False, ("source", "account_id", "cursor_key")),
    "build_source_item": ("query", R, False, ("payload",)),
    "list_action_rules": ("query", R, False, ()),
    "get_preferences": ("query", R, False, ()),
    "get_overview": ("query", R, False, ()),
    "get_action_targets": ("query", R, False, ("kind", "query")),
    "start_briefing": ("domainWrite", W, True, ("briefing_date", "title")),
    "complete_briefing": ("domainWrite", W, True, ("briefing_id", "payload")),
    "run_pipeline": ("domainWrite", W, False, ("briefing_date", "operation", "trigger", "sources", "draft", "run_at")),
    "update_item_status": ("domainWrite", W, True, ("item_id", "status")),
    "upsert_source_item": ("domainWrite", W, True, ("payload",)),
    "create_rule": ("domainWrite", W, True, ("payload",)),
    "update_rule": ("domainWrite", W, True, ("rule_id", "payload")),
    "delete_rule": ("domainWrite", W, True, ("rule_id",)),
    "set_cursor": ("domainWrite", W, True, ("source", "cursor_key", "cursor_value", "account_id")),
    "update_action": ("domainWrite", W, True, ("item_id", "payload")),
    "create_action_rule": ("domainWrite", W, True, ("payload",)),
    "delete_action_rule": ("domainWrite", W, True, ("rule_id",)),
    "update_preferences": ("domainWrite", W, True, ("payload",)),
    # --- Plugin extensions used by the host pipeline / source selection ---
    "list_revisions": ("query", R, False, ("briefing_id",)),
    "window_candidates": ("query", R, False, ("start", "end", "accounts")),
    "staged_window_candidates": ("query", R, False, ("run_id", "start", "end", "accounts")),
    "list_sources": ("query", R, False, ()),
    "select_sources": ("query", R, False, ("selectors",)),
    "stage_source_items": ("domainWrite", W, True, ("run_id", "rows")),
    "stage_source_errors": ("domainWrite", W, True, ("run_id", "source", "account_id", "errors")),
    "dispatch_outbox": ("domainWrite", W, False, ("limit",)),
}

BRIEFING_APPLICATION_METHODS = tuple(list(METHODS)[:25])

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


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _pair(row) -> dict[str, Any]:
    item, email = row
    return {"item": _jsonable(item), "email": _jsonable(email) if email is not None else None}


def _service(invoke_params: dict[str, Any]) -> BriefingService:
    handle = invoke_params.get("_hostDataHandle") or {}
    db_path = handle.get("dbPath")
    if not db_path:
        raise RuntimeError("host data handle with dbPath required")
    return BriefingService(get_briefing_store(Path(db_path)), PeerService('todo'), PeerService('calendar'))


def _sources(invoke_params: dict[str, Any]) -> list[dict]:
    handle = invoke_params.get("_hostDataHandle") or {}
    return available_sources(handle.get("sourceDirectory"))


def _staged_rows(rows) -> list[tuple[SourceItem, EmailMessage | None]]:
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("item"), dict):
            raise ValueError("each staged row needs an item object")
        email = row.get("email")
        result.append((SourceItem(**row["item"]), EmailMessage(**email) if email else None))
    return result


def _accounts(accounts) -> list[tuple[str, str]]:
    if not isinstance(accounts, list) or any(not isinstance(a, (list, tuple)) or len(a) != 2 for a in accounts):
        raise ValueError("accounts must be a list of [source, account_id] pairs")
    return [(a[0], a[1]) for a in accounts]


def _dispatch(svc: BriefingService, method: str, params: dict[str, Any], invoke_params: dict[str, Any]) -> Any:
    store = svc.store
    if method == "upsert_source_item" or method == "build_source_item":
        return _pair(getattr(svc, method)(**params))
    if method in {"delete_rule", "delete_action_rule"}:
        getattr(svc, method)(**params)
        return {"deleted": True, "id": params["rule_id"]}
    if method == "list_revisions":
        return store.list_revisions(params["briefing_id"])
    if method == "window_candidates":
        return [_pair(r) for r in store.window_candidates(
            params["start"], params["end"], _accounts(params["accounts"]))]
    if method == "staged_window_candidates":
        return [_pair(r) for r in store.staged_window_candidates(
            params["run_id"], params["start"], params["end"], _accounts(params["accounts"]))]
    if method == "stage_source_items":
        rows = _staged_rows(params["rows"])
        store.stage_source_items(params["run_id"], rows)
        return {"staged": len(rows)}
    if method == "stage_source_errors":
        store.stage_source_errors(params["run_id"], params["source"], params.get("account_id") or "default",
                                  list(params["errors"]))
        return {"staged": True}
    if method == "list_sources":
        return _sources(invoke_params)
    if method == "select_sources":
        return select_sources(_sources(invoke_params), params.get("selectors"))
    if method == "dispatch_outbox":
        return dispatch_pending(store, int(params.get("limit") or 20), svc._todos, svc._calendar)
    if method == "run_pipeline":
        return BriefingPipeline(svc).run(
            briefing_date=params.get("briefing_date"), operation=params.get("operation") or "upsert",
            trigger=params.get("trigger") or "manual", sources=params.get("sources"), draft=params.get("draft"),
            run_at=params.get("run_at"))
    return getattr(svc, method)(**params)


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
        value = _jsonable(_dispatch(svc, method, params, invoke_params))
    except PeerOutcomeUnknown:
        return {'status':'unknown','sideEffects':'unknown','operationId':invoke_params.get('idempotencyKey') or method}
    except AdapterUnavailable as exc:
        return _fail("unsupported", str(exc))
    except PermissionError as exc:
        return _fail('permission_denied', str(exc))
    except KeyError as exc:
        return _fail("not_found", str(exc.args[0]) if exc.args else "not found")
    except sqlite3.IntegrityError as exc:
        return _fail("conflict", str(exc))
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
