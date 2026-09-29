"""Briefings use the existing scheduler and tool dispatch, never a private loop."""
import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent.briefing.pipeline import BriefingPipeline
from agent.briefing.scheduler import DAILY_BRIEFING_TASK_ID, ensure_daily_briefing_task
from agent.briefing.service import BriefingService
from agent.briefing.sources.static import StaticSource
from agent.briefing.store import BriefingStore
from agent.scheduler import SchedulerService, TaskStore
from agent.scheduler import integration
from agent.tools.base_tool import ToolResult
from agent.tools.briefing.briefing_tool import BriefingTool
from agent.tools.tool_manager import ToolManager


@pytest.fixture
def clock(monkeypatch):
    current = [datetime(2026, 9, 9, 7, 59, 59)]

    class Clock(datetime):
        @classmethod
        def now(cls):
            return current[0]

    monkeypatch.setattr("agent.scheduler.service.datetime", Clock)
    return current


@pytest.fixture
def store(tmp_path):
    return TaskStore(str(tmp_path / "scheduler" / "tasks.json"))


def test_default_is_once_only_and_preserves_edits_pause_and_deletion(store):
    now = datetime(2026, 9, 9, 10)
    assert ensure_daily_briefing_task(store, now)
    task = store.get_task(DAILY_BRIEFING_TASK_ID)
    assert task["next_run_at"] == "2026-09-09T08:00:00"
    assert task["action"] == {"type": "tool_call", "call_name": "briefing",
                              "call_params": {"action": "run", "operation": "create"}, "silent": True}
    store.update_task(task["id"], {"enabled": False, "schedule": {"type": "cron", "expression": "0 9 * * *"}})
    assert not ensure_daily_briefing_task(store, now)
    assert store.get_task(task["id"])["enabled"] is False
    assert store.get_task(task["id"])["schedule"]["expression"] == "0 9 * * *"
    store.add_task({"id": "other", "name": "other task"})
    store.delete_task(task["id"])
    reopened = TaskStore(store.store_path)
    assert not ensure_daily_briefing_task(reopened, now + timedelta(days=1))
    assert [task["id"] for task in reopened.list_tasks()] == ["other"]
    assert json.loads(open(store.store_path).read())["initialized_defaults"] == [DAILY_BRIEFING_TASK_ID]


def test_default_keeps_an_existing_task_without_replacing_it(store):
    store.add_task({"id": DAILY_BRIEFING_TASK_ID, "name": "custom", "enabled": False})
    assert not ensure_daily_briefing_task(store, datetime(2026, 9, 9, 7))
    assert store.get_task(DAILY_BRIEFING_TASK_ID)["name"] == "custom"


def test_shared_scheduler_at_eight_catches_up_and_skips_existing(store, clock, tmp_path, monkeypatch,
        deterministic_briefing_generator):
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    tool = BriefingTool(service=service)
    monkeypatch.setattr(tool, "_get_pipeline", lambda svc: BriefingPipeline(svc, [StaticSource([])],
        clock=lambda: clock[0].replace(tzinfo=timezone(timedelta(hours=8)))))
    monkeypatch.setattr(ToolManager, "create_tool", lambda self, name: tool)
    monkeypatch.setattr("agent.briefing.settings.public_mailboxes", lambda: {"configured": True})
    ensure_daily_briefing_task(store, clock[0])
    scheduler = SchedulerService(store, lambda task: integration._execute_tool_call(task, None))
    scheduler._check_and_execute_tasks()
    assert not service.list_briefings()
    clock[0] = datetime(2026, 9, 9, 8)
    scheduler._check_and_execute_tasks()
    assert service.get_briefing("brf-2026-09-09-morning")["revisions"][0]["trigger"] == "scheduled"
    # Run now or an extra tick reuses today's successful document.
    assert integration._execute_tool_call(store.get_task(DAILY_BRIEFING_TASK_ID), None)
    scheduler._check_and_execute_tasks()
    assert len(service.get_briefing("brf-2026-09-09-morning")["revisions"]) == 1
    # A later failed manual update still has a successful daily document.
    BriefingPipeline(service, [StaticSource(error=RuntimeError("offline"))],
        clock=lambda: clock[0].replace(tzinfo=timezone(timedelta(hours=8)))).run(operation="update")
    monkeypatch.setattr("agent.briefing.settings.public_mailboxes", lambda: {"configured": False})
    assert integration._execute_tool_call(store.get_task(DAILY_BRIEFING_TASK_ID), None)
    assert len(service.get_briefing("brf-2026-09-09-morning")["revisions"]) == 2
    monkeypatch.setattr("agent.briefing.settings.public_mailboxes", lambda: {"configured": True})
    # Sleep across several days only generates the day we wake up.
    clock[0] = datetime(2026, 9, 12, 15)
    scheduler._check_and_execute_tasks()
    assert len(service.list_briefings()) == 2
    assert store.get_task(DAILY_BRIEFING_TASK_ID)["next_run_at"] == "2026-09-13T08:00:00"


