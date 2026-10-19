"""Core integration of the stella.tasks plugin: agent tool, desktop API, commands, calendar handoff.

Pure Tasks domain behaviour lives with the plugin in
Stella-Plugins/plugins/tasks/tests/; every test here drives the real plugin
worker through ``TodosPluginFacade`` (see the ``todos_plugin`` fixture).
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.calendar import CalendarService
from agent.permission.gateway import SecurityGateway
from agent.scheduler.automation_store import AutomationStore
from agent.scheduler import delivery
from agent.todos import scheduler_link
from application import Application, RequestContext
from common.runtime_identity import identity_scope
from core.services import todos_gateway
from agent.tools.todos.todos_tool import TodosTool
from agent.tools.tool_manager import ToolManager

check_tool_call = SecurityGateway.check


@pytest.fixture
def service(todos_plugin):
    return todos_plugin


def test_disconnected_route_does_not_block_unrelated_todo_edit(service, monkeypatch):
    monkeypatch.setattr(delivery, "runtime_channel", lambda _: SimpleNamespace())
    instant = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    todo = service.create_todo({"title": "Original", "remind_at": instant,
        "reminder_delivery": {"primary": {"channel_type": "telegram", "receiver": "100"}}})
    monkeypatch.setattr(delivery, "runtime_channel", lambda _: None)
    renamed = service.update_todo(todo["id"], {"title": "Renamed"})
    assert renamed["title"] == "Renamed"
    assert renamed["reminder_delivery"] == todo["reminder_delivery"]


def test_linked_reminder_uses_user_scoped_desktop_scheduler_and_internal_command(tmp_path, service, monkeypatch):
    with identity_scope(user_id="student-a"):
        store = AutomationStore(tmp_path / "scheduler" / "tasks.json", "default")
        # The host reconciles plugin reminder links into the user-scoped desktop store.
        monkeypatch.setattr(scheduler_link, "default_scheduler_store", lambda: store)
        reminder = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        todo = service.create_todo({"title": "提交课程作业", "remind_at": reminder})
        linked = store.get_task(todo["scheduler_task_id"])
        assert linked["owner_user_id"] == "student-a"
        with patch.object(Application, "port", return_value=service):
            with pytest.raises(PermissionError, match="reserved for scheduler"):
                Application.command("todos", "QueueTodoReminder", [todo["id"], reminder],
                                    RequestContext(source="desktop", user_id="student-a"))
            result = Application.command("todos", "QueueTodoReminder", [todo["id"], reminder],
                                         RequestContext(source="scheduler", user_id="student-a"))
            assert result["value"] is False  # The scheduler has not reached the time yet.
    with identity_scope(user_id="student-b"):
        assert store.get_task(todo["scheduler_task_id"]) is None


def test_legacy_calendar_todos_migrate_once_without_reappearing(tmp_path, service):
    calendar_path = tmp_path / "calendar.db"
    calendar = CalendarService(calendar_path)
    with sqlite3.connect(calendar_path) as db:
        db.execute("INSERT INTO agenda_handoffs VALUES (?,?,?,?,?,?,?,?,?)",
                   ("briefing", "old-source", "task", "旧事务", "备忘", "briefing-1", "item-1", None, "2026-10-01"))
    assert [row["title"] for row in service.list_todos()] == ["旧事务"]
    todo_id = service.list_todos()[0]["id"]
    service.delete_todo(todo_id)
    todos_gateway.shutdown_todos_session()  # reopen: a fresh worker over the same files
    assert service.list_todos() == []
    assert calendar.list_events() == []


def test_uncertain_reminder_desktop_api_uses_todo_service(service, monkeypatch):
    from channel.desktop import desktop_channel as web_channel
    monkeypatch.setattr(web_channel, "_todo_service", lambda: service)
    monkeypatch.setattr(web_channel, "_require_auth", lambda: None)
    monkeypatch.setattr(web_channel.web, "header", lambda *_args: None)
    result = json.loads(web_channel.TodoUncertainRemindersHandler().GET())
    assert result == {"status": "success", "reminders": []}
    with patch.object(web_channel.web, "data", return_value=b'{"delivery_id":"missing"}'):
        result = json.loads(web_channel.TodoRetryReminderHandler().POST())
    assert result["status"] == "error"


def test_tool_and_web_api_are_independent(service, monkeypatch):
    manager = ToolManager()
    manager._load_tools_from_init()
    assert manager.tool_classes["todos"] is TodosTool
    tool = TodosTool(service=service)
    assert json.loads(tool.execute({"action": "create", "title": "准备报告"}).result)["todo"]["title"] == "准备报告"
    assert not check_tool_call("read-only", "todos", {"action": "complete", "id": "x", "completed": True})
    assert not check_tool_call("read-only", "todos", {"action": "add_dependency", "id": "x", "prerequisite_id": "y"})
    assert check_tool_call("read-only", "todos", {"action": "list"})

    from channel.desktop import desktop_channel as web_channel
    monkeypatch.setattr(web_channel, "_todo_service", lambda: service)
    monkeypatch.setattr(web_channel, "_require_auth", lambda: None)
    monkeypatch.setattr(web_channel.web, "header", lambda *_args: None)
    with patch.object(web_channel.web, "data", return_value='{"title":"来自页面"}'.encode()):
        result = json.loads(web_channel.TodosHandler().POST())
    assert result["status"] == "success" and result["todo"]["title"] == "来自页面"


def test_agent_and_desktop_share_hierarchy_and_status_rules(service, monkeypatch):
    from channel.desktop import desktop_channel as web_channel
    monkeypatch.setattr(web_channel, "_todo_service", lambda: service)
    monkeypatch.setattr(web_channel, "_require_auth", lambda: None)
    monkeypatch.setattr(web_channel.web, "header", lambda *_args: None)
    tool = TodosTool(service=service)
    parent = json.loads(tool.execute({"action": "create", "title": "Homework"}).result)["todo"]
    with patch.object(web_channel.web, "data", return_value=json.dumps({
        "parent_id": parent["id"], "title": "Check answers"}).encode()):
        child = json.loads(web_channel.TodoSubtaskHandler().POST())["todo"]
    assert child["parent_id"] == parent["id"]
    assert json.loads(tool.execute({"action": "get", "id": parent["id"]}).result)["todo"]["progress_total"] == 1
    completed = tool.execute({"action": "status", "id": parent["id"], "status": "completed"})
    assert completed.status == "success"
    assert json.loads(completed.result)["todo"]["status"] == "completed"
    assert service.get_todo(child["id"])["status"] == "completed"
    with patch.object(web_channel.web, "data", return_value=json.dumps({
        "id": child["id"], "status": "completed"}).encode()):
        assert json.loads(web_channel.TodoStatusHandler().POST())["todo"]["status"] == "completed"
    assert json.loads(tool.execute({"action": "complete", "id": parent["id"],
                                    "completed": True}).result)["todo"]["status"] == "completed"
    next_step = json.loads(tool.execute({"action": "create", "title": "Submit"}).result)["todo"]
    linked = tool.execute({"action": "add_dependency", "id": next_step["id"],
                           "prerequisite_id": child["id"]})
    assert json.loads(linked.result)["todo"]["dependency_ids"] == [child["id"]]


def test_todo_api_validation_errors_are_written_to_logs(service, monkeypatch):
    from channel.desktop import desktop_channel as web_channel

    monkeypatch.setattr(web_channel, "_todo_service", lambda: service)
    monkeypatch.setattr(web_channel, "_require_auth", lambda: None)
    monkeypatch.setattr(web_channel.web, "header", lambda *_args: None)
    params = SimpleNamespace(start="2026-09-01", end="2027-10-01", include_completed="true")
    with patch.object(web_channel.web, "input", return_value=params), \
         patch.object(web_channel.logger, "warning") as log_warning:
        response = json.loads(web_channel.TodosHandler().GET())
    assert response == {"status": "error", "message": "invalid todo range"}
    log_warning.assert_called_once()
    assert "invalid todo range" in log_warning.call_args.args[-1]



def test_manual_task_payload_cannot_impersonate_a_briefing_source(service):
    existing = service.create_todo({'title':'Briefing task'}, _briefing_key='owned-source')
    with pytest.raises(ValueError, match='reserved'):
        service.create_todo({'title':'New manual task', '_briefing_key':'owned-source'})
    assert [todo['id'] for todo in service.list_todos()] == [existing['id']]
