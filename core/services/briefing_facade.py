"""Core compatibility types over the Briefing owner service; no domain writes."""

from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from core.services import briefing_gateway

_RUN_LOCKS: dict[str, threading.Lock] = {}
_RUN_LOCKS_GUARD = threading.Lock()


def _db_path() -> Path:
    from common.state_dir import briefing_db

    return briefing_db()


def _models():
    from agent.briefing import models

    return models


def _briefing(row):
    return None if row is None else _models().Briefing(**row)


def _item(row):
    return _models().BriefingItem(**row)


def _rule(row):
    return None if row is None else _models().FilterRule(**row)


def _cursor(row):
    return None if row is None else _models().SyncCursor(**row)


def _pair(row):
    models = _models()
    email = models.EmailMessage(**row["email"]) if row.get("email") else None
    return models.SourceItem(**row["item"]), email


def _detail(detail):
    if detail is None:
        return None
    detail = dict(detail)
    detail["briefing"] = _briefing(detail["briefing"])
    detail["items"] = [_item(row) for row in detail["items"]]
    return detail


def _overview(value):
    return {**value, "items": [_item(row) for row in value["items"]]}


_RESULT = {
    "list_briefings": lambda v: [_briefing(row) for row in v],
    "get_briefing": _detail,
    "briefing_for_date": _briefing,
    "start_briefing": _briefing,
    "complete_briefing": _detail,
    "update_item_status": _item,
    "list_rules": lambda v: [_rule(row) for row in v],
    "get_rule": _rule,
    "create_rule": _rule,
    "update_rule": _rule,
    "get_cursor": _cursor,
    "set_cursor": _cursor,
    "upsert_source_item": _pair,
    "build_source_item": _pair,
    "get_overview": _overview,
    "delete_rule": lambda v: None,
    "delete_action_rule": lambda v: None,
}

# Methods the Application port exposes (Application._METHODS["briefing"]).
APPLICATION_METHODS = frozenset({
    "list_briefings", "get_briefing", "get_revision", "start_briefing", "briefing_for_date",
    "complete_briefing", "update_item_status", "upsert_source_item", "list_rules",
    "get_rule", "create_rule", "update_rule", "delete_rule", "get_cursor", "set_cursor",
    "build_source_item", "update_action", "list_action_rules", "create_action_rule", "delete_action_rule",
    "get_preferences", "update_preferences", "get_action_targets", "get_overview",
})


class BriefingPluginError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _call(method: str, params: dict[str, Any]) -> Any:
    result = briefing_gateway.invoke_briefing(method, params, db_path=_db_path())
    status = result.get("status")
    if status == "failed":
        err = result.get("error") or {}
        message = err.get("message") or "briefing plugin call failed"
        code = err.get("code")
        if code == "not_found":
            raise KeyError(message)
        if code in {"invalid_argument", "conflict"}:
            raise ValueError(message)
        raise BriefingPluginError(code or "failed", message)
    if status != "succeeded":
        raise RuntimeError(f"briefing plugin returned {status}")
    return result.get("value")


def _wire(value: Any) -> Any:
    """Make host objects (dataclasses, tuples) JSON-safe for the plugin boundary."""
    if hasattr(value, "__dataclass_fields__") and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    return value


class _StoreProxy:
    """The slice of BriefingStore the Core pipeline uses, served by the plugin."""

    def __init__(self):
        key = str(_db_path().resolve())
        with _RUN_LOCKS_GUARD:
            self.run_lock = _RUN_LOCKS.setdefault(key, threading.Lock())

    def list_revisions(self, briefing_id):
        return _call("list_revisions", {"briefing_id": briefing_id})

    def get_revision(self, briefing_id, number):
        try:
            return _call("get_revision", {"briefing_id": briefing_id, "number": number})
        except KeyError:
            return None

    def window_candidates(self, start, end, accounts):
        rows = _call("window_candidates", {"start": start, "end": end, "accounts": _wire(accounts)})
        return [_pair(row) for row in rows]

    def staged_window_candidates(self, run_id, start, end, accounts):
        rows = _call("staged_window_candidates", {
            "run_id": run_id, "start": start, "end": end, "accounts": _wire(accounts)})
        return [_pair(row) for row in rows]

    def stage_source_items(self, run_id, rows):
        wired = [{"item": _wire(item), "email": _wire(email) if email else None} for item, email in rows]
        _call("stage_source_items", {"run_id": run_id, "rows": wired})

    def stage_source_errors(self, run_id, source, account_id, errors):
        _call("stage_source_errors", {
            "run_id": run_id, "source": source, "account_id": account_id, "errors": list(errors)})

    def dispatch_outbox(self, limit=20):
        return _call('dispatch_outbox', {'limit': limit})


class BriefingPluginFacade:
    """Drop-in for Application._Port when STELLA_BRIEFING_PLUGIN is enabled."""

    @property
    def store(self):
        return _StoreProxy()

    def __getattr__(self, name: str):
        if name not in APPLICATION_METHODS:
            raise AttributeError(name)
        names = briefing_gateway.BRIEFING_METHOD_PARAMS[name]

        def call(*args: Any, **kwargs: Any) -> Any:
            if len(args) > len(names):
                raise TypeError(f"{name}() takes at most {len(names)} arguments")
            params = dict(zip(names, args))
            for key, value in kwargs.items():
                if key not in names:
                    raise TypeError(f"{name}() got an unexpected keyword argument {key!r}")
                if key in params:
                    raise TypeError(f"{name}() got multiple values for argument {key!r}")
                params[key] = value
            params = {key: _wire(value) for key, value in params.items()}
            value = _call(name, params)
            convert = _RESULT.get(name)
            return convert(value) if convert else value

        call.__name__ = name
        return call
