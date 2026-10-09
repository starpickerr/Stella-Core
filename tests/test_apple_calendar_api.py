"""Desktop API contract for the Apple Calendar connection."""

import json
from unittest.mock import patch

from tests.test_apple_calendar_sync import AppleCalendarSync, FakeBridge, remote_event


def test_application_owns_calendar_manager_and_one_time_requires_exact_ids(tmp_path, monkeypatch):
    from application import Application

    monkeypatch.setattr("common.state_dir.calendar_db", lambda **_kwargs: tmp_path / "calendar.db")
    Application.reset_apple_managers()
    first = Application.apple_calendar()
    assert first is Application.apple_calendar()
    assert first.db_path == tmp_path / "apple_sync.db"
    Application.reset_apple_managers()
    bridge = FakeBridge([remote_event()])
    sync = AppleCalendarSync(bridge=bridge, db_path=tmp_path / "apple.db",
                             calendar_port=Application.port("calendar"),
                             clock=lambda: "2026-10-10T00:00:00+00:00")
    with __import__("pytest").raises(ValueError, match="event_id"):
        sync.one_time("import", "a", [], confirm=True)
    with __import__("pytest").raises(ValueError, match="confirmation"):
        sync.one_time("import", "a", ["event-1"], confirm=False)
    result = sync.one_time("import", "a", ["event-1"], confirm=True)
    assert result["imported"] == 1
    assert sync.status()["connected"] is False
    assert sync.one_time("import", "a", ["event-1"], confirm=True)["imported"] == 0
    with __import__("pytest").raises(KeyError):
        sync.one_time("import", "a", ["invented"], confirm=True)


def test_calendar_items_requires_selected_source_and_time_window(tmp_path):
    from application import Application

    bridge = FakeBridge([remote_event()])
    sync = AppleCalendarSync(bridge=bridge, db_path=tmp_path / "apple.db",
                             calendar_port=Application.port("calendar"))
    with __import__("pytest").raises(ValueError, match="window"):
        sync.items("a")
    rows = sync.items("a", "2026-10-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00")
    assert rows[0]["event_id"] == "event-1"
    with __import__("pytest").raises(ValueError, match="unavailable"):
        sync.items("invented", "2026-10-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00")


def test_calendar_one_time_export_uses_explicit_event_id_and_stays_disconnected(tmp_path, monkeypatch):
    from application import Application

    monkeypatch.setattr("common.state_dir.calendar_db", lambda **_kwargs: tmp_path / "calendar.db")
    bridge = FakeBridge([])
    port = Application.port("calendar")
    own = port.create_event({"title": "Report", "start_at": "2026-10-12T09:00:00+08:00",
                             "end_at": "2026-10-12T10:00:00+08:00"})
    sync = AppleCalendarSync(bridge=bridge, db_path=tmp_path / "apple.db", calendar_port=port)
    assert sync.preview_items("export", "a", [own["id"]])["new"] == 1
    assert sync.one_time("export", "a", [own["id"]], confirm=True)["exported"] == 1
    assert bridge.upsert_requests[-1]["stella_id"] == own["id"]
    assert sync.status()["connected"] is False
    assert sync.one_time("export", "a", [own["id"]], confirm=True)["exported"] == 0


def test_desktop_calendar_inventory_uses_application_manager(tmp_path, monkeypatch):
    from channel.desktop import desktop_channel as web_channel
    from application import Application

    sync = AppleCalendarSync(bridge=FakeBridge([remote_event()]), db_path=tmp_path / "apple.db",
                             calendar_port=Application.port("calendar"))
    monkeypatch.setattr(Application, "apple_calendar", staticmethod(lambda: sync))
    body = {"calendar_id": "a", "start": "2026-10-01T00:00:00+00:00",
            "end": "2026-11-01T00:00:00+00:00"}
    with patch.object(web_channel, "_require_auth") as auth, patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "data", return_value=json.dumps(body).encode()):
        result = json.loads(web_channel.AppleCalendarItemsHandler().POST())
    assert result["items"][0]["event_id"] == "event-1"
    auth.assert_called_once()


def test_apple_calendar_routes_use_authenticated_shared_sync(tmp_path, monkeypatch):
    from channel.desktop import desktop_channel as web_channel
    from application import Application

    monkeypatch.setattr("common.state_dir.calendar_db", lambda **_kwargs: tmp_path / "calendar.db")
    bridge = FakeBridge([remote_event()])
    sync = AppleCalendarSync(bridge=bridge, db_path=tmp_path / "sync.db", calendar_port=Application.port("calendar"),
                             clock=lambda: "2026-10-10T00:00:00+00:00")
    monkeypatch.setattr(web_channel, "_apple_calendar_sync", lambda: sync)

    def call(handler, method="POST", body=None):
        with patch.object(web_channel.web, "data", return_value=json.dumps(body or {}).encode()):
            return json.loads(getattr(handler(), method)())

    with patch.object(web_channel, "_require_auth") as auth, patch.object(web_channel.web, "header"):
        status = call(web_channel.AppleCalendarStatusHandler, "GET")
        assert status["connection"]["connected"] is False
        assert call(web_channel.AppleCalendarAccessHandler)["connection"]["authorization"] == "full_access"
        selection = {"calendar_ids": ["a"], "direction": "bidirectional"}
        prepared = call(web_channel.AppleCalendarScopePreviewHandler, body=selection)
        assert prepared["preview"]["new"] == 1
        configured = call(web_channel.AppleCalendarConfigureHandler,
                          body={**selection, "confirm": True, "preview_token": prepared["preview_token"]})
        assert configured["result"]["imported"] == 1
        assert configured["connection"]["connected"] is True
        assert call(web_channel.AppleCalendarSyncHandler, body={"confirm_deletions": False})["result"]["status"] == "success"
        assert call(web_channel.AppleCalendarDisconnectHandler)["connection"]["connected"] is False
        assert auth.call_count == 6


def test_local_calendar_delete_confirmation_reaches_sync_service(tmp_path, monkeypatch):
    from channel.desktop import desktop_channel as web_channel
    from application import Application

    monkeypatch.setattr("common.state_dir.calendar_db", lambda **_kwargs: tmp_path / "calendar.db")
    bridge = FakeBridge([remote_event()])
    port = Application.port("calendar")
    sync = AppleCalendarSync(bridge=bridge, db_path=tmp_path / "sync.db", calendar_port=port,
                             clock=lambda: "2026-10-10T00:00:00+00:00")
    sync.configure(["a"], "bidirectional")
    sync.sync()
    bridge.rows.clear()
    sync.sync()
    sync.clock = lambda: "2026-10-10T00:02:00+00:00"
    assert sync.sync()["pending_local_deletions"] == 1
    monkeypatch.setattr(web_channel, "_apple_calendar_sync", lambda: sync)
    with patch.object(web_channel, "_require_auth"), patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "data", return_value=b'{"confirm_local_deletions": true}'):
        result = json.loads(web_channel.AppleCalendarSyncHandler().POST())
    assert result["result"]["deleted_local"] == 1
    assert port.list_events() == []
