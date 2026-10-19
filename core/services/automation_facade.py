"""Compatibility facade: same surface as SchedulerMutations, task rules served by the plugin.

Host-only work stays here: destination catalog, test sends, notification-route
normalization, conversation-scope validation and delivery status (which reads
Core's lease/delivery tables). Everything else is a plugin call against the shared
``automation.db``. Stores without that database (legacy JSON ``TaskStore``) are not
served by the plugin; ``Application.scheduler`` keeps them on ``SchedulerMutations``.
"""

from __future__ import annotations

from typing import Any

from core.services import automation_gateway


def plugin_serves(store: Any) -> bool:
    """Only the SQLite AutomationStore shares automation.db with the plugin."""
    return bool(getattr(store, "store_path", None)) and bool(getattr(store, "agent_id", None))


class AutomationPluginFacade:
    def __init__(self, store: Any):
        if not plugin_serves(store):
            raise ValueError("automation plugin needs an AutomationStore (automation.db)")
        self.store = store
        from agent.scheduler.mutations import SchedulerMutations

        self._host = SchedulerMutations(store)  # destination/route helpers only

    # -- plugin plumbing ---------------------------------------------------
    def _call(self, method: str, **params: Any) -> Any:
        from pathlib import Path

        result = automation_gateway.invoke_automation(
            method, params, db_path=Path(self.store.store_path), agent_id=self.store.agent_id,
            owner_user_id=self.store._current_user())
        status = result.get("status")
        if status == "failed":
            err = result.get("error") or {}
            raise ValueError(err.get("message") or "automation plugin call failed")
        if status != "succeeded":
            raise RuntimeError(f"automation plugin returned {status}")
        return result.get("value")

    def _with_delivery_status(self, task: dict) -> dict:
        return self._host._with_delivery_status(task)

    # -- host-owned --------------------------------------------------------
    def destinations(self, agent_id=None):
        return self._host.destinations(agent_id)

    def test_send(self, route, *, agent_id=None):
        return self._host.test_send(route, agent_id=agent_id)

    # -- plugin-owned ------------------------------------------------------
    def get(self, task_id):
        return self._with_delivery_status(self._call("get_task", task_id=task_id))

    def list(self):
        return [self._with_delivery_status(task) for task in self._call("list_tasks", enabled_only=False)]

    def create(self, task, *, notification_route=None, agent_id=None, origin="user"):
        task = dict(task)
        if notification_route is not None:
            action, route = self._host._route_action(task.get("action") or {}, notification_route, agent_id)
            task["action"] = action
            task["notification_route"] = route
        self._call("create_task", task=task, origin=origin)
        return task

    def update(self, task_id, patch, *, agent_id=None, origin="user"):
        original = self._call("get_task", task_id=task_id)
        resolved: dict[str, Any] = {}
        if isinstance(patch, dict) and not original.get("linked_todo_id"):
            resolved = self._host.resolve_delivery_updates(original, patch, agent_id)
        self._call("update_task", task_id=task_id, patch=patch, resolved=resolved, origin=origin)
        return self.get(task_id)

    def delete(self, task_id):
        task = self.get(task_id)
        self._call("delete_task", task_id=task_id)
        return task

    def enable(self, task_id, enabled):
        self._call("enable_task", task_id=task_id, enabled=enabled)
        return self.get(task_id)
