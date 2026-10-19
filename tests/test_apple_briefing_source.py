import pytest

from application import Application
from agent.briefing.sources.calendar_agenda import CalendarAgendaSource
from agent.briefing.sources import registry

pytestmark = pytest.mark.usefixtures("calendar_plugin_env")


def test_connected_apple_calendar_makes_upcoming_stella_events_available_to_briefing(tmp_path, monkeypatch):
    monkeypatch.setattr("common.state_dir.calendar_db", lambda **_kwargs: tmp_path / "calendar.db")
    port = Application.port("calendar")
    port.upsert_external_event("apple_calendar", "source-1", {
        "title": "Apple meeting", "description": "Discussion", "location": "Room 2",
        "start_at": "2026-10-10T09:00:00+08:00", "end_at": "2026-10-10T10:00:00+08:00",
        "all_day": False})
    port.create_event({"title": "Stella planning", "start_at": "2026-10-10T11:00:00+08:00",
                       "end_at": "2026-10-10T12:00:00+08:00"})
    source = CalendarAgendaSource(calendar_port=port)
    result = source.fetch({"until": "2026-10-10T00:00:00Z"})
    assert {item.title for item in result.items} == {"Apple meeting", "Stella planning"}
    assert all(item.occurred_at == "2026-10-10T00:00:00Z" for item in result.items)
    assert all("start_at" not in item.payload for item in result.items)
    assert len(port.list_events()) == 2


def test_calendar_source_is_registered_only_when_connected(monkeypatch):
    monkeypatch.setattr(registry.settings, "email_sources", lambda: [])
    monkeypatch.setattr(registry.elearning_settings, "elearning_sources", lambda: [])
    monkeypatch.setattr(registry, "apple_calendar_connected", lambda: False)
    assert registry.configured_sources() == []
    monkeypatch.setattr(registry, "apple_calendar_connected", lambda: True)
    assert [source.name for source in registry.configured_sources()] == ["calendar_agenda"]
