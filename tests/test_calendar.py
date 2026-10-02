"""Calendar storage, agent access, and briefing routing share one SQLite model."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from agent.calendar import CalendarService
from agent.permission.policy import check_tool_call
from agent.tools.calendar.calendar_tool import CalendarTool
from agent.tools.tool_manager import ToolManager


@pytest.fixture
def service(tmp_path):
    return CalendarService(tmp_path / "calendar.db")


def test_events_categories_and_time_ranges_persist(service):
    group = service.create_category({"name": "旅行", "color": "#123ABC"})
    event = service.create_event({
        "title": "出发", "start_at": "2026-10-01T09:00:00+08:00",
        "end_at": "2026-10-01T10:00:00+08:00", "category_id": group["id"],
    })
    assert event["start_at"] == "2026-10-01T01:00:00+00:00"
    assert [row["id"] for row in CalendarService(service.db_path).list_events(
        "2026-10-01T00:00:00+08:00", "2026-10-02T00:00:00+08:00", group["id"])] == [event["id"]]
    changed = service.update_event(event["id"], {"title": "乘车", "location": "车站"})
    assert changed["title"] == "乘车" and changed["user_modified"] == 1
    service.delete_category(group["id"])
    assert service.get_event(event["id"])["category_id"] is None
    service.delete_event(event["id"])
    assert service.list_events() == []
    with pytest.raises(ValueError):
        service.create_event({"title": "bad", "start_at": "2026-10-01T10:00+08:00", "end_at": "2026-10-01T09:00+08:00"})


def test_default_categories_are_for_schedules(service):
    assert [category["id"] for category in service.categories()] == [
        "personal", "work", "study", "china_holidays"]
    with pytest.raises(ValueError):
        service.delete_category("china_holidays")


def test_weekly_series_expands_selected_days_and_updates_whole_series(service):
    event = service.create_event({
        "title": "上课", "start_at": "2026-10-05T09:00+08:00", "end_at": "2026-10-05T10:00+08:00",
        "repeat_frequency": "weekly", "repeat_days": [0, 2], "repeat_until": "2026-10-14",
        "repeat_timezone": "Asia/Shanghai",
    })
    rows = service.list_events("2026-10-05T00:00+08:00", "2026-10-19T00:00+08:00")
    assert [row["start_at"] for row in rows] == [
        "2026-10-05T01:00:00+00:00", "2026-10-07T01:00:00+00:00",
        "2026-10-12T01:00:00+00:00", "2026-10-14T01:00:00+00:00",
    ]
    assert all(row["series_id"] == event["id"] for row in rows)
    service.update_event(event["id"], {"title": "新课程"})
    assert all(row["title"] == "新课程" for row in service.list_events("2026-10-05T00:00+08:00", "2026-10-19T00:00+08:00"))


def test_daily_recurrence_preserves_local_time_across_dst(service):
    service.create_event({"title": "晨会", "start_at": "2026-10-31T09:00-04:00",
        "end_at": "2026-10-31T10:00-04:00", "repeat_frequency": "daily",
        "repeat_timezone": "America/New_York", "repeat_until": "2026-11-02"})
    rows = service.list_events("2026-10-31T00:00-04:00", "2026-11-03T00:00-05:00")
    assert [row["start_at"] for row in rows] == [
        "2026-10-31T13:00:00+00:00", "2026-11-01T14:00:00+00:00", "2026-11-02T14:00:00+00:00"]


def test_monthly_and_yearly_recurrence_skip_missing_calendar_dates(service):
    service.create_event({"title": "月末", "start_at": "2026-01-31T09:00+08:00",
        "end_at": "2026-01-31T10:00+08:00", "repeat_frequency": "monthly",
        "repeat_timezone": "Asia/Shanghai"})
    service.create_event({"title": "闰日", "start_at": "2024-02-29T09:00+08:00",
        "end_at": "2024-02-29T10:00+08:00", "repeat_frequency": "yearly",
        "repeat_timezone": "Asia/Shanghai"})
    assert [row["title"] for row in service.list_events("2026-02-01T00:00+08:00", "2026-03-01T00:00+08:00")] == []
    assert [row["title"] for row in service.list_events("2026-03-01T00:00+08:00", "2026-04-01T00:00+08:00")] == ["月末"]


def test_existing_database_gets_recurrence_columns(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE calendar_events (id TEXT PRIMARY KEY, title TEXT, description TEXT,
            start_at TEXT, end_at TEXT, all_day INTEGER, location TEXT, category_id TEXT,
            source_type TEXT, source_key TEXT, source_url TEXT, user_modified INTEGER,
            created_at TEXT, updated_at TEXT)""")
    service = CalendarService(path)
    event = service.create_event({"title": "迁移后", "start_at": "2026-10-01T09:00+08:00", "end_at": "2026-10-01T10:00+08:00"})
    assert event["repeat_frequency"] == "none"


