"""Apple Calendar synchronization with isolated Stella and fake EventKit data."""

import copy
import uuid
from datetime import datetime

import pytest

from agent.calendar import CalendarService
from agent.calendar.apple_sync import AppleCalendarSync
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


def test_sourced_upsert_can_apply_reconciled_remote_change(tmp_path):
    service = CalendarService(tmp_path / "calendar.db")
    imported = service.upsert_external_event("apple_calendar", "cal/a/occ-1", event_payload())
    service.update_event(imported["id"], {"title": "Previously synced edit"})
    updated = service.upsert_external_event("apple_calendar", "cal/a/occ-1", event_payload("Later remote edit"),
                                            event_id=imported["id"], reconciled=True)
    assert updated["title"] == "Later remote edit"
    assert updated["user_modified"] == 0


def test_sourced_upsert_is_available_through_application_port(tmp_path, monkeypatch):
    monkeypatch.setattr("common.state_dir.calendar_db", lambda **_kwargs: tmp_path / "calendar.db")
    port = Application.port("calendar")
    event = port.upsert_external_event("apple_calendar", "cal/a/occ-1", event_payload())
    assert port.get_event(event["id"])["source_key"] == "cal/a/occ-1"


def remote_event(calendar="a", identifier="event-1", title="Lecture", **overrides):
    event = {
        "calendar_id": calendar, "event_id": identifier, "external_id": f"uid-{identifier}",
        "occurrence_date": "2026-10-12T01:00:00Z", "stella_id": "",
        "title": title, "description": "Room 1", "location": "Campus",
        "start_at": "2026-10-12T01:00:00Z", "end_at": "2026-10-12T02:00:00Z",
        "all_day": False, "timezone": "Asia/Shanghai", "recurrence": {"frequency": "none", "days": [], "until": None},
        "is_detached": False, "last_modified": "2026-10-10T00:00:00Z", "writable": True,
    }
    event.update(overrides)
    return event


