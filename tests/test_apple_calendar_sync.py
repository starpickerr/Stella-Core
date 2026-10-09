"""Apple Calendar synchronization with isolated Stella and fake EventKit data."""

import pytest

from agent.calendar import CalendarService
from application import Application


def event_payload(title="Lecture"):
    return {
        "title": title, "description": "Room 1", "location": "Campus",
        "start_at": "2026-10-12T09:00:00+08:00",
        "end_at": "2026-10-12T10:00:00+08:00", "all_day": False,
    }


def test_sourced_upsert_is_idempotent_and_preserves_provenance(tmp_path):
    service = CalendarService(tmp_path / "calendar.db")
    first = service.upsert_external_event("apple_calendar", "cal/a/occ-1", event_payload())
    again = service.upsert_external_event("apple_calendar", "cal/a/occ-1", event_payload("New title"))
    assert first["id"] == again["id"]
    assert again["title"] == "New title"
    assert again["source_type"] == "apple_calendar"
    assert again["source_key"] == "cal/a/occ-1"
    assert len(service.list_events()) == 1


def test_sourced_upsert_keeps_local_edit_and_rejects_wrong_provider(tmp_path):
    service = CalendarService(tmp_path / "calendar.db")
    imported = service.upsert_external_event("apple_calendar", "cal/a/occ-1", event_payload())
    service.update_event(imported["id"], {"title": "My correction"})
    with pytest.raises(ValueError, match="locally modified"):
        service.upsert_external_event("apple_calendar", "cal/a/occ-1", event_payload("Remote title"))
    assert service.get_event(imported["id"])["title"] == "My correction"
    with pytest.raises(ValueError, match="provider"):
        service.upsert_external_event("other", "k", event_payload())


def test_sourced_upsert_is_available_through_application_port(tmp_path, monkeypatch):
    monkeypatch.setattr("common.state_dir.calendar_db", lambda **_kwargs: tmp_path / "calendar.db")
    port = Application.port("calendar")
    event = port.upsert_external_event("apple_calendar", "cal/a/occ-1", event_payload())
    assert port.get_event(event["id"])["source_key"] == "cal/a/occ-1"
