"""Agent and desktop notification configuration must agree on persisted routes."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.scheduler import delivery
from agent.scheduler.store import TaskStore
from agent.todos import TodoService
from agent.tools.scheduler.scheduler_tool import SchedulerTool
from agent.tools.todos.todos_tool import TodosTool


class _Context(dict):
    kwargs = {}


@pytest.fixture
def channels(monkeypatch):
    available = {
        "feishu": SimpleNamespace(),
        "weixin": SimpleNamespace(login_status="logged_in", _context_tokens={"wx_user": "private-token"}),
    }
    monkeypatch.setattr(delivery, "runtime_channel", available.get)
    return available


def _todo_tool(tmp_path):
    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    service = TodoService(tmp_path / "todos.db", tmp_path / "calendar.db", scheduler_store=store)
    return TodosTool(service=service), store


def _scheduler_tool(tmp_path):
    tool = SchedulerTool({"channel_type": "feishu"})
    tool.task_store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    tool.current_context = _Context(receiver="ou_origin", session_id="source_chat", isgroup=False)
    return tool


def _future():
    return (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0).isoformat()


def _route(channel, receiver, *, backup=None, enabled=False):
    return {"primary": {"channel_type": channel, "receiver": receiver},
            "backup_enabled": enabled, "backup": backup}


def test_agent_creates_queries_and_changes_todo_reminder_without_duplicate_task(tmp_path, channels):
    tool, store = _todo_tool(tmp_path)
    reminder = _future()
    created = tool.execute({"action": "create", "title": "Submit homework", "remind_at": reminder,
                            "reminder_delivery": _route("weixin", "wx_user")})
    assert created.status == "success"
    todo = json.loads(created.result)["todo"]
    assert todo["reminder_delivery"]["primary"]["channel_type"] == "weixin"
    changed = tool.execute({"action": "update", "id": todo["id"],
                            "reminder_delivery": _route("feishu", "ou_student")})
    assert changed.status == "success"
    stored = json.loads(tool.execute({"action": "get", "id": todo["id"]}).result)["todo"]
    assert stored["reminder_delivery"]["primary"]["receiver"] == "ou_student"
    assert stored["reminder_delivery"]["backup_enabled"] is False
    assert len(store.list_tasks()) == 1
    assert store.get_task(todo["scheduler_task_id"])["reminder_delivery"] == stored["reminder_delivery"]


def test_agent_rejects_unresolved_todo_recipient(tmp_path, channels):
    tool, store = _todo_tool(tmp_path)
    result = tool.execute({"action": "create", "title": "Submit", "remind_at": _future(),
                           "reminder_delivery": _route("feishu", "")})
    assert result.status == "error" and "recipient" in result.result
    assert store.list_tasks() == []


def test_agent_scheduler_route_create_backup_change_and_disable(tmp_path, channels):
    tool = _scheduler_tool(tmp_path)
    created = tool.execute({"action": "create", "name": "Morning", "message": "Get ready",
                            "schedule_type": "once", "schedule_value": _future(),
                            "notification_route": _route("weixin", "wx_user")})
    assert created.status == "success"
    task = tool.task_store.list_tasks()[0]
    assert task["notification_route"]["primary"]["channel_type"] == "weixin"
    assert task["notification_route"]["backup_enabled"] is False
    enabled = tool.execute({"action": "update", "task_id": task["id"],
                            "notification_route": _route("weixin", "wx_user", enabled=True,
                                backup={"channel_type": "feishu", "receiver": "ou_backup"})})
    assert enabled.status == "success"
    assert tool.task_store.get_task(task["id"])["notification_route"]["backup"]["receiver"] == "ou_backup"
    disabled = tool.execute({"action": "update", "task_id": task["id"],
                             "notification_route": _route("weixin", "wx_user")})
    assert disabled.status == "success"
    assert tool.task_store.get_task(task["id"])["notification_route"]["backup"] is None
    assert len(tool.task_store.list_tasks()) == 1


def test_agent_scheduler_only_feishu_and_unresolved_recipient(tmp_path, channels):
    tool = _scheduler_tool(tmp_path)
    invalid = tool.execute({"action": "create", "name": "Invalid", "message": "Hello",
                            "schedule_type": "once", "schedule_value": _future(),
                            "notification_route": _route("feishu", "")})
    assert invalid.status == "error"
    assert tool.task_store.list_tasks() == []
    result = tool.execute({"action": "create", "name": "Only Feishu", "message": "Hello",
                           "schedule_type": "once", "schedule_value": _future(),
                           "notification_route": _route("feishu", "ou_student")})
    assert result.status == "success"
    task = tool.task_store.list_tasks()[0]
    assert task["notification_route"]["backup_enabled"] is False
    assert task["notification_route"]["backup"] is None
    assert "private-token" not in str(task)


def test_scheduler_tool_exposes_destination_catalog_and_validation_failure(tmp_path, channels, monkeypatch):
    tool = _scheduler_tool(tmp_path)
    monkeypatch.setattr(delivery, "web_sessions", lambda *_: [])
    monkeypatch.setattr("config.conf", lambda: {"channel_type": "feishu,weixin"})
    result = tool.execute({"action": "destinations"})
    assert result.status == "success"
    assert "wx_user" in result.result
    assert "private-token" not in result.result
    assert tool.execute({"action": "create", "name": "Missing content",
                         "schedule_type": "once", "schedule_value": _future()}).status == "error"


def test_desktop_scheduler_uses_same_route_update_contract(tmp_path, channels, monkeypatch):
    from channel.desktop import desktop_channel as desktop
    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    monkeypatch.setattr(desktop, "_scheduler_store", lambda: store)
    monkeypatch.setattr(desktop, "_require_auth", lambda: None)
    monkeypatch.setattr(desktop.web, "header", lambda *_args: None)
    create = {"name": "Only Feishu", "schedule": {"type": "once", "run_at": _future()},
              "session_id": "source_chat", "action": {"type": "send_message", "content": "Hello",
              "channel_type": "feishu", "receiver": "ou_origin"},
              "notification_route": _route("feishu", "ou_student")}
    with patch.object(desktop.web, "data", return_value=json.dumps(create).encode()):
        response = json.loads(desktop.SchedulerHandler().POST())
    assert response["status"] == "success"
    task_id = response["task"]["id"]
    assert response["task"]["notification_route"]["primary"]["receiver"] == "ou_student"
    update = {"task_id": task_id, "notification_route": _route("weixin", "wx_user")}
    with patch.object(desktop.web, "data", return_value=json.dumps(update).encode()):
        response = json.loads(desktop.SchedulerUpdateHandler().POST())
    assert response["status"] == "success"
    assert store.get_task(task_id)["action"]["channel_type"] == "weixin"
    assert len(store.list_tasks()) == 1


def test_legacy_action_edit_resets_stale_backup_route(tmp_path, channels):
    from application import Application
    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    service = Application.scheduler(store)
    task = {"id": "legacy", "name": "Legacy", "enabled": True,
            "schedule": {"type": "once", "run_at": _future()}, "next_run_at": _future(),
            "action": {"type": "send_message", "content": "Hello", "channel_type": "weixin",
                       "receiver": "wx_user", "execution_session_id": "source_chat"}}
    service.create(task, notification_route=_route("weixin", "wx_user", enabled=True,
        backup={"channel_type": "feishu", "receiver": "ou_backup"}))
    updated = service.update("legacy", {"action": {"channel_type": "feishu", "receiver": "ou_student"}})
    assert updated["notification_route"]["primary"]["receiver"] == "ou_student"
    assert updated["notification_route"]["backup_enabled"] is False
    assert updated["notification_route"]["backup"] is None


def test_agent_scheduler_missing_task_is_tool_failure(tmp_path, channels):
    tool = _scheduler_tool(tmp_path)
    for action in ("get", "delete", "enable", "disable", "update"):
        result = tool.execute({"action": action, "task_id": "missing",
                               "notification_route": _route("feishu", "ou_student")})
        assert result.status == "error"
