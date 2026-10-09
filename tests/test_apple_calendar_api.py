"""Desktop API contract for the Apple Calendar connection."""

import json
from unittest.mock import patch

from tests.test_apple_calendar_sync import AppleCalendarSync, FakeBridge, remote_event


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
        configured = call(web_channel.AppleCalendarConfigureHandler,
                          body={"calendar_ids": ["a"], "direction": "bidirectional"})
        assert configured["result"]["imported"] == 1
        assert configured["connection"]["connected"] is True
        assert call(web_channel.AppleCalendarSyncHandler, body={"confirm_deletions": False})["result"]["status"] == "success"
        assert call(web_channel.AppleCalendarDisconnectHandler)["connection"]["connected"] is False
        assert auth.call_count == 5


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
