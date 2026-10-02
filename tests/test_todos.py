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


def test_old_database_migrates_without_losing_todos(service):
    old = service.create_todo({"title": "Existing", "due_on": "2026-10-02"})
    with sqlite3.connect(service.db_path) as db:
        for column in ("planned_on", "list_name", "tags", "flagged", "checklist"):
            db.execute(f"ALTER TABLE todos DROP COLUMN {column}")
    reopened = TodoService(service.db_path, service.legacy_calendar_db_path)
    migrated = reopened.get_todo(old["id"])
    assert migrated["title"] == "Existing" and migrated["due_on"] == "2026-10-02"
    assert migrated["tags"] == "[]" and migrated["list_name"] == "" and migrated["flagged"] == 0
    updated = reopened.update_todo(old["id"], {"planned_on": "2026-10-01", "list_name": "Work",
        "tags": ["urgent", "urgent"], "flagged": True,
        "checklist": [{"id": "upload", "title": "Upload PDF"}]})
    assert updated["planned_on"] == "2026-10-01" and updated["due_on"] == "2026-10-02"
    assert json.loads(updated["tags"]) == ["urgent"]


def test_repeating_checklist_completion_and_plan_date_are_occurrence_scoped(service):
    todo = service.create_todo({"title": "Daily", "due_on": "2026-10-02", "planned_on": "2026-10-01",
        "repeat_frequency": "daily", "checklist": [{"id": "step", "title": "Check"}]})
    service.complete_checklist_item(f"{todo['id']}@2026-10-02", "step", True)
    rows = service.list_todos("2026-10-02", "2026-10-04")
    assert rows[0]["planned_on"] == "2026-10-01" and rows[1]["planned_on"] == "2026-10-02"
    assert json.loads(rows[0]["checklist"])[0]["completed"] is True
    assert json.loads(rows[1]["checklist"])[0]["completed"] is False
    assert service.list_todos_focus("2026-10-02")[0]["id"] == rows[0]["id"]
    service.complete_todo(rows[0]["id"], True)
    focus = service.list_todos_focus("2026-10-02")
    assert len(focus) == 2
    assert focus[0]["id"] == rows[1]["id"] and focus[0]["completed_at"] is None
    assert focus[1]["id"] == rows[0]["id"] and focus[1]["completed_at"] is not None


@pytest.mark.parametrize("payload", [{"tags": "oops"}, {"flagged": 2}, {"planned_on": "tomorrow"},
    {"checklist": [{"title": "", "completed": True}]},
    {"checklist": [{"id": "x", "title": "One"}, {"id": "x", "title": "Two"}]}])
def test_organization_fields_reject_invalid_values(service, payload):
    with pytest.raises(ValueError):
        service.create_todo({"title": "Test", **payload})
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


def test_desktop_reminder_lease_ack_and_retry(service):
    from datetime import datetime, timezone

    todo = service.create_todo({"title": "Pay bill", "due_on": "2026-10-02",
                                "due_time": "08:00", "timezone": "Asia/Shanghai"})
    due = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
    claimed = service.claim_desktop_reminders(due)
    assert len(claimed) == 1
    assert claimed[0]["todo_id"] == todo["id"]
    assert service.claim_desktop_reminders(due) == []
    delivery = claimed[0]
    assert not service.acknowledge_desktop_reminder(delivery["delivery_id"], "wrong", True)
    assert service.acknowledge_desktop_reminder(delivery["delivery_id"], delivery["claim_id"], False)
    retried = service.claim_desktop_reminders(due)
    assert retried[0]["delivery_id"] == delivery["delivery_id"]
    assert retried[0]["claim_id"] != delivery["claim_id"]
    assert service.acknowledge_desktop_reminder(retried[0]["delivery_id"], retried[0]["claim_id"], True)
    assert service.claim_desktop_reminders(due) == []


def test_desktop_reminder_cancels_on_completion(service):
    from datetime import datetime, timezone

    todo = service.create_todo({"title": "Review", "due_on": "2026-10-02",
                                "due_time": "08:00", "timezone": "Asia/Shanghai"})
    due = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
    delivery = service.claim_desktop_reminders(due)[0]
    service.complete_todo(todo["id"], True)
    assert not service.acknowledge_desktop_reminder(delivery["delivery_id"], delivery["claim_id"], True)
    assert service.claim_desktop_reminders(due) == []


