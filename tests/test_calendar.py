"""Core tool, desktop and Briefing integration with the real Calendar worker."""
import json
import pytest
from agent.permission.gateway import SecurityGateway
from agent.tools.calendar.calendar_tool import CalendarTool
from agent.tools.tool_manager import ToolManager

check_tool_call = SecurityGateway.check

@pytest.fixture
def service(calendar_plugin):
    return calendar_plugin

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
def test_briefing_pipeline_routes_due_item_to_todos(tmp_path, monkeypatch, todos_plugin_env, calendar_plugin):
    from datetime import datetime
    from agent.briefing.pipeline import BriefingPipeline
    from tests.briefing_domain import BriefingService
    from agent.briefing.sources.base import FetchedItem
    from tests.briefing_domain import BriefingStore
    from briefing_fakes import StaticSource
    from core.services.todos_facade import TodosPluginFacade

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
    events = calendar_plugin.list_events()
    assert events == []
    todos = TodosPluginFacade().list_todos()
    assert todos == []
    assert detail['actions'][detail['items'][0].id]['todo']['state'] == 'pending'
    receipt = briefing.update_action(detail['items'][0].id, {'operation':'create', 'kind':'todo'})
    assert receipt['state'] == 'succeeded'
    todos = TodosPluginFacade().list_todos()
    assert len(todos) == 1 and todos[0]['title'] == '测验'
    assert calendar_plugin.list_events() == []

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
