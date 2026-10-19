"""Compatibility facade: same method surface as TodoService, routed to plugin RPC."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from core.services import todos_gateway

logger = logging.getLogger(__name__)


def _db_paths() -> tuple[Path, Path]:
    from common.state_dir import calendar_db, todos_db

    return todos_db(), calendar_db(ensure=False)


def _wire_value(name: str, value: Any) -> Any:
    """Make host objects JSON-safe for the plugin boundary."""
    if isinstance(value, datetime):
        return value.isoformat()
    if name == "detail" and isinstance(value, dict) and "briefing" in value:
        briefing = value["briefing"]
        briefing_id = briefing["id"] if isinstance(briefing, dict) else briefing.id
        return {"briefing": {"id": briefing_id}}
    return value


class TodosPluginFacade:
    """Drop-in for Application._Port when STELLA_TODOS_PLUGIN is enabled."""

    def __getattr__(self, name: str):
        names = todos_gateway.TODOS_METHOD_PARAMS.get(name)
        if names is None or name == "pending_scheduler_links":
            raise AttributeError(name)

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
            params = {key: _wire_value(key, value) for key, value in params.items()}
            write = name in todos_gateway.TODOS_WRITE_METHODS
            value = self._value(name, params, write=write)
            if name == "delete_todo":
                return None
            if name == "sync_briefing_facts":
                return tuple(value)
            return value

        call.__name__ = name
        return call

    def _value(self, method: str, params: dict[str, Any], *, write: bool = False) -> Any:
        db_path, calendar_path = _db_paths()
        result = todos_gateway.invoke_todos(
            method, params, db_path=db_path, legacy_calendar_db_path=calendar_path
        )
        status = result.get("status")
        if status == "failed":
            err = result.get("error") or {}
            message = err.get("message") or "todos plugin call failed"
            if err.get("code") == "not_found":
                raise KeyError(message)
            raise ValueError(message)
        if status != "succeeded":
            raise RuntimeError(f"todos plugin returned {status}")
        if write:
            self._reconcile_host_scheduler(db_path, calendar_path)
        return result.get("value")

    @staticmethod
    def _reconcile_host_scheduler(db_path: Path, calendar_path: Path) -> None:
        """The worker cannot reach the host scheduler; apply pending reminder links here."""
        if os.environ.get("STELLA_TODOS_PLUGIN_SCHEDULER_SYNC", "1").strip() in {"0", "false", "no"}:
            return
        try:
            pending = todos_gateway.invoke_todos(
                "pending_scheduler_links", {}, db_path=db_path, legacy_calendar_db_path=calendar_path
            )
            if pending.get("status") != "succeeded" or not pending.get("value"):
                return
            from agent.todos.scheduler_link import default_scheduler_store
            from agent.todos.service import TodoService

            TodoService(
                db_path=db_path,
                legacy_calendar_db_path=calendar_path,
                scheduler_store=default_scheduler_store(),
            )._sync_scheduler_links()
        except Exception as exc:  # reminder sync is retried on the next write
            logger.warning("[Todos] host scheduler reconcile deferred: %s", exc)
