"""Pure task rules: run permission, schedule evaluation, action shape, handler plan."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from .cron import next_cron

EXPLICIT_RUN_MODES = {"read-only", "workspace-write", "full-access"}
ACTION_TYPES = ("agent_task", "send_message", "tool_call", "skill_call", "application_command")
SILENT_CAPABLE = ("agent_task", "tool_call", "skill_call")
UPDATE_FIELDS = {"name", "enabled", "schedule", "action", "notification_route", "run_permission_mode"}
SCHEDULE_TYPES = ("cron", "interval", "once")


def normalize_run_permission(value: Any, *, origin: str) -> Optional[str]:
    """Return a stored mode, or None when the task should inherit.

    Only a trusted user action may store an explicit mode. Agent-origin calls
    that try to set one are refused instead of silently dropped.
    """
    if value is None or value == "" or value == "inherit":
        return None
    if value not in EXPLICIT_RUN_MODES:
        raise ValueError("invalid run permission mode")
    if origin != "user":
        raise ValueError("只有用户可以设置定时任务的运行权限")
    return value


def parse_naive_local(iso_str: str) -> datetime:
    """Parse an ISO datetime and coerce it to tz-naive local time."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def calculate_next_run(task: dict, from_time: datetime) -> Optional[datetime]:
    """Next run for cron / interval / once schedules; None when there is none."""
    schedule = task.get("schedule") or {}
    kind = schedule.get("type")
    if kind == "cron":
        expression = schedule.get("expression")
        if not expression:
            return None
        try:
            return next_cron(expression, from_time)
        except ValueError:
            return None
    if kind == "interval":
        seconds = schedule.get("seconds", 0)
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds <= 0:
            return None
        return from_time + timedelta(seconds=seconds)
    if kind == "once":
        run_at = schedule.get("run_at")
        if not run_at:
            return None
        try:
            moment = parse_naive_local(run_at)
        except (TypeError, ValueError):
            return None
        return moment if moment > from_time else None
    return None


def validate_schedule(schedule: Any) -> dict:
    if not isinstance(schedule, dict) or schedule.get("type") not in SCHEDULE_TYPES:
        raise ValueError("schedule.type must be cron, interval or once")
    if schedule["type"] == "cron":
        from .cron import CronExpression

        CronExpression(schedule.get("expression"))
    elif schedule["type"] == "interval":
        seconds = schedule.get("seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds <= 0:
            raise ValueError("schedule.seconds must be a positive number")
    else:
        try:
            parse_naive_local(str(schedule.get("run_at")))
        except ValueError:
            raise ValueError("schedule.run_at must be an ISO datetime") from None
    return schedule


def normalize_action(action: Any) -> dict:
    """Shape rules for a stored action; destination/conversation checks stay in the host."""
    if not isinstance(action, dict):
        raise ValueError("Action must be an object")
    action = dict(action)
    kind = action.get("type")
    if kind == "send_message":
        action.pop("task_description", None)
        action.pop("silent", None)
    elif kind == "agent_task":
        action.pop("content", None)
    return action


def handler_plan(task: dict) -> dict[str, Any]:
    """Classify one due task for the host dispatcher (execution stays in Core)."""
    action = task.get("action") or {}
    kind = action.get("type")
    silent = kind == "application_command" or (kind in SILENT_CAPABLE and bool(action.get("silent", False)))
    persist = "conversation_mode" in action
    valid = kind in ACTION_TYPES
    return {
        "valid": valid, "handler": kind, "silent": silent, "persist_in_chat": persist,
        "needs_channel_ready": not silent and not task.get("notification_route") and not persist,
        "channel_type": action.get("channel_type", "unknown"), "receiver": action.get("receiver", ""),
        "error": "" if valid else f"Unknown action type: {kind}",
    }
