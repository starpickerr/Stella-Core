"""Authenticated desktop API and explicit one-time Apple Reminders operations."""

import json
from unittest.mock import patch

import pytest

from application import Application
from tests.test_apple_reminder_sync import manager, reminder

pytestmark = pytest.mark.usefixtures("todos_plugin")


def test_reminder_one_time_is_scoped_confirmed_and_does_not_connect(tmp_path):
    sync, todos, bridge, _ = manager(tmp_path, [reminder()])
    with pytest.raises(ValueError, match="reminder_id"):
        sync.one_time("import", "a", [], confirm=True)
    with pytest.raises(ValueError, match="confirmation"):
        sync.one_time("import", "a", ["r1"], confirm=False)
    assert sync.one_time("import", "a", ["r1"], confirm=True)["imported"] == 1
    assert len(todos.list_todos()) == 1
    assert sync.status()["connected"] is False
    assert sync.one_time("import", "a", ["r1"], confirm=True)["imported"] == 0
    with pytest.raises(KeyError):
        sync.one_time("import", "a", ["made-up"], confirm=True)
    assert bridge.writes == []


def test_desktop_reminders_uses_application_manager(tmp_path, monkeypatch):
    from channel.desktop import desktop_channel as web_channel

    sync, _, _, _ = manager(tmp_path, [reminder()])
    monkeypatch.setattr(Application, "apple_reminders", staticmethod(lambda: sync))
    request = {"direction": "import", "list_id": "a", "item_ids": ["r1"]}
    def call(handler, body):
        with patch.object(web_channel.web, "data", return_value=json.dumps(body).encode()):
            return json.loads(handler().POST())
    with patch.object(web_channel, "_require_auth") as auth, patch.object(web_channel.web, "header"):
        assert call(web_channel.AppleReminderOneTimeHandler, {**request, "confirm": True})["status"] == "error"
        prepared = call(web_channel.AppleReminderPreviewHandler, request)
        response = call(web_channel.AppleReminderOneTimeHandler, {**request,
            "confirm": True, "preview_token": prepared["preview_token"]})
    assert response["status"] == "success"
    assert response["result"]["imported"] == 1
    assert response["connection"]["connected"] is False
    assert auth.call_count == 3


def test_first_reminder_connection_requires_matching_preview_token(tmp_path, monkeypatch):
    from channel.desktop import desktop_channel as web_channel

    sync, todos, _, _ = manager(tmp_path, [reminder()])
    monkeypatch.setattr(Application, "apple_reminders", staticmethod(lambda: sync))

    def call(handler, body):
        with patch.object(web_channel, "_require_auth"), patch.object(web_channel.web, "header"), \
             patch.object(web_channel.web, "data", return_value=json.dumps(body).encode()):
            return json.loads(handler().POST())

    selection = {"list_ids": ["a"], "direction": "import"}
    assert call(web_channel.AppleReminderConfigureHandler, selection)["status"] == "error"
    assert todos.list_todos() == [] and sync.status()["connected"] is False
    prepared = call(web_channel.AppleReminderScopePreviewHandler, selection)
    assert prepared["preview"]["new"] == 1
    assert call(web_channel.AppleReminderConfigureHandler, {**selection, "confirm": True,
        "preview_token": "invented"})["status"] == "error"
    configured = call(web_channel.AppleReminderConfigureHandler, {**selection, "confirm": True,
        "preview_token": prepared["preview_token"]})
    assert configured["result"]["imported"] == 1


def test_desktop_reminder_inventory_requires_auth_and_selected_list(tmp_path, monkeypatch):
    from channel.desktop import desktop_channel as web_channel

    sync, _, _, _ = manager(tmp_path, [reminder()])
    monkeypatch.setattr(Application, "apple_reminders", staticmethod(lambda: sync))
    with patch.object(web_channel, "_require_auth") as auth, patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "data", return_value=b'{"list_id":"a"}'):
        result = json.loads(web_channel.AppleReminderItemsHandler().POST())
    assert result["items"][0]["reminder_id"] == "r1"
    auth.assert_called_once()


def test_one_time_reminder_export_uses_explicit_todo_id_and_stays_disconnected(tmp_path):
    sync, todos, bridge, _ = manager(tmp_path)
    own = todos.create_todo({"title": "Write report", "due_on": "2026-10-12"})
    assert sync.preview_items("export", "a", [own["id"]])["new"] == 1
    assert sync.one_time("export", "a", [own["id"]], confirm=True)["exported"] == 1
    assert bridge.writes[-1]["stella_id"] == own["id"]
    assert sync.status()["connected"] is False
    assert sync.one_time("export", "a", [own["id"]], confirm=True)["exported"] == 0
    with pytest.raises(KeyError):
        sync.one_time("export", "a", ["made-up"], confirm=True)


def test_one_time_reminder_rejects_ambiguous_external_identity(tmp_path):
    sync, todos, bridge, _ = manager(tmp_path, [reminder(), reminder("r2", external_id="external-r1")])
    with pytest.raises(ValueError, match="ambiguous"):
        sync.one_time("import", "a", ["r1"], confirm=True)
    assert todos.list_todos() == []


def test_one_time_import_recovers_stella_marker_without_duplicate(tmp_path):
    sync, todos, bridge, _ = manager(tmp_path)
    own = todos.create_todo({"title": "A local task"})
    bridge.rows.append(reminder("saved", stella_id=own["id"], title="A local task"))
    result = sync.one_time("import", "a", ["saved"], confirm=True)
    assert result["imported"] == 0
    assert len(todos.list_todos()) == 1
    assert sync._maps()[0]["todo_id"] == own["id"]


def test_reminder_auto_switch_is_independent_and_persistent(tmp_path, monkeypatch):
    sync, todos, bridge, _ = manager(tmp_path)
    sync.configure(["a"], "import")
    calls = []
    monkeypatch.setattr(sync, "stop_auto", lambda: calls.append("stop"))
    sync.set_auto(False)
    assert calls == ["stop"]
    from agent.todos.apple_sync import AppleReminderSync
    reopened = AppleReminderSync(bridge=bridge, db_path=tmp_path / "apple_reminders.db", todo_port=todos)
    assert reopened.status()["auto_enabled"] is False
    monkeypatch.setattr(reopened, "start_auto", lambda: calls.append("start"))
    reopened.resume_auto()
    assert calls == ["stop"]
    reopened.set_auto(True)
    assert calls == ["stop", "start"]


def test_reminder_auto_route_updates_shared_manager(tmp_path, monkeypatch):
    from channel.desktop import desktop_channel as web_channel
    sync, _, _, _ = manager(tmp_path)
    monkeypatch.setattr(web_channel, "_apple_reminder_sync", lambda: sync)
    with patch.object(web_channel, "_require_auth"), patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "data", return_value=b'{"enabled":false}'), \
         patch.object(sync, "stop_auto"):
        result = json.loads(web_channel.AppleReminderAutoHandler().POST())
    assert result["connection"]["auto_enabled"] is False
