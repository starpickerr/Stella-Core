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
        if write and method not in todos_gateway.TODOS_OUTBOX_METHODS:
            self._reconcile_host_scheduler(db_path, calendar_path)
        return result.get("value")

    @staticmethod
    def _reconcile_host_scheduler(db_path: Path, calendar_path: Path) -> None:
        """Apply pending reminder links via Core TaskStore + plugin link completion.

        Does not construct ``agent.todos.TodoService`` (avoids a dual domain writer).
        """
        if os.environ.get("STELLA_TODOS_PLUGIN_SCHEDULER_SYNC", "1").strip() in {"0", "false", "no"}:
            return
        try:
            import json
            from datetime import datetime, timezone

            from agent.todos.scheduler_link import default_scheduler_store, sync_task

            pending = todos_gateway.invoke_todos(
                "pending_scheduler_links",
                {},
                db_path=db_path,
                legacy_calendar_db_path=calendar_path,
            )
            if pending.get("status") != "succeeded" or not pending.get("value"):
                return
            store = default_scheduler_store()
            now = datetime.now(timezone.utc)
            for link in pending["value"]:
                todo_id = link["todo_id"]
                desired = link.get("desired_at")
                title = link.get("title") or ""
                remind_at = link.get("remind_at")
                status = link.get("status") or ""
                route_raw = link.get("reminder_delivery")
                route = json.loads(route_raw) if route_raw else None
                active = bool(
                    remind_at
                    and desired
                    and remind_at == desired
                    and status not in {"completed", "cancelled"}
                )
                if active and link.get("source_type") == "apple_reminders":
                    active = False
                if active:
                    try:
                        instant = datetime.fromisoformat(str(remind_at).replace("Z", "+00:00"))
                        if instant.tzinfo is None or instant <= now:
                            active = False
                    except ValueError:
                        active = False
                try:
                    sync_task(store, todo_id, title, desired if active else None, route)
                    todos_gateway.invoke_todos(
                        "complete_scheduler_link",
                        {
                            "todo_id": todo_id,
                            "desired_at": desired,
                            "outcome": "synced" if active else "cleared",
                        },
                        db_path=db_path,
                        legacy_calendar_db_path=calendar_path,
                    )
                except Exception as link_exc:
                    todos_gateway.invoke_todos(
                        "complete_scheduler_link",
                        {
                            "todo_id": todo_id,
                            "desired_at": desired,
                            "outcome": "error",
                            "error": str(link_exc),
                        },
                        db_path=db_path,
                        legacy_calendar_db_path=calendar_path,
                    )
        except Exception as exc:  # reminder sync is retried on the next write
            logger.warning("[Todos] host scheduler reconcile deferred: %s", exc)
