"""Automation task mutations (rules only; Core owns lease/dispatch/delivery)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import rules
from .store import TaskRuleStore


class TaskNotFound(ValueError):
    pass


class AutomationService:
    def __init__(self, store: TaskRuleStore):
        self.store = store

    # -- reads ---------------------------------------------------------
    def get_task(self, task_id: str) -> dict:
        task = self.store.get(task_id)
        if not task:
            raise TaskNotFound(f"Task '{task_id}' not found")
        return task

    def list_tasks(self, enabled_only: bool = False) -> list[dict]:
        return self.store.list(bool(enabled_only))

    # -- rules ---------------------------------------------------------
    def calculate_next_run(self, task: dict, from_time: str | None = None) -> str | None:
        moment = rules.parse_naive_local(from_time) if from_time else datetime.now()
        found = rules.calculate_next_run(task, moment)
        return found.isoformat() if found else None

    def validate_task(self, task: dict, origin: str = "user") -> dict:
        if not isinstance(task, dict):
            raise ValueError("task must be an object")
        checked = dict(task)
        if "schedule" in checked:
            rules.validate_schedule(checked["schedule"])
        if "action" in checked and not isinstance(checked["action"], dict):
            raise ValueError("Action must be an object")
        if "run_permission_mode" in checked or origin != "user":
            mode = rules.normalize_run_permission(checked.get("run_permission_mode"), origin=origin)
            if mode is None:
                checked.pop("run_permission_mode", None)
            else:
                checked["run_permission_mode"] = mode
        return checked

    def resolve_handler(self, task: dict) -> dict:
        if not isinstance(task, dict):
            raise ValueError("task must be an object")
        return rules.handler_plan(task)

    # -- mutations -----------------------------------------------------
    def create_task(self, task: dict, origin: str = "user") -> dict:
        return self.store.add(self.validate_task(task, origin))

    def update_task(self, task_id: str, patch: dict, resolved: dict | None = None,
                    origin: str = "user") -> dict:
        original = self.get_task(task_id)
        if original.get("linked_todo_id"):
            raise ValueError("请在关联事务中修改提醒时间和渠道")
        if not isinstance(patch, dict):
            raise ValueError("task update must be an object")
        if set(patch) - rules.UPDATE_FIELDS:
            raise ValueError("unsupported scheduler update fields")
        updates: dict[str, Any] = {k: patch[k] for k in ("name", "enabled", "schedule") if k in patch}
        if "schedule" in updates:
            rules.validate_schedule(updates["schedule"])
        if "run_permission_mode" in patch:
            updates["run_permission_mode"] = rules.normalize_run_permission(
                patch["run_permission_mode"], origin=origin)
        resolved = dict(resolved or {})
        if set(resolved) - {"action", "notification_route"}:
            raise ValueError("resolved may only carry action and notification_route")
        for key in ("action", "notification_route"):
            if key in resolved:
                updates[key] = rules.normalize_action(resolved[key]) if key == "action" else resolved[key]
        if "action" in patch and "action" not in resolved:
            raise ValueError("action updates must be resolved by the host")
        if "notification_route" in patch and "notification_route" not in resolved:
            raise ValueError("notification_route updates must be resolved by the host")
        if "schedule" in patch or "next_run_at" not in original:
            next_run = rules.calculate_next_run({**original, **updates}, datetime.now())
            if not next_run:
                raise ValueError("Cannot calculate next run time")
            updates["next_run_at"] = next_run.isoformat()
        return self.store.update(task_id, updates)

    def delete_task(self, task_id: str) -> dict:
        task = self.get_task(task_id)
        if task.get("linked_todo_id"):
            raise ValueError("请在关联事务中修改或删除提醒时间")
        self.store.delete(task_id)
        return task

    def enable_task(self, task_id: str, enabled: bool) -> dict:
        task = self.get_task(task_id)
        if task.get("linked_todo_id"):
            raise ValueError("请在关联事务中修改提醒时间")
        if type(enabled) is not bool:
            raise ValueError("enabled must be true or false")
        return self.store.update(task_id, {"enabled": enabled})