class FakeBridge:
    def __init__(self, rows=()):
        self.rows = [copy.deepcopy(row) for row in rows]
        self.authorization = "full_access"
        self.available = {"a", "b"}
        self.writes = []
        self.fail_next_write = False

    def call(self, op, **payload):
        if op == "status":
            return {"supported": True, "authorization": self.authorization}
        if op == "request_access":
            return {"authorization": self.authorization, "granted": self.authorization == "full_access"}
        if self.authorization != "full_access":
            raise RuntimeError("Calendar full access is required")
        if op == "calendars":
            return {"calendars": [{"id": key, "title": key, "source": "iCloud", "writable": True}
                                  for key in sorted(self.available)]}
        if op == "events":
            success = set(payload["calendar_ids"]) & self.available
            start = datetime.fromisoformat(payload["start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(payload["end"].replace("Z", "+00:00"))
            return {"events": [copy.deepcopy(row) for row in self.rows if row["calendar_id"] in success and
                               datetime.fromisoformat(row["end_at"].replace("Z", "+00:00")) > start and
                               datetime.fromisoformat(row["start_at"].replace("Z", "+00:00")) < end],
                    "successful_calendar_ids": sorted(success),
                    "failed_calendar_ids": sorted(set(payload["calendar_ids"]) - success)}
        if op == "lookup":
            matches = [row for row in self.rows if row["calendar_id"] == payload["calendar_id"] and
                       (row["event_id"] == payload.get("event_id") or
                        (row["external_id"] == payload.get("external_id") and
                         row["occurrence_date"] == payload.get("occurrence_date")))]
            return {"event": copy.deepcopy(matches[0]) if matches else None}
        if op == "upsert":
            if self.fail_next_write:
                self.fail_next_write = False
                raise RuntimeError("temporary EventKit failure")
            scan_start = datetime.fromisoformat(payload["scan_start"].replace("Z", "+00:00")) if payload.get("scan_start") else None
            scan_end = datetime.fromisoformat(payload["scan_end"].replace("Z", "+00:00")) if payload.get("scan_end") else None
            matching = next((row for row in self.rows if row["calendar_id"] == payload["calendar_id"] and
                             (row["event_id"] == payload.get("event_id") or
                              row["stella_id"] and row["stella_id"] == payload.get("stella_id") and
                              (scan_start is None or scan_start <= datetime.fromisoformat(row["start_at"].replace("Z", "+00:00")) < scan_end))), None)
            if matching is None:
                matching = remote_event(payload["calendar_id"], str(uuid.uuid4()))
                matching["stella_id"] = payload.get("stella_id", "")
                self.rows.append(matching)
            for key in ("title", "description", "start_at", "end_at", "all_day", "location"):
                matching[key] = payload[key]
            if payload.get("stella_id"):
                matching["recurrence"] = {"frequency": payload.get("repeat_frequency", "none"),
                                          "days": payload.get("repeat_days", []), "until": payload.get("repeat_until"),
                                          "interval": 1, "month_days": [], "months": [], "week_numbers": [],
                                          "year_days": [], "set_positions": []}
            self.writes.append((op, matching["event_id"]))
            return {"event": copy.deepcopy(matching)}
        if op == "delete":
            self.rows = [row for row in self.rows if row["event_id"] != payload["event_id"]]
            self.writes.append((op, payload["event_id"]))
            return {"deleted": True}
        raise AssertionError(op)


@pytest.fixture
def sync_env(tmp_path, monkeypatch):
    monkeypatch.setattr("common.state_dir.calendar_db", lambda **_kwargs: tmp_path / "calendar.db")
    bridge = FakeBridge([remote_event()])
    port = Application.port("calendar")
    sync = AppleCalendarSync(bridge=bridge, db_path=tmp_path / "sync.db", calendar_port=port,
                             clock=lambda: "2026-10-10T00:00:00+00:00")
    return sync, bridge, port, tmp_path


def connect(sync, calendars=("a",), direction="bidirectional"):
    sync.configure(list(calendars), direction)
    return sync.sync(manual=True)


def test_first_import_multiple_calendars_and_repeat_is_idempotent(sync_env):
    sync, bridge, port, _ = sync_env
    bridge.rows.append(remote_event("b", "event-2", "Tutorial"))
    first = connect(sync, ("a", "b"))
    assert first["imported"] == 2
    assert {row["title"] for row in port.list_events()} == {"Lecture", "Tutorial"}
    assert sync.sync(manual=True)["imported"] == 0
    assert len(port.list_events()) == 2
    assert all(row["source_type"] == "apple_calendar" for row in port.list_events())


def test_first_connection_keeps_preexisting_stella_events_local(sync_env):
    sync, bridge, port, _ = sync_env
    preexisting = port.create_event(event_payload("Old private event"))
    connect(sync)
    assert not any(row["stella_id"] == preexisting["id"] for row in bridge.rows)
    new = port.create_event(event_payload("New shared event"))
    assert sync.sync()["exported"] == 1
    assert any(row["stella_id"] == new["id"] for row in bridge.rows)


def test_local_create_exports_once_and_recovers_after_mapping_loss(sync_env):
    sync, bridge, port, tmp_path = sync_env
    connect(sync)
    own = port.create_event(event_payload("New Stella event"))
    assert sync.sync()["exported"] == 1
    assert sync.sync()["exported"] == 0
    assert len([row for row in bridge.rows if row["stella_id"] == own["id"]]) == 1
    with sync._connect() as db:
        db.execute("DELETE FROM mappings WHERE stella_id=?", (own["id"],))
    restarted = AppleCalendarSync(bridge=bridge, db_path=tmp_path / "sync.db", calendar_port=port,
                                  clock=lambda: "2026-10-10T00:00:00+00:00")
    assert restarted.sync()["exported"] == 0
    assert len([row for row in bridge.rows if row["stella_id"] == own["id"]]) == 1


def test_far_future_stella_event_recovers_without_duplicate_after_crash(sync_env):
    sync, bridge, port, tmp_path = sync_env
    connect(sync)
    own = port.create_event({"title": "2035 meeting", "start_at": "2035-01-01T09:00:00+08:00",
                             "end_at": "2035-01-01T10:00:00+08:00"})
    assert sync.sync()["exported"] == 1
    with sync._connect() as db:
        db.execute("DELETE FROM mappings WHERE stella_id=?", (own["id"],))
    restarted = AppleCalendarSync(bridge=bridge, db_path=tmp_path / "sync.db", calendar_port=port,
                                  clock=lambda: "2026-10-10T00:00:00+00:00")
    restarted.sync()
    assert len([row for row in bridge.rows if row["stella_id"] == own["id"]]) == 1


def test_remote_change_updates_import_and_relinked_identifier(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    original = port.list_events()[0]
    bridge.rows[0]["event_id"] = "new-event-identifier"
    bridge.rows[0]["title"] = "Rescheduled lecture"
    assert sync.sync()["updated"] == 1
    assert port.get_event(original["id"])["title"] == "Rescheduled lecture"
    assert len(port.list_events()) == 1


def test_move_between_selected_apple_calendars_keeps_stella_identity(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync, ("a", "b"))
    imported = port.list_events()[0]
    bridge.rows[0]["calendar_id"] = "b"
    bridge.rows[0]["event_id"] = "id-after-move"
    assert sync.sync()["imported"] == 0
    assert len(port.list_events()) == 1
    assert port.list_events()[0]["id"] == imported["id"]


def test_remote_deletion_removes_unchanged_import_but_not_unavailable_calendar(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    bridge.available.remove("a")
    bridge.rows.clear()
    sync.sync()
    assert len(port.list_events()) == 1
    bridge.available.add("a")
    assert sync.sync()["deleted_local"] == 0
    assert len(port.list_events()) == 1
    sync.clock = lambda: "2026-10-10T00:02:00+00:00"
    assert sync.sync()["deleted_local"] == 1
    assert port.list_events() == []


def test_unavailable_calendar_resets_pending_missing_confirmation(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    bridge.rows.clear()
    assert sync.sync()["deleted_local"] == 0
    bridge.available.remove("a")
    sync.clock = lambda: "2026-10-10T00:02:00+00:00"
    sync.sync()
    bridge.available.add("a")
    assert sync.sync()["deleted_local"] == 0
    assert len(port.list_events()) == 1


def test_local_edit_exports_imported_event_and_conflict_stays_unmodified(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    imported = port.list_events()[0]
    port.update_event(imported["id"], {"title": "My title"})
    bridge.rows[0]["title"] = "Apple title"
    result = sync.sync()
    assert result["conflicts"] == 1
    assert port.get_event(imported["id"])["title"] == "My title"
    assert bridge.rows[0]["title"] == "Apple title"
    sync.resolve_conflict(imported["id"], "keep_stella")
    assert bridge.rows[0]["title"] == "My title"


def test_local_edit_of_imported_event_writes_to_apple_and_remote_can_change_later(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    imported = port.list_events()[0]
    port.update_event(imported["id"], {"title": "My correction"})
    assert sync.sync()["exported"] == 1
    assert bridge.rows[0]["title"] == "My correction"
    bridge.rows[0]["title"] = "Later Apple correction"
    assert sync.sync()["updated"] == 1
    assert port.get_event(imported["id"])["title"] == "Later Apple correction"


def test_export_only_does_not_import_unlinked_apple_events(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync, direction="export")
    assert port.list_events() == []
    port.create_event(event_payload("Stella only"))
    assert sync.sync()["exported"] == 1
    assert len(bridge.rows) == 2


def test_local_delete_queues_apple_delete_until_explicit_confirmation(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    imported = port.list_events()[0]
    port.delete_event(imported["id"])
    assert sync.sync()["pending_deletions"] == 1
    assert len(bridge.rows) == 1
    assert sync.sync(manual=True, confirm_deletions=True)["deleted_remote"] == 1
    assert bridge.rows == []


def test_permission_revocation_and_retry_preserve_state(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    bridge.authorization = "denied"
    bridge.rows.clear()
    assert sync.sync()["status"] == "denied"
    assert len(port.list_events()) == 1
    bridge.authorization = "full_access"
    bridge.rows.append(remote_event())
    assert sync.sync()["status"] == "success"
    assert len(port.list_events()) == 1


def test_recurring_exception_and_all_day_preserve_distinct_occurrences(sync_env):
    sync, bridge, port, _ = sync_env
    bridge.rows = [
        remote_event(identifier="repeat", occurrence_date="2026-10-12T01:00:00Z"),
        remote_event(identifier="repeat-2", external_id="uid-repeat", occurrence_date="2026-10-13T01:00:00Z",
                     start_at="2026-10-13T03:00:00Z", end_at="2026-10-13T04:00:00Z", is_detached=True),
        remote_event(identifier="all-day", title="Festival", start_at="2026-10-14T16:00:00Z",
                     end_at="2026-10-15T16:00:00Z", all_day=True, timezone="Asia/Shanghai"),
    ]
    connect(sync)
    rows = port.list_events()
    assert len(rows) == 3
    assert len([row for row in rows if row["title"] == "Lecture"]) == 2
    assert next(row for row in rows if row["title"] == "Festival")["all_day"] == 1


def test_export_failure_retries_without_duplicate(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    own = port.create_event(event_payload("Retry"))
    bridge.fail_next_write = True
    assert sync.sync()["status"] == "error"
    assert sync.sync()["exported"] == 1
    assert len([row for row in bridge.rows if row["stella_id"] == own["id"]]) == 1


def test_direction_filter_and_disconnect_keep_imported_stella_data(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync, direction="import")
    port.create_event(event_payload("Local only"))
    sync.sync()
    assert not any(row["stella_id"] for row in bridge.rows)
    sync.disconnect()
    assert sync.status()["connected"] is False
    assert len(port.list_events()) == 2


def test_two_events_with_same_external_uid_and_occurrence_remain_distinct(sync_env):
    sync, bridge, port, _ = sync_env
    bridge.rows.append(remote_event(identifier="event-duplicate", external_id="uid-event-1"))
    assert connect(sync)["imported"] == 2
    assert len(port.list_events()) == 2


def test_repeated_stella_series_occurrences_do_not_duplicate_mapping(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    own = port.create_event({**event_payload("Weekly"), "repeat_frequency": "weekly", "repeat_days": [0],
                             "repeat_timezone": "Asia/Shanghai"})
    assert sync.sync()["exported"] == 1
    first = next(row for row in bridge.rows if row["stella_id"] == own["id"])
    bridge.rows.append({**first, "event_id": "next-occurrence", "occurrence_date": "2026-10-19T01:00:00Z",
                        "start_at": "2026-10-19T01:00:00Z", "end_at": "2026-10-19T02:00:00Z"})
    assert sync.sync()["status"] == "success"
    assert len([row for row in port.list_events() if row["title"] == "Weekly"]) == 1


def test_detached_apple_occurrence_replaces_only_that_stella_series_instance(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    own = port.create_event({**event_payload("Weekly"), "repeat_frequency": "weekly", "repeat_days": [0],
                             "repeat_timezone": "Asia/Shanghai"})
    sync.sync()
    first = next(row for row in bridge.rows if row["stella_id"] == own["id"])
    bridge.rows.append({**first, "event_id": "detached-1", "occurrence_date": "2026-10-19T01:00:00Z",
                        "start_at": "2026-10-19T03:00:00Z", "end_at": "2026-10-19T04:00:00Z",
                        "title": "Moved occurrence", "is_detached": True})
    assert sync.sync()["imported"] == 1
    week = port.list_events("2026-10-19T00:00:00+08:00", "2026-10-20T00:00:00+08:00")
    assert [row["title"] for row in week] == ["Moved occurrence"]
    assert port.get_event(own["id"])["repeat_frequency"] == "weekly"


def test_conflict_resolution_does_not_collapse_stella_recurring_series(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    own = port.create_event({**event_payload("Weekly"), "repeat_frequency": "weekly", "repeat_days": [0],
                             "repeat_timezone": "Asia/Shanghai"})
    sync.sync()
    remote = next(row for row in bridge.rows if row["stella_id"] == own["id"])
    remote["title"] = "Changed in Apple"
    assert sync.sync()["conflicts"] == 1
    with pytest.raises(ValueError, match="recurring series"):
        sync.resolve_conflict(own["id"], "keep_apple")
    assert port.get_event(own["id"])["repeat_frequency"] == "weekly"


def test_apple_recurrence_interval_change_is_reported_as_conflict(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    own = port.create_event({**event_payload("Weekly"), "repeat_frequency": "weekly", "repeat_days": [0],
                             "repeat_timezone": "Asia/Shanghai"})
    sync.sync()
    remote = next(row for row in bridge.rows if row["stella_id"] == own["id"])
    remote["recurrence"] = {"frequency": "weekly", "days": [0], "until": None, "interval": 2,
                            "month_days": [], "months": [], "week_numbers": [], "year_days": [], "set_positions": []}
    assert sync.sync()["conflicts"] == 1
    assert port.get_event(own["id"])["repeat_frequency"] == "weekly"


def test_apple_recurrence_occurrence_count_change_is_not_silent(sync_env):
    sync, bridge, port, _ = sync_env
    connect(sync)
    own = port.create_event({**event_payload("Weekly"), "repeat_frequency": "weekly", "repeat_days": [0],
                             "repeat_timezone": "Asia/Shanghai"})
    sync.sync()
    remote = next(row for row in bridge.rows if row["stella_id"] == own["id"])
    remote["recurrence"]["count"] = 3
    assert sync.sync()["conflicts"] == 1
