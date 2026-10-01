"""The to-do app has its own store, API, agent tool, and briefing ingestion."""

import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.calendar import CalendarService
from agent.permission.policy import check_tool_call
from agent.todos import TodoService
from agent.tools.todos.todos_tool import TodosTool
from agent.tools.tool_manager import ToolManager


@pytest.fixture
def service(tmp_path):
    return TodoService(tmp_path / "todos.db", tmp_path / "calendar.db")


def test_undated_todo_can_be_edited_completed_and_deleted(service):
    todo = service.create_todo({"title": "交作业", "notes": "上传 PDF", "priority": 2})
    assert todo["due_on"] is None and todo["completed_at"] is None
    assert [row["id"] for row in service.list_todos()] == [todo["id"]]
    assert service.list_todos("2026-10-01", "2026-10-02") == []
    service.complete_todo(todo["id"], True)
    assert service.list_todos(include_completed=False) == []
    service.complete_todo(todo["id"], False)
    updated = service.update_todo(todo["id"], {"due_on": "2026-10-02", "due_time": "09:30"})
    assert updated["due_time"] == "09:30" and updated["user_modified"] == 1
    assert service.list_todos("2026-10-02", "2026-10-03")[0]["id"] == todo["id"]
    service.delete_todo(todo["id"])
    assert service.list_todos() == []


def test_weekly_completion_applies_to_one_occurrence(service):
    todo = service.create_todo({"title": "上交周报", "due_on": "2026-10-05", "due_time": "17:00",
                                "repeat_frequency": "weekly", "repeat_days": [0], "repeat_until": "2026-10-19"})
    rows = service.list_todos("2026-10-01", "2026-10-22")
    assert [row["due_on"] for row in rows] == ["2026-10-05", "2026-10-12", "2026-10-19"]
    service.complete_todo(rows[0]["id"], True)
    assert [bool(row["completed_at"]) for row in service.list_todos("2026-10-01", "2026-10-22")] == [True, False, False]
    with pytest.raises(ValueError, match="occurrence"):
        service.complete_todo(todo["id"], True)


def test_todo_validation(service):
    for payload in ({"title": "x", "due_time": "09:00"}, {"title": "x", "priority": 4},
                    {"title": "x", "repeat_frequency": "daily"}, {"title": "x", "due_on": "2026-02-30"}):
        with pytest.raises(ValueError):
            service.create_todo(payload)


def test_briefing_actions_create_todos_and_preserve_user_edits(service):
    item = SimpleNamespace(source="elearning", account_id="student", source_id="homework-1",
                           source_item_id="source-1", section="action", title="交作业", snippet="课后作业",
                           payload={"due_at": "2026-10-02T20:00:00+08:00"}, url="https://example.test",
                           id="card-1")
    detail = {"briefing": SimpleNamespace(id="briefing-1"), "items": [item], "mail": []}
    service.ingest_briefing(detail)
    service.ingest_briefing(detail)
    rows = service.list_todos()
    assert len(rows) == 1 and rows[0]["due_on"] == "2026-10-02" and rows[0]["due_time"] == "20:00"
    service.complete_todo(rows[0]["id"], True)
    item.section = "fyi"
    service.ingest_briefing(detail)
    assert len(service.list_todos()) == 1 and service.list_todos()[0]["completed_at"]


def test_legacy_calendar_todos_migrate_once_without_reappearing(tmp_path):
    calendar_path = tmp_path / "calendar.db"
    calendar = CalendarService(calendar_path)
    with sqlite3.connect(calendar_path) as db:
        db.execute("INSERT INTO agenda_handoffs VALUES (?,?,?,?,?,?,?,?,?)",
                   ("briefing", "old-source", "task", "旧事务", "备忘", "briefing-1", "item-1", None, "2026-10-01"))
    path = tmp_path / "todos.db"
    service = TodoService(path, calendar_path)
    assert [row["title"] for row in service.list_todos()] == ["旧事务"]
    todo_id = service.list_todos()[0]["id"]
    service.delete_todo(todo_id)
    assert TodoService(path, calendar_path).list_todos() == []
    assert calendar.list_events() == []


