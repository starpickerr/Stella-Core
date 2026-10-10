"""Agent Apple operations share desktop's persisted integration manager."""

import json

from agent.tools.apple.apple_tool import AppleTool
from application import Application
from tests.test_apple_reminder_sync import manager, reminder


def test_agent_reminders_lookup_preview_and_one_time_share_manager(tmp_path, monkeypatch):
    sync, todos, _, _ = manager(tmp_path, [reminder()])
    monkeypatch.setattr(Application, "apple_reminders", staticmethod(lambda: sync))
    tool = AppleTool()

    def call(**params):
        result = tool.execute(params)
        assert result.status == "success", result.result
        return json.loads(result.result)

    assert call(kind="reminders", action="status")["connection"]["connected"] is False
    assert call(kind="reminders", action="sources")["sources"][0]["id"] == "a"
    assert call(kind="reminders", action="items", source_id="a")["items"][0]["reminder_id"] == "r1"
    assert call(kind="reminders", action="lookup", source_id="a", item_id="r1")["item"]["title"] == "Homework"
    preview = call(kind="reminders", action="preview", direction="import", source_id="a", item_ids=["r1"])
    assert preview["preview"]["new"] == 1
    assert tool.execute({"kind": "reminders", "action": "one_time", "direction": "import",
                         "source_id": "a", "item_ids": ["r1"], "confirm": True}).status == "error"
    assert call(kind="reminders", action="one_time", direction="import", source_id="a",
                item_ids=["r1"], confirm=True, preview_token=preview["preview_token"])["result"]["imported"] == 1
    assert todos.list_todos()[0]["title"] == "Homework"
    assert sync.status()["connected"] is False
    assert tool.execute({"kind": "reminders", "action": "lookup", "source_id": "a",
                         "item_id": "fiction"}).status == "error"


def test_agent_can_inspect_unsupported_relative_alarm_without_importing(tmp_path, monkeypatch):
    sync, todos, _, _ = manager(tmp_path, [reminder(remind_at=None, alarm_count=1)])
    monkeypatch.setattr(Application, "apple_reminders", staticmethod(lambda: sync))
    result = AppleTool().execute({"kind": "reminders", "action": "lookup",
                                  "source_id": "a", "item_id": "r1"})
    assert result.status == "success"
    assert json.loads(result.result)["item"]["alarm_count"] == 1
    assert todos.list_todos() == []


def test_agent_configure_keeps_disabled_auto_sync_off(tmp_path, monkeypatch):
    sync, _, _, _ = manager(tmp_path, [reminder()])
    monkeypatch.setattr(Application, "apple_reminders", staticmethod(lambda: sync))
    starts = []
    monkeypatch.setattr(sync, "start_auto", lambda *args: starts.append(args))
    sync.set_auto(False)
    tool = AppleTool()
    preview = tool.execute({"kind": "reminders", "action": "preview_scope",
                            "source_ids": ["a"], "direction": "import"})
    assert preview.status == "success", preview.result
    token = json.loads(preview.result)["preview_token"]
    configured = tool.execute({"kind": "reminders", "action": "configure", "source_ids": ["a"],
                               "direction": "import", "confirm": True, "preview_token": token})
    assert configured.status == "success", configured.result
    assert sync.status()["auto_enabled"] is False
    assert starts == []
