"""Shared scheduler write boundary for Agent and desktop clients."""

from __future__ import annotations

from datetime import datetime

from agent.scheduler.conversation import validate_conversation_action
from agent.scheduler.delivery import (DESTINATION_FIELDS, destination_catalog, load_saved_route,
                                      normalize_notification_route, patch_destination, same_notification_route)


_EXPLICIT_RUN_MODES = {"read-only", "workspace-write", "full-access"}


def normalize_run_permission(value, *, origin):
    """Return a stored mode, or None when the task should inherit.

    Only a trusted user action may store an explicit mode. Agent-origin
    calls that try to set one are refused instead of silently dropped.
    """
    if value is None or value == "" or value == "inherit":
        return None
    if value not in _EXPLICIT_RUN_MODES:
        raise ValueError("invalid run permission mode")
    if origin != "user":
        raise ValueError("只有用户可以设置定时任务的运行权限")
    return value


class SchedulerMutations:
    def __init__(self, store):
        self.store = store

    def destinations(self, agent_id=None):
        return destination_catalog(agent_id)

    def test_send(self, route, *, agent_id=None):
        normalized = normalize_notification_route(route, agent_id)
        if normalized["primary"] is None:
            raise ValueError("A primary notification destination is required")
        from agent.scheduler.dispatch import dispatch_test_notification
        return dispatch_test_notification(normalized, agent_id=agent_id)

    def get(self, task_id):
        task = self.store.get_task(task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found")
        return self._with_delivery_status(task)

    def list(self):
        return [self._with_delivery_status(task) for task in self.store.list_tasks()]

    def _with_delivery_status(self, task):
        route = task.get("notification_route")
        if isinstance(route, dict):
            task = {**task, "notification_route": load_saved_route(route)}
        return {**task, "notification_delivery_status": self.store.latest_delivery(task["id"])} if hasattr(
            self.store, "latest_delivery") else task

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

    def create(self, task, *, notification_route=None, agent_id=None, origin="user"):
        task = dict(task)
        if "run_permission_mode" in task or origin != "user":
            mode = normalize_run_permission(task.get("run_permission_mode"), origin=origin)
            if mode is None:
                task.pop("run_permission_mode", None)
            else:
                task["run_permission_mode"] = mode
        if notification_route is not None:
            action, route = self._route_action(task.get("action") or {}, notification_route, agent_id)
            task["action"] = action
            task["notification_route"] = route
        self.store.add_task(task)
        return task

    def update(self, task_id, patch, *, agent_id=None, origin="user"):
        original = self.get(task_id)
        if original.get("linked_todo_id"):
            raise ValueError("请在关联事务中修改提醒时间和渠道")
        if not isinstance(patch, dict):
            raise ValueError("task update must be an object")
        allowed = {"name", "enabled", "schedule", "action", "notification_route", "run_permission_mode"}
        if set(patch) - allowed:
            raise ValueError("unsupported scheduler update fields")
        same_route = ("notification_route" in patch and
                      same_notification_route(patch["notification_route"], original.get("notification_route")))
        updates = {key: patch[key] for key in ("name", "enabled", "schedule") if key in patch}
        if "run_permission_mode" in patch:
            updates["run_permission_mode"] = normalize_run_permission(patch["run_permission_mode"], origin=origin)
        if "action" in patch:
            if not isinstance(patch["action"], dict):
                raise ValueError("Action must be an object")
            action_patch = ({key: value for key, value in patch["action"].items() if key not in DESTINATION_FIELDS}
                            if same_route else patch["action"])
            action = patch_destination(original.get("action") or {}, action_patch, agent_id)
        else:
            action = dict(original.get("action") or {})
        if "notification_route" in patch:
            submitted = patch["notification_route"]
            if isinstance(submitted, dict) and (
                    submitted.get("backup_enabled") is True or submitted.get("backup") not in (None,)):
                raise ValueError("备用渠道已移除")
            if same_route:
                route = load_saved_route(original.get("notification_route"))
            else:
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