def test_migrates_old_calendar_affairs_and_completion(tmp_path):
    calendar_path = tmp_path / "calendar.db"
    CalendarService(calendar_path)
    with sqlite3.connect(calendar_path) as db:
        db.executescript("""CREATE TABLE calendar_affairs (
            id TEXT PRIMARY KEY,title TEXT,notes TEXT,due_on TEXT,due_time TEXT,timezone TEXT,
            priority INTEGER,completed_at TEXT,repeat_frequency TEXT,repeat_days TEXT,repeat_until TEXT,
            source_type TEXT,source_key TEXT,source_url TEXT,user_modified INTEGER,created_at TEXT,updated_at TEXT);
            CREATE TABLE calendar_affair_completions (affair_id TEXT,occurrence_on TEXT,completed_at TEXT);
            CREATE TABLE calendar_affair_notifications (affair_id TEXT,occurrence_on TEXT,notified_at TEXT);""")
        db.execute("INSERT INTO calendar_affairs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("old-id", "旧重复事务", "备注", "2026-10-01", "09:00", "Asia/Shanghai", 2, None,
                    "daily", "[]", None, None, None, "", 1, "2026-09-01", "2026-09-01"))
        db.execute("INSERT INTO calendar_affair_completions VALUES (?,?,?)",
                   ("old-id", "2026-10-01", "2026-10-01T01:00:00+00:00"))
        db.execute("INSERT INTO calendar_affair_notifications VALUES (?,?,?)",
                   ("old-id", "2026-10-01", "2026-10-01T01:00:00+00:00"))
    service = TodoService(tmp_path / "todos.db", calendar_path)
    rows = service.list_todos("2026-10-01", "2026-10-03")
    assert rows[0]["id"] == "old-id@2026-10-01" and rows[0]["completed_at"]
    assert rows[1]["id"] == "old-id@2026-10-02" and not rows[1]["completed_at"]
    assert service.claim_due_todo_notifications(datetime(2026, 10, 1, 1, 1, tzinfo=timezone.utc)) == []


def test_due_notifications_claim_once_and_skip_completed_occurrences(service):
    due = {"due_on": "2026-10-01", "due_time": "09:00", "timezone": "Asia/Shanghai"}
    single = service.create_todo({"title": "交作业", **due})
    recurring = service.create_todo({"title": "打卡", **due, "repeat_frequency": "daily"})
    service.complete_todo(f"{recurring['id']}@2026-10-01", True)
    now = datetime(2026, 10, 1, 1, 1, tzinfo=timezone.utc)
    assert [row["id"] for row in service.claim_due_todo_notifications(now)] == [single["id"]]
    assert service.claim_due_todo_notifications(now) == []
    tomorrow = datetime(2026, 10, 2, 1, 1, tzinfo=timezone.utc)
    assert f"{recurring['id']}@2026-10-02" in [row["id"] for row in service.claim_due_todo_notifications(tomorrow)]


def test_tool_and_web_api_are_independent(service, monkeypatch):
    manager = ToolManager()
    manager._load_tools_from_init()
    assert manager.tool_classes["todos"] is TodosTool
    tool = TodosTool(service=service)
    assert json.loads(tool.execute({"action": "create", "title": "准备报告"}).result)["todo"]["title"] == "准备报告"
    assert not check_tool_call("read-only", "todos", {"action": "complete", "id": "x", "completed": True})
    assert check_tool_call("read-only", "todos", {"action": "list"})

    from channel.web import web_channel
    monkeypatch.setattr(web_channel, "_todo_service", lambda: service)
    monkeypatch.setattr(web_channel, "_require_auth", lambda: None)
    monkeypatch.setattr(web_channel.web, "header", lambda *_args: None)
    with patch.object(web_channel.web, "data", return_value='{"title":"来自页面"}'.encode()):
        result = json.loads(web_channel.TodosHandler().POST())
    assert result["status"] == "success" and result["todo"]["title"] == "来自页面"
