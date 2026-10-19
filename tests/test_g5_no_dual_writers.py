"""G5: when domain plugins are enabled, host paths must not construct legacy writers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from application import Application, RequestContext


def test_dispatch_todo_reminder_uses_plugin_facade_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("STELLA_TODOS_PLUGIN", "1")
    monkeypatch.setenv(
        "STELLA_TODOS_PLUGIN_ROOT",
        str(Path("stella-plugins-workspace/plugins/tasks").resolve()),
    )
    calls = []

    class _Facade:
        def dispatch_scheduled_reminder(self, todo_id, expected_at):
            calls.append((todo_id, expected_at))
            return {"dispatched": True, "todoId": todo_id}

    monkeypatch.setattr(
        "core.services.todos_facade.TodosPluginFacade",
        lambda: _Facade(),
    )
    # Legacy constructor must not run.
    monkeypatch.setattr(
        "agent.todos.TodoService",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("legacy TodoService")),
    )
    result = Application.dispatch_todo_reminder(
        "t1",
        "2026-01-01T00:00:00+00:00",
        RequestContext(source="scheduler", user_id="u", agent_id="a", session_id="s"),
    )
    assert result["dispatched"] is True
    assert calls == [("t1", "2026-01-01T00:00:00+00:00")]


def test_briefing_actions_uses_public_default_services(monkeypatch):
    from agent.briefing.actions import BriefingActions

    todo = MagicMock(name="todo_facade")
    cal = MagicMock(name="cal_facade")
    monkeypatch.setattr("core.services.todos_public.default_service", lambda: todo)
    monkeypatch.setattr("core.services.calendar_public.default_service", lambda: cal)
    monkeypatch.setattr(
        "agent.todos.service.TodoService",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("legacy todos")),
    )
    monkeypatch.setattr(
        "agent.calendar.service.CalendarService",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("legacy calendar")),
    )
    actions = BriefingActions.__new__(BriefingActions)
    actions.store = MagicMock()
    actions._todos = None
    actions._calendar = None
    assert actions.todos is todo
    assert actions.calendar is cal
