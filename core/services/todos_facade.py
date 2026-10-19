"""Tasks port facade: the stella.tasks method surface, routed to plugin RPC."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from core.services import todos_gateway

from common.log import logger


def _db_paths() -> tuple[Path, Path]:
    from common.state_dir import calendar_db, todos_db

    return todos_db(), calendar_db(ensure=False)


def _wire_value(name: str, value: Any) -> Any:
    """Make host objects JSON-safe for the plugin boundary."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(value)
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
            briefing_key = kwargs.pop("_briefing_key", None) if name == "create_todo" else None
            if len(args) > len(names):
                raise TypeError(f"{name}() takes at most {len(names)} arguments")
            params = dict(zip(names, args))
            for key, value in kwargs.items():
                if key not in names:
                    raise TypeError(f"{name}() got an unexpected keyword argument {key!r}")
                if key in params:
                    raise TypeError(f"{name}() got multiple values for argument {key!r}")
                params[key] = value
            if name == 'create_todo' and isinstance(params.get('payload'), dict):
                if {'_briefing_key', '_external_source_key'} & set(params['payload']):
                    raise ValueError('reserved Tasks source fields are not allowed in public payloads')
            if briefing_key:
                params["payload"] = {**params.get("payload", {}), "_briefing_key": briefing_key}
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

    def _value(self, method: str, params: dict[str, Any], *, write: bool = False, reconcile: bool = True) -> Any:
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
        value = result.get("value")
        if reconcile and ((write and method not in todos_gateway.TODOS_OUTBOX_METHODS) or
                          method in {'get_todo', 'list_todos', 'list_todos_focus'}):
            reconciled = self._reconcile_host_scheduler(db_path, calendar_path)
            # The plugin answered before the host applied scheduler links; re-read so
            # reminder_sync_pending / reminder_sync_error reflect the actual outcome.
            if not write and reconciled:
                value = self._value(method, params, reconcile=False)
            elif isinstance(value, dict) and value.get("id") in reconciled:
                value = self._value("get_todo", {"todo_id": value["id"]}, reconcile=False)
        return value

    def reconcile_scheduler_links(self) -> set[str]:
        """Repair pending projections without creating a new business request."""
        return self._reconcile_host_scheduler(*_db_paths())

    @staticmethod
    def _reconcile_host_scheduler(db_path: Path, calendar_path: Path) -> set[str]:
        """Apply pending reminder links via Core TaskStore + plugin link completion.

        Returns the todo ids whose link state changed.

        """
        changed = set()
        if os.environ.get("STELLA_TODOS_PLUGIN_SCHEDULER_SYNC", "1").strip() in {"0", "false", "no"}:
            return changed
        from core.plugins.caller import plugin_user_id
        from core.plugins.locks import package_lock
        from core.plugins.management import default_store

        # Business writes may proceed while projection runs, but pending read,
        # Core task update and plugin receipt must be one serialized operation.
        # A separate lease avoids blocking unrelated plugin business requests.
        try:
            with package_lock(default_store().root,
                              'stella.tasks:reminder-projection:' + plugin_user_id(), exclusive=True):
                return TodosPluginFacade._project_scheduler_links(db_path, calendar_path)
        except Exception as exc:
            logger.warning('[Todos] host scheduler reconcile deferred: %s', exc)
            return changed

    @staticmethod
    def _project_scheduler_links(db_path: Path, calendar_path: Path) -> set[str]:
        changed = set()
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
            if pending.get('status') != 'succeeded':
                logger.warning('[Todos] Reminder projection unavailable: %s', (pending.get('error') or {}).get('message', 'plugin unavailable'))
                return changed
            if not pending.get('value'):
                return changed
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
                if active:
                    try:
                        instant = datetime.fromisoformat(str(remind_at).replace("Z", "+00:00"))
                        if instant.tzinfo is None or instant <= now:
                            active = False
                    except ValueError:
                        active = False
                try:
                    sync_task(store, todo_id, title, desired if active else None, route)
                    receipt = todos_gateway.invoke_todos(
                        "complete_scheduler_link",
                        {
                            "todo_id": todo_id,
                            "desired_at": desired,
                            "outcome": "synced" if active else "cleared",
                        },
                        db_path=db_path,
                        legacy_calendar_db_path=calendar_path,
                    )
                    if receipt.get('status') != 'succeeded':
                        raise RuntimeError((receipt.get('error') or {}).get('message') or 'scheduler receipt rejected')
                    changed.add(todo_id)
                except Exception as link_exc:
                    receipt = todos_gateway.invoke_todos(
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
                    if receipt.get('status') == 'succeeded':
                        changed.add(todo_id)
        except Exception as exc:  # pending projection is retried on reads and scheduler ticks
            logger.warning("[Todos] host scheduler reconcile deferred: %s", exc)
        return changed
