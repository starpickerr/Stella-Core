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
    assert call(kind="reminders", action="one_time", direction="import", source_id="a",
                item_ids=["r1"], confirm=True)["result"]["imported"] == 1
    assert todos.list_todos()[0]["title"] == "Homework"
    assert sync.status()["connected"] is False
    assert tool.execute({"kind": "reminders", "action": "lookup", "source_id": "a",
                         "item_id": "fiction"}).status == "error"
