"""Authenticated desktop API and explicit one-time Apple Reminders operations."""

import json
from unittest.mock import patch

import pytest

from application import Application
from tests.test_apple_reminder_sync import manager, reminder


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
    with patch.object(web_channel, "_require_auth") as auth, \
         patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "data", return_value=json.dumps({
             "direction": "import", "list_id": "a", "item_ids": ["r1"], "confirm": True,
         }).encode()):
        response = json.loads(web_channel.AppleReminderOneTimeHandler().POST())
    assert response["status"] == "success"
    assert response["result"]["imported"] == 1
    assert response["connection"]["connected"] is False
    auth.assert_called_once()


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
