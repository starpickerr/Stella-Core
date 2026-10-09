"""Shared scheduler write boundary for Agent and desktop clients."""

from __future__ import annotations

from datetime import datetime

from agent.scheduler.conversation import validate_conversation_action
from agent.scheduler.delivery import destination_catalog, normalize_notification_route, patch_destination


class SchedulerMutations:
    def __init__(self, store):
        self.store = store

    def destinations(self, agent_id=None):
        return destination_catalog(agent_id)

    def get(self, task_id):
        task = self.store.get_task(task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found")
        return task

    def list(self):
        return self.store.list_tasks()

    @staticmethod
    def _route_action(action, route, agent_id=None):
        normalized = normalize_notification_route(route, agent_id)
        primary = normalized["primary"]
        if primary is None:
            raise ValueError("An explicit notification route requires a primary recipient")
        action = patch_destination(action, primary, agent_id)
        if action.get("channel_type") != "web":
            for field in ("conversation_mode", "source_session_id", "conversation_space", "execution_project_dir"):
                action.pop(field, None)
        return validate_conversation_action(action), normalized

    def create(self, task, *, notification_route=None, agent_id=None):
        task = dict(task)
        if notification_route is not None:
            action, route = self._route_action(task.get("action") or {}, notification_route, agent_id)
            task["action"] = action
            task["notification_route"] = route
        self.store.add_task(task)
        return task

    def update(self, task_id, patch, *, agent_id=None):
        original = self.get(task_id)
        if original.get("linked_todo_id"):
            raise ValueError("请在关联事务中修改提醒时间和渠道")
        if not isinstance(patch, dict):
            raise ValueError("task update must be an object")
        allowed = {"name", "enabled", "schedule", "action", "notification_route"}
        if set(patch) - allowed:
            raise ValueError("unsupported scheduler update fields")
        updates = {key: patch[key] for key in ("name", "enabled", "schedule") if key in patch}
        if "action" in patch:
            if not isinstance(patch["action"], dict):
                raise ValueError("Action must be an object")
            action = patch_destination(original.get("action") or {}, patch["action"], agent_id)
        else:
            action = dict(original.get("action") or {})
        if "notification_route" in patch:
            action, route = self._route_action(action, patch["notification_route"], agent_id)
            updates["notification_route"] = route
        elif "action" in patch and any(
                field in patch["action"] and action.get(field) != (original.get("action") or {}).get(field)
                for field in ("channel_type", "receiver", "receive_id_type", "is_group")):
            # The older editor sends destination fields inside action. Its
            # channel change is an explicit primary choice, never permission
            # to keep a previously configured backup.
            updates["notification_route"] = normalize_notification_route({"primary": action}, agent_id)
        if "action" in patch or "notification_route" in patch:
            if (action.get("conversation_mode") == "source" and
                    action.get("source_session_id") != (original.get("action") or {}).get("source_session_id")):
                action.pop("conversation_space", None)
                action.pop("execution_project_dir", None)
            if action.get("channel_type") != "web":
                for field in ("conversation_mode", "source_session_id", "conversation_space", "execution_project_dir"):
                    action.pop(field, None)
            action = validate_conversation_action(action)
            if action.get("type") == "send_message":
                action.pop("task_description", None)
                action.pop("silent", None)
            elif action.get("type") == "agent_task":
                action.pop("content", None)
            updates["action"] = action
        if "schedule" in patch or "next_run_at" not in original:
            from agent.scheduler import SchedulerService
            merged = {**original, **updates}
            next_run = SchedulerService(self.store, lambda _task: None)._calculate_next_run(merged, datetime.now())
            if not next_run:
                raise ValueError("Cannot calculate next run time")
            updates["next_run_at"] = next_run.isoformat()
        self.store.update_task(task_id, updates)
        return self.get(task_id)

    def delete(self, task_id):
        task = self.get(task_id)
        if task.get("linked_todo_id"):
            raise ValueError("请在关联事务中修改或删除提醒时间")
        self.store.delete_task(task_id)
        return task

    def enable(self, task_id, enabled):
        task = self.get(task_id)
        if task.get("linked_todo_id"):
            raise ValueError("请在关联事务中修改提醒时间")
        if type(enabled) is not bool:
            raise ValueError("enabled must be true or false")
        self.store.enable_task(task_id, enabled)
        return self.get(task_id)
