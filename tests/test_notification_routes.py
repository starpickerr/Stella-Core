"""Agent and desktop notification configuration must agree on persisted routes."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.scheduler import delivery
from agent.scheduler.store import TaskStore
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


def _todo_tool(todos_plugin):
    # Real stella.tasks worker; the host reconciles reminder links into
    # TaskStore(tmp_path/scheduler/tasks.json), the same store as before.
    return TodosTool(service=todos_plugin), todos_plugin.scheduler_store


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


def test_agent_creates_queries_and_changes_todo_reminder_without_duplicate_task(tmp_path, channels, todos_plugin):
    tool, store = _todo_tool(todos_plugin)
    reminder = _future()
    created = tool.execute({"action": "create", "title": "Submit homework", "remind_at": reminder,
                            "reminder_delivery": _route("telegram", "100")})
    assert created.status == "success"
    todo = json.loads(created.result)["todo"]
    assert todo["reminder_delivery"]["primary"]["channel_type"] == "telegram"
    changed = tool.execute({"action": "update", "id": todo["id"],
                            "reminder_delivery": _route("wecom_bot", "chat-1")})
    assert changed.status == "success"
    stored = json.loads(tool.execute({"action": "get", "id": todo["id"]}).result)["todo"]
    assert stored["reminder_delivery"]["primary"]["receiver"] == "chat-1"
    assert "backup" not in stored["reminder_delivery"]
    assert len(store.list_tasks()) == 1
    assert store.get_task(todo["scheduler_task_id"])["reminder_delivery"] == stored["reminder_delivery"]


def test_unchanged_weixin_route_allows_other_edits_after_context_expires(tmp_path, channels, todos_plugin):
    from application import Application
    tool, store = _todo_tool(todos_plugin)
    todo = json.loads(tool.execute({"action": "create", "title": "Before", "remind_at": _future(),
                                    "reminder_delivery": _route("telegram", "100")}).result)["todo"]
    task = {"id": "independent", "name": "Before", "enabled": True,
            "schedule": {"type": "once", "run_at": _future()}, "next_run_at": _future(),
            "action": {"type": "send_message", "channel_type": "telegram", "receiver": "100",
                       "content": "Hello"}}
    scheduler = Application.scheduler(store)
    scheduler.create(task, notification_route=_route("telegram", "100"))
    saved = tool.service.update_todo(todo["id"], {"title": "After", "reminder_delivery": todo["reminder_delivery"]})
    assert saved["title"] == "After"
    existing = scheduler.get("independent")
    saved_task = scheduler.update("independent", {"name": "After", "enabled": False,
        "action": existing["action"], "notification_route": {
            "primary": {"channel_type": "telegram", "receiver": "100"},
            "backup_enabled": False, "backup": None}})
    assert saved_task["name"] == "After" and saved_task["enabled"] is False


def test_agent_rejects_unresolved_todo_recipient(tmp_path, channels, todos_plugin):
    tool, store = _todo_tool(todos_plugin)
    result = tool.execute({"action": "create", "title": "Submit", "remind_at": _future(),
                           "reminder_delivery": _route("telegram", "")})
    assert result.status == "error" and "recipient" in result.result
    assert store.list_tasks() == []


def test_agent_scheduler_route_create_backup_change_and_disable(tmp_path, channels):
    tool = _scheduler_tool(tmp_path)
    created = tool.execute({"action": "create", "name": "Morning", "message": "Get ready",
                            "schedule_type": "once", "schedule_value": _future(),
                            "notification_route": _route("telegram", "100")})
    assert created.status == "success"
    task = tool.task_store.list_tasks()[0]
    assert task["notification_route"]["primary"]["channel_type"] == "telegram"
    assert "backup" not in task["notification_route"]
    enabled = tool.execute({"action": "update", "task_id": task["id"],
                            "notification_route": _route("telegram", "100", enabled=True,
                                backup={"channel_type": "desktop", "receiver": "client"})})
    assert enabled.status == "error" and "备用渠道已移除" in enabled.result
    assert "backup" not in tool.task_store.get_task(task["id"])["notification_route"]
    assert len(tool.task_store.list_tasks()) == 1


def test_agent_scheduler_only_feishu_and_unresolved_recipient(tmp_path, channels):
    tool = _scheduler_tool(tmp_path)
    invalid = tool.execute({"action": "create", "name": "Invalid", "message": "Hello",
                            "schedule_type": "once", "schedule_value": _future(),
                            "notification_route": _route("telegram", "")})
    assert invalid.status == "error"
    assert tool.task_store.list_tasks() == []
    result = tool.execute({"action": "create", "name": "Telegram", "message": "Hello",
                           "schedule_type": "once", "schedule_value": _future(),
                           "notification_route": _route("telegram", "100")})
    assert result.status == "success"
    task = tool.task_store.list_tasks()[0]
    assert "backup" not in task["notification_route"]
    assert task["notification_route"]["needs_reselect"] is False
    assert "private-token" not in str(task)


def test_scheduler_tool_exposes_destination_catalog_and_validation_failure(tmp_path, channels, monkeypatch):
    tool = _scheduler_tool(tmp_path)
    monkeypatch.setattr(delivery, "runtime_channel", lambda name: SimpleNamespace(
        mode="websocket", authenticated=True) if name == "wecom_bot" else None)
    result = tool.execute({"action": "destinations"})
    assert result.status == "success"
    assert "wecom_bot" in result.result
    assert "wx_user" not in result.result
    assert "private-token" not in result.result
    assert tool.execute({"action": "create", "name": "Missing content",
                         "schedule_type": "once", "schedule_value": _future()}).status == "error"


def test_desktop_scheduler_uses_same_route_update_contract(tmp_path, channels, monkeypatch):
    from channel.desktop import desktop_channel as desktop
    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    monkeypatch.setattr(desktop, "_scheduler_store", lambda: store)
    monkeypatch.setattr(desktop, "_require_auth", lambda: None)
    monkeypatch.setattr(desktop.web, "header", lambda *_args: None)
    create = {"name": "Telegram", "schedule": {"type": "once", "run_at": _future()},
              "session_id": "source_chat", "action": {"type": "send_message", "content": "Hello",
              "channel_type": "telegram", "receiver": "100"},
              "notification_route": _route("telegram", "100")}
    with patch.object(desktop.web, "data", return_value=json.dumps(create).encode()):
        response = json.loads(desktop.SchedulerHandler().POST())
    assert response["status"] == "success"
    task_id = response["task"]["id"]
    assert response["task"]["notification_route"]["primary"]["receiver"] == "100"
    update = {"task_id": task_id, "notification_route": _route("wecom_bot", "chat-1")}
    with patch.object(desktop.web, "data", return_value=json.dumps(update).encode()):
        response = json.loads(desktop.SchedulerUpdateHandler().POST())
    assert response["status"] == "success"
    assert store.get_task(task_id)["action"]["channel_type"] == "wecom_bot"
    assert len(store.list_tasks()) == 1


def test_legacy_action_edit_resets_stale_backup_route(tmp_path, channels):
    from application import Application
    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    service = Application.scheduler(store)
    task = {"id": "legacy", "name": "Legacy", "enabled": True,
            "schedule": {"type": "once", "run_at": _future()}, "next_run_at": _future(),
            "action": {"type": "send_message", "content": "Hello", "channel_type": "weixin",
                       "receiver": "wx_user", "execution_session_id": "source_chat"}}
    with pytest.raises(ValueError, match="备用渠道已移除"):
        service.create(task, notification_route=_route("weixin", "wx_user", enabled=True,
            backup={"channel_type": "feishu", "receiver": "ou_backup"}))
    service.create(task, notification_route=_route("telegram", "100"))
    updated = service.update("legacy", {"action": {"channel_type": "wecom_bot", "receiver": "chat-1"}})
    assert updated["notification_route"]["primary"]["receiver"] == "chat-1"
    assert "backup" not in updated["notification_route"]


def test_agent_scheduler_missing_task_is_tool_failure(tmp_path, channels):
    tool = _scheduler_tool(tmp_path)
    for action in ("get", "delete", "enable", "disable", "update"):
        result = tool.execute({"action": action, "task_id": "missing",
                               "notification_route": _route("feishu", "ou_student")})
        assert result.status == "error"


def test_desktop_test_send_uses_live_channel_without_scheduling(tmp_path, channels, monkeypatch):
    from channel.desktop import desktop_channel as desktop
    from agent.scheduler import dispatch
    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    sends = []
    monkeypatch.setattr(desktop, "_scheduler_store", lambda: store)
    monkeypatch.setattr(desktop, "_require_auth", lambda: None)
    monkeypatch.setattr(desktop.web, "header", lambda *_args: None)
    monkeypatch.setattr(dispatch, "_channel_for", lambda _: SimpleNamespace(
        send=lambda reply, context: sends.append((reply.content, context["receiver"])) or {"ret": 0}))
    with patch.object(desktop.web, "data", return_value=json.dumps({
        "notification_route": _route("telegram", "100")}).encode()):
        result = json.loads(desktop.SchedulerTestDeliveryHandler().POST())
    assert result["status"] == "success" and result["delivery_status"] == "accepted"
    assert sends == [("Stella 测试通知", "100")]
    assert store.list_tasks() == []
    with patch.object(desktop.web, "data", return_value=json.dumps({
        "notification_route": _route("weixin", "wx_user")}).encode()):
        result = json.loads(desktop.SchedulerTestDeliveryHandler().POST())
    assert result["status"] == "error" and len(sends) == 1
    with patch.object(desktop.web, "data", return_value=json.dumps({
        "notification_route": {"primary": _route("telegram", "100")["primary"],
                               "backup_enabled": True, "backup": {"channel_type": "desktop", "receiver": "client"}}}).encode()):
        result = json.loads(desktop.SchedulerTestDeliveryHandler().POST())
    assert result["status"] == "error" and len(sends) == 1
