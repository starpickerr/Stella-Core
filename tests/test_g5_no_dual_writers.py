"""G5: when domain plugins are enabled, host paths must not construct legacy writers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


from application import Application, RequestContext


def _assert_no_legacy_todo_service():
    import importlib.util

    import agent.todos

    assert not hasattr(agent.todos, "TodoService")
    assert importlib.util.find_spec("agent.todos.service") is None


def test_dispatch_todo_reminder_uses_plugin_facade_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("STELLA_TODOS_PLUGIN", "1")
    monkeypatch.setenv(
        "STELLA_TODOS_PLUGIN_ROOT",
        str(Path("stella-plugins-workspace/plugins/tasks").resolve()),
    )
    calls = []

    class _Facade:
        def scheduled_reminder_delivery(self, todo_id, expected_at):
            calls.append((todo_id, expected_at))
            return None

    monkeypatch.setattr(
        "core.services.todos_facade.TodosPluginFacade",
        lambda: _Facade(),
    )
    # The legacy constructor cannot run: Core no longer ships a Tasks service.
    _assert_no_legacy_todo_service()
    result = Application.dispatch_todo_reminder(
        "t1",
        "2026-01-01T00:00:00+00:00",
        RequestContext(source="scheduler", user_id="u", agent_id="a", session_id="s"),
    )
    assert result is None
    assert calls == [("t1", "2026-01-01T00:00:00+00:00")]


def test_todos_facade_reconcile_does_not_construct_legacy_service(monkeypatch, tmp_path):
    from core.services.todos_facade import TodosPluginFacade

    monkeypatch.setenv("STELLA_TODOS_PLUGIN", "1")
    _assert_no_legacy_todo_service()
    calls = []

    def fake_invoke(method, params, *, db_path, legacy_calendar_db_path=None):
        calls.append(method)
        if method == "pending_scheduler_links":
            return {"status": "succeeded", "value": []}
        return {"status": "succeeded", "value": {}}

    monkeypatch.setattr("core.services.todos_gateway.invoke_todos", fake_invoke)
    TodosPluginFacade._reconcile_host_scheduler(tmp_path / "todos.db", tmp_path / "calendar.db")
    assert calls == ["pending_scheduler_links"]


def test_briefing_actions_uses_public_default_services(monkeypatch):
    from agent.briefing.actions import BriefingActions

    todo = MagicMock(name="todo_facade")
    cal = MagicMock(name="cal_facade")
    monkeypatch.setattr("core.services.todos_public.default_service", lambda: todo)
    monkeypatch.setattr("core.services.calendar_public.default_service", lambda: cal)
    _assert_no_legacy_todo_service()
    import importlib.util
    assert importlib.util.find_spec('agent.calendar.service') is None
    actions = BriefingActions.__new__(BriefingActions)
    actions.store = MagicMock()
    actions._todos = None
    actions._calendar = None
    assert actions.todos is todo
    assert actions.calendar is cal
