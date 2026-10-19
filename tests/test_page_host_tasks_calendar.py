"""PluginPageHost Bridge invoke for tasks and calendar restricted pages."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins.page_host import PluginPageHost


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setenv("STELLA_TODOS_PLUGIN", "1")
    monkeypatch.setenv("STELLA_CALENDAR_PLUGIN", "1")
    tasks = Path("stella-plugins-workspace/plugins/tasks")
    calendar = Path("stella-plugins-workspace/plugins/calendar")
    if not tasks.is_dir():
        tasks = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "tasks"
    if not calendar.is_dir():
        calendar = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "calendar"
    monkeypatch.setenv("STELLA_TASKS_PLUGIN_ROOT", str(tasks.resolve()))
    monkeypatch.setenv("STELLA_CALENDAR_PLUGIN_ROOT", str(calendar.resolve()))
    from core.services import calendar_facade, todos_facade

    monkeypatch.setattr(todos_facade, "_db_paths", lambda: (tmp_path / "todos.db", tmp_path / "cal.db"))
    monkeypatch.setattr(calendar_facade, "_db_path", lambda: tmp_path / "calendar.db")
    return PluginPageHost()


def test_tasks_bridge_create_and_list_focus(host):
    opened = host.open_page(
        plugin_id="stella.tasks", page_id="tasks.main",
        user_id="u1", instance_id="i1", generation=1,
    )
    created = host.invoke(
        channel_nonce=opened["channelNonce"],
        plugin_id="stella.tasks", page_id="tasks.main", generation=1,
        method="create_todo",
        input={"payload": {"title": "桥接事务"}},
    )
    assert created["title"] == "桥接事务"
    rows = host.invoke(
        channel_nonce=opened["channelNonce"],
        plugin_id="stella.tasks", page_id="tasks.main", generation=1,
        method="list_todos_focus",
        input={"today": "2026-10-20"},
    )
    assert any(row["id"] == created["id"] for row in rows)


def test_calendar_bridge_create_and_list(host):
    opened = host.open_page(
        plugin_id="stella.calendar", page_id="calendar.main",
        user_id="u1", instance_id="i1", generation=1,
    )
    created = host.invoke(
        channel_nonce=opened["channelNonce"],
        plugin_id="stella.calendar", page_id="calendar.main", generation=1,
        method="create_event",
        input={"payload": {
            "title": "桥接会议",
            "start_at": "2026-10-20T10:00:00+08:00",
            "end_at": "2026-10-20T11:00:00+08:00",
        }},
    )
    assert created["title"] == "桥接会议"
    rows = host.invoke(
        channel_nonce=opened["channelNonce"],
        plugin_id="stella.calendar", page_id="calendar.main", generation=1,
        method="list_events",
        input={"start": "2026-10-20T00:00:00+08:00", "end": "2026-10-21T00:00:00+08:00"},
    )
    assert any(row["id"] == created["id"] for row in rows)