def test_shared_scheduler_waits_for_mailboxes_and_retries_failures(store, clock, tmp_path, monkeypatch,
        deterministic_briefing_generator):
    clock[0] = datetime(2026, 9, 9, 8)
    configured = [False]
    sources = [StaticSource(error=RuntimeError("offline"))]
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    tool = BriefingTool(service=service)
    monkeypatch.setattr(tool, "_get_pipeline", lambda svc: BriefingPipeline(svc, sources,
        clock=lambda: clock[0].replace(tzinfo=timezone(timedelta(hours=8)))))
    monkeypatch.setattr(ToolManager, "create_tool", lambda self, name: tool)
    monkeypatch.setattr("agent.briefing.settings.public_mailboxes", lambda: {"configured": configured[0]})
    ensure_daily_briefing_task(store, clock[0])
    scheduler = SchedulerService(store, lambda task: integration._execute_tool_call(task, None))
    scheduler._check_and_execute_tasks()
    assert not service.list_briefings()
    configured[0] = True
    clock[0] = datetime(2026, 9, 9, 8, 1)
    scheduler._check_and_execute_tasks()
    assert not service.list_briefings()
    clock[0] = datetime(2026, 9, 9, 8, 5)
    scheduler._check_and_execute_tasks()
    failed = service.get_briefing("brf-2026-09-09-morning")
    assert failed["briefing"].generated_at is None
    sources[0] = StaticSource([])
    clock[0] = datetime(2026, 9, 9, 8, 10)
    scheduler._check_and_execute_tasks()
    assert service.get_briefing("brf-2026-09-09-morning")["briefing"].status == "completed"
    task = store.get_task(DAILY_BRIEFING_TASK_ID)
    assert task["retry_at"] is None
    assert task["last_run_at"] == "2026-09-09T08:10:00"


def test_overdue_before_eight_waits_until_today_and_ordinary_tasks_keep_grace_period(store):
    ensure_daily_briefing_task(store, datetime(2026, 9, 8, 8))
    scheduler = SchedulerService(store, lambda task: True)
    task = store.get_task(DAILY_BRIEFING_TASK_ID)
    assert not scheduler._is_task_due(task, datetime(2026, 9, 12, 7))
    assert store.get_task(task["id"])["next_run_at"] == "2026-09-12T08:00:00"
    assert scheduler._is_task_due(store.get_task(task["id"]), datetime(2026, 9, 12, 16))
    store.add_task({**task, "id": "ordinary", "catch_up": None})
    assert not scheduler._is_task_due(store.get_task("ordinary"), datetime(2026, 9, 12, 16))
    assert store.get_task("ordinary")["next_run_at"] == "2026-09-13T08:00:00"


def test_silent_tool_dispatch_has_no_delivery_and_propagates_errors(monkeypatch):
    task = {"id": "briefing", "action": {"type": "tool_call", "call_name": "briefing", "silent": True}}
    tool = SimpleNamespace(execute=lambda params: ToolResult.success("saved"))
    monkeypatch.setattr(ToolManager, "create_tool", lambda self, name: tool)
    monkeypatch.setattr("channel.channel_factory.create_channel", lambda *args: pytest.fail("silent task must not send"))
    cancel_event = threading.Event()
    assert integration._execute_tool_call(task, None, "default", cancel_event)
    assert tool.current_context.get("is_scheduled_task") is True
    assert tool.current_context.get("agent_id") == "default"
    assert tool.cancel_event is cancel_event
    tool.execute = lambda params: ToolResult.fail("model failure")
    assert not integration._execute_tool_call(task, None)


def test_desktop_boot_registers_in_existing_scheduler_and_bypasses_delivery_readiness(tmp_path, monkeypatch):
    bridge = SimpleNamespace(agent_registry=SimpleNamespace(
        get=lambda agent_id: SimpleNamespace(id="default"), default_agent_id="default"))
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    monkeypatch.setattr(SchedulerService, "start", lambda service: setattr(service, "running", True))
    monkeypatch.setattr(integration, "_is_channel_ready", lambda *args: pytest.fail("silent task must not need a chat session"))
    monkeypatch.setattr(ToolManager, "create_tool", lambda self, name: SimpleNamespace(execute=lambda params: ToolResult.success("saved")))
    integration.reset_scheduler_services(stop=False)
    try:
        assert integration.init_scheduler(bridge, str(tmp_path), "default")
        scheduler = integration.get_scheduler_service(str(tmp_path))
        task = scheduler.task_store.get_task(DAILY_BRIEFING_TASK_ID)
        assert scheduler.execute_callback(task)
        assert integration.init_scheduler(bridge, str(tmp_path), "default")
        assert integration.get_scheduler_service(str(tmp_path)) is scheduler
        assert len(scheduler.task_store.list_tasks()) == 1
    finally:
        integration.reset_scheduler_services(stop=False)
