"""Calendar storage, agent access, and briefing routing share one SQLite model."""

import json
import sqlite3
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


def test_briefing_handoff_is_idempotent_and_preserves_user_edits(service):
    item = SimpleNamespace(source="elearning", account_id="student", source_id="quiz-1",
        source_item_id="src-1", section="action", title="课程测验", snippet="周五截止",
        payload={"due_at": "2026-10-02T20:00:00+08:00"}, url="https://example.test/quiz",
        id="item-1")
    detail = {"briefing": SimpleNamespace(id="briefing-1"), "items": [item], "mail": []}
    assert service.ingest_briefing(detail) == 1
    assert service.ingest_briefing(detail) == 1
    assert len(service.list_events()) == 1
    event = service.list_events()[0]
    assert event["category_id"] == "study"
    with sqlite3.connect(service.db_path) as db:
        assert db.execute("SELECT destination FROM agenda_handoffs ORDER BY destination").fetchall() == [("calendar",), ("task",)]
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
    assert len(service.list_events()) == 1
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
    service.ingest_briefing({"briefing": SimpleNamespace(id="briefing-4"), "items": [item], "mail": []})
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
        assert db.execute("SELECT count(*) FROM agenda_handoffs WHERE destination='task'").fetchone()[0] == 2


def test_agent_tool_discovery_and_permissions(service):
    manager = ToolManager()
    manager._load_tools_from_init()
    assert manager.tool_classes["calendar"] is CalendarTool
    tool = CalendarTool(service=service)
    result = tool.execute({"action": "create", "title": "会议", "start_at": "2026-10-01T09:00+08:00", "end_at": "2026-10-01T10:00+08:00"})
    assert json.loads(result.result)["event"]["title"] == "会议"
    assert check_tool_call("read-only", "calendar", {"action": "list"})
    assert not check_tool_call("read-only", "calendar", {"action": "create"})
    assert check_tool_call("workspace-write", "calendar", {"action": "create"})

@pytest.mark.usefixtures("deterministic_briefing_generator")
def test_briefing_pipeline_routes_due_item_to_calendar(tmp_path, monkeypatch):
    from datetime import datetime
    from agent.briefing.pipeline import BriefingPipeline
    from agent.briefing.service import BriefingService
    from agent.briefing.sources.base import FetchedItem
    from agent.briefing.store import BriefingStore
    from briefing_fakes import StaticSource

    calendar_path = tmp_path / "calendar.db"
    monkeypatch.setattr("common.state_dir.calendar_db", lambda: calendar_path)
    briefing = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    source = StaticSource([FetchedItem(
        source="elearning", account_id="student", source_id="quiz-1", title="测验",
        occurred_at="2026-09-09T07:00:00+08:00", payload={"due_at": "2026-09-12T20:00:00+08:00"},
    )], name="elearning", account_id="student")
    detail = BriefingPipeline(briefing, [source], clock=lambda: datetime.fromisoformat("2026-09-09T08:00:00+08:00")).run()
    assert detail["briefing"].status == "completed"
    events = CalendarService(calendar_path).list_events()
    assert len(events) == 1 and events[0]["title"] == "测验"
    with sqlite3.connect(calendar_path) as db:
        assert {row[0] for row in db.execute("SELECT destination FROM agenda_handoffs")} == {"task", "calendar"}


def test_web_calendar_handlers_share_service_and_require_auth(service, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import patch
    from channel.web import web_channel

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