def test_desktop_migration_records_old_claim_as_unknown(service, monkeypatch):
    todo = service.create_todo({"title": "Legacy", "due_on": "2026-10-02",
                                "due_time": "08:00", "timezone": "Asia/Shanghai"})
    with sqlite3.connect(service.db_path) as db:
        db.execute("INSERT INTO todo_notifications VALUES (?,?,?)",
                   (todo["id"], "2026-10-02", "2026-10-02T00:30:00+00:00"))
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    reopened = TodoService(service.db_path, service.legacy_calendar_db_path)
    with sqlite3.connect(service.db_path) as db:
        assert db.execute("SELECT state FROM reminder_occurrences WHERE todo_id=?",
                          (todo["id"],)).fetchone()[0] == "legacy_claimed_unknown"
        assert db.execute("SELECT status FROM reminder_deliveries").fetchone()[0] == "legacy_claimed_unknown"
    assert reopened.claim_desktop_reminders(datetime(2026, 10, 2, 1, tzinfo=timezone.utc)) == []


def test_legacy_unknown_reminder_needs_explicit_retry(service, monkeypatch):
    todo = service.create_todo({"title": "Review", "due_on": "2026-10-02",
                                "due_time": "08:00", "timezone": "Asia/Shanghai"})
    with sqlite3.connect(service.db_path) as db:
        db.execute("INSERT INTO todo_notifications VALUES (?,?,?)",
                   (todo["id"], "2026-10-02", datetime.now(timezone.utc).isoformat()))
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    reopened = TodoService(service.db_path, service.legacy_calendar_db_path)
    uncertain = reopened.list_uncertain_reminders()
    assert len(uncertain) == 1 and uncertain[0]["title"] == "Review"
    assert reopened.retry_uncertain_reminder(uncertain[0]["delivery_id"])
    assert reopened.list_uncertain_reminders() == []
    due = datetime(2026, 10, 2, 1, tzinfo=timezone.utc)
    assert reopened.claim_desktop_reminders(due)[0]["delivery_id"] == uncertain[0]["delivery_id"]


def test_legacy_unknown_reminder_is_cancelled_if_todo_completed(service, monkeypatch):
    todo = service.create_todo({"title": "Review", "due_on": "2026-10-02",
                                "due_time": "08:00", "timezone": "Asia/Shanghai"})
    with sqlite3.connect(service.db_path) as db:
        db.execute("INSERT INTO todo_notifications VALUES (?,?,?)",
                   (todo["id"], "2026-10-02", "2026-10-02T00:30:00+00:00"))
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    reopened = TodoService(service.db_path, service.legacy_calendar_db_path)
    reminder = reopened.list_uncertain_reminders()[0]
    reopened.complete_todo(todo["id"], True)
    assert not reopened.retry_uncertain_reminder(reminder["delivery_id"])
    assert reopened.list_uncertain_reminders() == []


def test_legacy_unknown_reminder_is_cancelled_if_todo_was_edited(service, monkeypatch):
    todo = service.create_todo({"title": "Review", "due_on": "2026-10-02",
                                "due_time": "08:00", "timezone": "Asia/Shanghai"})
    with sqlite3.connect(service.db_path) as db:
        db.execute("INSERT INTO todo_notifications VALUES (?,?,?)",
                   (todo["id"], "2026-10-02", "2026-10-02T00:30:00+00:00"))
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    reopened = TodoService(service.db_path, service.legacy_calendar_db_path)
    reminder = reopened.list_uncertain_reminders()[0]
    reopened.update_todo(todo["id"], {"due_time": "09:00"})
    assert not reopened.retry_uncertain_reminder(reminder["delivery_id"])
    assert reopened.list_uncertain_reminders() == []


def test_uncertain_reminder_desktop_api_uses_todo_service(service, monkeypatch):
    from channel.web import web_channel
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
    assert check_tool_call("read-only", "todos", {"action": "list"})

    from channel.web import web_channel
    monkeypatch.setattr(web_channel, "_todo_service", lambda: service)
    monkeypatch.setattr(web_channel, "_require_auth", lambda: None)
    monkeypatch.setattr(web_channel.web, "header", lambda *_args: None)
    with patch.object(web_channel.web, "data", return_value='{"title":"来自页面"}'.encode()):
        result = json.loads(web_channel.TodosHandler().POST())
    assert result["status"] == "success" and result["todo"]["title"] == "来自页面"


def test_todo_api_validation_errors_are_written_to_logs(service, monkeypatch):
    from channel.web import web_channel

    monkeypatch.setattr(web_channel, "_todo_service", lambda: service)
    monkeypatch.setattr(web_channel, "_require_auth", lambda: None)
    monkeypatch.setattr(web_channel.web, "header", lambda *_args: None)
    params = SimpleNamespace(start="2026-09-01", end="2027-10-01", include_completed="true")
    with patch.object(web_channel.web, "input", return_value=params), \
         patch.object(web_channel.logger, "warning") as log_warning:
        response = json.loads(web_channel.TodosHandler().GET())
    assert response == {"status": "error", "message": "invalid todo range"}
    log_warning.assert_called_once()
    assert "invalid todo range" in log_warning.call_args.args[0]
