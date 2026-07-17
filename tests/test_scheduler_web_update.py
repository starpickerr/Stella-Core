"""Regression tests for scheduler edits made through the Web console."""

import json
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import patch

from agent.tools.scheduler.task_store import TaskStore

# Keep this unit test independent from the optional web.py dependency.
if "web" not in sys.modules:
    web_stub = types.ModuleType("web")
    web_stub.HTTPError = type("HTTPError", (Exception,), {})
    web_stub.cookies = lambda: {}
    web_stub.header = lambda *args, **kwargs: None
    web_stub.data = lambda: b"{}"
    web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
    web_stub.setcookie = lambda *args, **kwargs: None
    web_stub.seeother = lambda *args, **kwargs: Exception("seeother")
    web_stub.notfound = lambda *args, **kwargs: Exception("notfound")
    web_stub.badrequest = lambda *args, **kwargs: Exception("badrequest")
    web_stub.application = lambda *args, **kwargs: types.SimpleNamespace(wsgifunc=lambda: None)
    web_stub.httpserver = types.SimpleNamespace(
        LogMiddleware=type("LogMiddleware", (), {"log": lambda *args, **kwargs: None}),
        StaticMiddleware=lambda app: app,
        WSGIServer=lambda *args, **kwargs: types.SimpleNamespace(serve_forever=lambda: None),
    )
    sys.modules["web"] = web_stub

from channel.web.web_channel import SchedulerUpdateHandler


def _store_task(tmp_path, action):
    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    store.add_task({
        "id": "task-1",
        "name": "maintenance",
        "enabled": True,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "next_run_at": (datetime.now() + timedelta(hours=1)).isoformat(),
        "schedule": {"type": "interval", "seconds": 3600},
        "action": action,
    })
    return store


def _post_update(tmp_path, payload):
    with patch("channel.web.web_channel._require_auth"), \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel.web.data", return_value=json.dumps(payload).encode()), \
         patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)):
        return json.loads(SchedulerUpdateHandler().POST())


def test_web_edit_preserves_hidden_agent_action_fields(tmp_path):
    store = _store_task(tmp_path, {
        "type": "agent_task",
        "task_description": "refresh the index",
        "receiver": "user-1",
        "receiver_name": "User",
        "is_group": False,
        "channel_type": "feishu",
        "notify_session_id": "session-1",
        "silent": True,
        "delivery_extension": {"trace": True},
    })

    result = _post_update(tmp_path, {
        "task_id": "task-1",
        "name": "renamed maintenance",
        "action": {
            "type": "agent_task",
            "task_description": "refresh both indexes",
            "receiver": "user-1",
            "channel_type": "feishu",
        },
    })

    assert result["status"] == "success"
    action = store.get_task("task-1")["action"]
    assert action["task_description"] == "refresh both indexes"
    assert action["silent"] is True
    assert action["notify_session_id"] == "session-1"
    assert action["delivery_extension"] == {"trace": True}


def test_switch_to_message_drops_agent_only_fields(tmp_path):
    store = _store_task(tmp_path, {
        "type": "agent_task",
        "task_description": "refresh the index",
        "receiver": "user-1",
        "channel_type": "web",
        "notify_session_id": "session-1",
        "silent": True,
    })

    result = _post_update(tmp_path, {
        "task_id": "task-1",
        "action": {
            "type": "send_message",
            "content": "Index refresh reminder",
            "receiver": "user-1",
            "channel_type": "web",
        },
    })

    assert result["status"] == "success"
    action = store.get_task("task-1")["action"]
    assert action["content"] == "Index refresh reminder"
    assert "task_description" not in action
    assert "silent" not in action
    assert action["notify_session_id"] == "session-1"