def test_concurrent_calendar_requests_migrate_old_database_once(tmp_path):
    path = tmp_path / "old-concurrent.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE calendar_events (id TEXT PRIMARY KEY, title TEXT, description TEXT,
            start_at TEXT, end_at TEXT, all_day INTEGER, location TEXT, category_id TEXT,
            source_type TEXT, source_key TEXT, source_url TEXT, user_modified INTEGER,
            created_at TEXT, updated_at TEXT)""")
    ready = Barrier(8)
    def open_calendar(_):
        ready.wait()
        return CalendarService(path).categories()
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert len(list(pool.map(open_calendar, range(8)))) == 8
    with sqlite3.connect(path) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(calendar_events)")]
    assert columns.count("repeat_frequency") == 1


def test_official_holidays_import_into_current_calendar_once(service):
    result = service.import_china_holidays(2026)
    assert result == {"year": 2026, "added": 13, "total": 13}
    assert service.import_china_holidays(2026)["added"] == 0
    rows = service.list_events("2026-09-25T00:00+08:00", "2026-09-28T00:00+08:00")
    assert len(rows) == 1 and rows[0]["title"] == "中秋节（休）"
    assert rows[0]["source_type"] == "china_holiday"
    assert rows[0]["category_id"] == "china_holidays"
    assert rows[0]["source_url"].startswith("https://www.gov.cn/")
    assert service.list_events("2026-10-10T00:00+08:00", "2026-10-11T00:00+08:00")[0]["title"] == "调休上班（班）"
    with pytest.raises(ValueError, match="cannot be edited"):
        service.update_event(rows[0]["id"], {"title": "changed"})
    assert len([row for row in service.list_events() if row["source_type"] == "china_holiday"]) == 13


def test_manual_and_file_special_dates_share_calendar_and_recur(service):
    manual = service.create_special_date({"title": "生日", "date": "2026-10-01", "annual": True,
                                          "timezone": "Asia/Shanghai", "description": "家人"})
    assert manual["source_type"] == "special_date" and manual["all_day"] == 1
    assert manual["category_id"] == "personal"
    assert service.list_events("2027-10-01T00:00+08:00", "2027-10-02T00:00+08:00")[0]["title"] == "生日"
    csv_content = "title,date,annual,description\n考试,2026-10-02,false,重要\n"
    assert service.import_special_dates(csv_content, "csv", "Asia/Shanghai") == {"added": 1, "total": 1}
    assert service.import_special_dates(csv_content, "csv", "Asia/Shanghai")["added"] == 0
    ics_content = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:anniversary-1\nSUMMARY:纪念日\nDTSTART;VALUE=DATE:20261003\nRRULE:FREQ=YEARLY\nEND:VEVENT\nEND:VCALENDAR"
    assert service.import_special_dates(ics_content, "ics", "Asia/Shanghai") == {"added": 1, "total": 1}
    assert service.import_special_dates(ics_content, "ics", "Asia/Shanghai")["added"] == 0
    assert {row["title"] for row in service.list_events()} == {"生日", "考试", "纪念日"}
    assert [row["id"] for row in service.categories()] == ["personal", "work", "study", "china_holidays"]
    assert service.list_events("2027-10-03T00:00+08:00", "2027-10-04T00:00+08:00")[0]["title"] == "纪念日"


def test_old_special_date_category_merges_into_personal_without_losing_events(service):
    row = service.create_special_date({"title": "旧纪念日", "date": "2026-10-01", "annual": False})
    with sqlite3.connect(service.db_path) as db:
        db.execute("INSERT INTO calendar_categories VALUES (?,?,?,?)", ("special_dates", "特殊日期", "#D183C6", "2026-01-01"))
        db.execute("UPDATE calendar_events SET category_id='special_dates' WHERE id=?", (row["id"],))
    reopened = CalendarService(service.db_path)
    assert reopened.get_event(row["id"])["category_id"] == "personal"
    assert "special_dates" not in {category["id"] for category in reopened.categories()}


def test_bad_special_date_file_does_not_partially_import(service):
    with pytest.raises(ValueError):
        service.import_special_dates("title,date\n有效,2026-10-02\n无效,2026-02-30\n", "csv", "Asia/Shanghai")
    assert service.list_events() == []


def test_briefing_handoff_is_idempotent_and_preserves_user_edits(service):
    item = SimpleNamespace(source="elearning", account_id="student", source_id="quiz-1",
        source_item_id="src-1", section="action", title="课程测验", snippet="周五截止",
        payload={"due_at": "2026-10-02T20:00:00+08:00"}, url="https://example.test/quiz",
        id="item-1")
    detail = {"briefing": SimpleNamespace(id="briefing-1"), "items": [item], "mail": [
        {"id": "src-1", "decision": {"calendar": {"start_at": "2026-10-02T09:00:00+08:00"}}}]}
    assert service.ingest_briefing(detail) == 1
    assert service.ingest_briefing(detail) == 1
    assert len(service.list_events()) == 1
    event = service.list_events()[0]
    assert event["category_id"] == "study"
    with sqlite3.connect(service.db_path) as db:
        assert db.execute("SELECT destination FROM agenda_handoffs ORDER BY destination").fetchall() == [("calendar",)]
    service.update_event(event["id"], {"title": "我修改的标题"})
    item.title = "来源的新标题"
    service.ingest_briefing(detail)
    assert service.get_event(event["id"])["title"] == "我修改的标题"


def test_briefing_reclassification_removes_unmodified_handoffs(service):
    item = SimpleNamespace(source="elearning", account_id="student", source_id="quiz-2",
        source_item_id="src-2", section="action", title="旧截止", snippet="截止",
        payload={"due_at": "2026-10-02T20:00:00+08:00"}, url="", id="item-2")
    detail = {"briefing": SimpleNamespace(id="briefing-2"), "items": [item], "mail": []}
    service.ingest_briefing(detail)
    assert service.list_events() == []
    item.section = "fyi"
    item.payload = {}
    service.ingest_briefing(detail)
    assert service.list_events() == []
    with sqlite3.connect(service.db_path) as db:
        assert db.execute("SELECT count(*) FROM agenda_handoffs").fetchone()[0] == 0


def test_deleted_default_category_does_not_block_briefing_import(service):
    service.delete_category("study")
    assert "study" not in {row["id"] for row in CalendarService(service.db_path).categories()}
    item = SimpleNamespace(source="elearning", account_id="student", source_id="quiz-3",
        source_item_id="src-3", thread_id="", section="action", title="新截止", snippet="截止",
        payload={"due_at": "2026-10-02T20:00:00+08:00"}, url="", id="item-3")
    service.ingest_briefing({"briefing": SimpleNamespace(id="briefing-4"), "items": [item], "mail": [
        {"id": "src-3", "decision": {"calendar": {"start_at": "2026-10-02T09:00:00+08:00"}}}]})
    assert service.list_events()[0]["category_id"] is None


def test_merged_briefing_thread_routes_each_selected_source(service):
    card = SimpleNamespace(source="email", account_id="inbox", source_id="first",
        source_item_id="src-1", thread_id="thread-1", section="action",
        title="会议通知", snippet="摘要", payload={}, url="", id="card-1")
    mail = [
        {"id": "src-1", "source": "email", "account_id": "inbox", "source_id": "first",
         "thread_id": "thread-1", "category": "selected", "decision": {"section": "action"}},
        {"id": "src-2", "source": "email", "account_id": "inbox", "source_id": "second",
         "thread_id": "thread-1", "category": "selected", "title": "会议改期", "snippet": "摘要",
         "metadata": {}, "url": "", "decision": {"section": "action", "calendar": {
             "start_at": "2026-10-03T10:00:00+08:00"}}},
    ]
    assert service.ingest_briefing({"briefing": SimpleNamespace(id="briefing-3"), "items": [card], "mail": mail}) == 1
    assert service.list_events()[0]["title"] == "会议改期"
    with sqlite3.connect(service.db_path) as db:
        assert db.execute("SELECT count(*) FROM agenda_handoffs WHERE destination='task'").fetchone()[0] == 0


def test_agent_tool_discovery_and_permissions(service):
    manager = ToolManager()
    manager._load_tools_from_init()
    assert manager.tool_classes["calendar"] is CalendarTool
    tool = CalendarTool(service=service)
    result = tool.execute({"action": "create", "title": "会议", "start_at": "2026-10-01T09:00+08:00", "end_at": "2026-10-01T10:00+08:00"})
    assert json.loads(result.result)["event"]["title"] == "会议"
    recurring = tool.execute({"action": "create", "title": "每周课", "start_at": "2026-10-05T09:00+08:00",
        "end_at": "2026-10-05T10:00+08:00", "repeat_frequency": "weekly", "repeat_days": [0],
        "repeat_timezone": "Asia/Shanghai"})
    assert json.loads(recurring.result)["event"]["repeat_frequency"] == "weekly"
    assert check_tool_call("read-only", "calendar", {"action": "list"})
    assert not check_tool_call("read-only", "calendar", {"action": "create"})
    assert check_tool_call("workspace-write", "calendar", {"action": "create"})

@pytest.mark.usefixtures("deterministic_briefing_generator")
def test_briefing_pipeline_routes_due_item_to_todos(tmp_path, monkeypatch):
    from datetime import datetime
    from agent.briefing.pipeline import BriefingPipeline
    from agent.briefing.service import BriefingService
    from agent.briefing.sources.base import FetchedItem
    from agent.briefing.store import BriefingStore
    from briefing_fakes import StaticSource
    from agent.todos import TodoService

    calendar_path = tmp_path / "calendar.db"
    todos_path = tmp_path / "todos.db"
    monkeypatch.setattr("common.state_dir.calendar_db", lambda **_kwargs: calendar_path)
    monkeypatch.setattr("common.state_dir.todos_db", lambda: todos_path)
    briefing = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    source = StaticSource([FetchedItem(
        source="elearning", account_id="student", source_id="quiz-1", title="测验",
        occurred_at="2026-09-09T07:00:00+08:00", payload={"due_at": "2026-09-12T20:00:00+08:00"},
    )], name="elearning", account_id="student")
    detail = BriefingPipeline(briefing, [source], clock=lambda: datetime.fromisoformat("2026-09-09T08:00:00+08:00")).run()
    assert detail["briefing"].status == "completed"
    events = CalendarService(calendar_path).list_events()
    assert events == []
    todos = TodoService(todos_path, calendar_path).list_todos()
    assert len(todos) == 1 and todos[0]["title"] == "测验"


def test_web_calendar_handlers_share_service_and_require_auth(service, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import patch
    from channel.desktop import desktop_channel as web_channel

    def call(handler, method="POST", body=None, params=None):
        with patch.object(web_channel.web, "data", return_value=json.dumps(body or {}).encode()), \
             patch.object(web_channel.web, "input", return_value=SimpleNamespace(**(params or {}))):
            return json.loads(getattr(handler(), method)())

    monkeypatch.setattr(web_channel, "_calendar_service", lambda: service)
    with patch.object(web_channel, "_require_auth") as auth, patch.object(web_channel.web, "header"):
        category = call(web_channel.CalendarCategoriesHandler, body={"name": "出行", "color": "#123ABC"})["category"]
        event = call(web_channel.CalendarEventsHandler, body={"title": "车票", "start_at": "2026-10-01T09:00+08:00",
            "end_at": "2026-10-01T10:00+08:00", "category_id": category["id"]})["event"]
        listed = call(web_channel.CalendarEventsHandler, "GET", params={"start": "", "end": "", "category_id": ""})
        assert listed["events"][0]["id"] == event["id"]
        assert call(web_channel.CalendarEventUpdateHandler, body={"id": event["id"], "title": "高铁"})["event"]["title"] == "高铁"
        assert call(web_channel.CalendarEventDeleteHandler, body={"id": event["id"]}) == {"status": "success"}
        assert auth.call_count == 5


def test_web_calendar_import_handlers_use_the_same_event_store(service, monkeypatch):
    from unittest.mock import patch
    from channel.desktop import desktop_channel as web_channel

    def call(handler, body):
        with patch.object(web_channel.web, "data", return_value=json.dumps(body).encode()):
            return json.loads(handler().POST())

    monkeypatch.setattr(web_channel, "_calendar_service", lambda: service)
    with patch.object(web_channel, "_require_auth") as auth, patch.object(web_channel.web, "header"):
        assert call(web_channel.CalendarHolidayImportHandler, {"year": 2026})["added"] == 13
        assert call(web_channel.CalendarSpecialDateHandler, {"title": "生日", "date": "2026-10-01",
            "annual": True, "timezone": "Asia/Shanghai"})["event"]["source_type"] == "special_date"
        assert call(web_channel.CalendarSpecialDateImportHandler, {"content": "title,date\n纪念日,2026-10-02\n",
            "format": "csv", "timezone": "Asia/Shanghai"})["added"] == 1
        bad = call(web_channel.CalendarSpecialDateImportHandler, {"content": "title,date\n错误,2026-02-30\n",
            "format": "csv", "timezone": "Asia/Shanghai"})
        assert bad["status"] == "error"
        assert auth.call_count == 4
    assert len(service.list_events()) == 15
