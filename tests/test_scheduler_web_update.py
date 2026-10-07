"""Regression tests for scheduler edits made through the Web console."""

import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from agent.scheduler import TaskStore

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

from channel.desktop import desktop_channel as web_channel

SchedulerUpdateHandler = web_channel.SchedulerUpdateHandler


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
    with patch("channel.desktop.desktop_channel._require_auth"), \
         patch("channel.desktop.desktop_channel.web.header"), \
         patch("channel.desktop.desktop_channel.web.data", return_value=json.dumps(payload).encode()), \
         patch("channel.desktop.desktop_channel._get_state_root", return_value=str(tmp_path)):
        return json.loads(SchedulerUpdateHandler().POST())


def test_desktop_can_edit_silent_tool_task_without_receiver(tmp_path):
    action = {"type": "tool_call", "call_name": "briefing",
              "call_params": {"action": "run", "operation": "create"},
              "silent": True, "channel_type": "web", "conversation_mode": "reuse",
              "conversation_space": "personal", "execution_project_dir": ""}
    store = _store_task(tmp_path, action)
    result = _post_update(tmp_path, {
        "task_id": "task-1",
        "name": "课程简报", "enabled": False,
        "schedule": {"type": "cron", "expression": "0 9 * * *"},
        "action": action,
    })
    assert result["status"] == "success"
    task = store.get_task("task-1")
    assert task["enabled"] is False
    assert task["schedule"]["expression"] == "0 9 * * *"
    assert task["action"]["call_params"] == {"action": "run", "operation": "create"}
    assert task["action"]["silent"] is True
    assert task["action"]["conversation_mode"] == "reuse"


def test_web_manual_run_is_authenticated_and_delegates_to_scheduler():
    assert hasattr(web_channel, "SchedulerRunHandler")

    service = Mock()
    with patch("channel.desktop.desktop_channel._require_auth") as require_auth, \
         patch("channel.desktop.desktop_channel.web.header"), \
         patch("channel.desktop.desktop_channel.web.data", return_value=b'{"task_id":"task-1"}'), \
         patch("agent.scheduler.get_scheduler_service", return_value=service):
        response = json.loads(web_channel.SchedulerRunHandler().POST())

    require_auth.assert_called_once_with()
    service.run_task_now.assert_called_once_with("task-1")
    assert response == {
        "status": "success",
        "message": "Task 'task-1' queued for immediate execution",
    }


def test_web_manual_run_rejects_unavailable_scheduler():
    assert hasattr(web_channel, "SchedulerRunHandler")

    with patch("channel.desktop.desktop_channel._require_auth"), \
         patch("channel.desktop.desktop_channel.web.header"), \
         patch("channel.desktop.desktop_channel.web.data", return_value=b'{"task_id":"task-1"}'), \
         patch("agent.scheduler.get_scheduler_service", return_value=None):
        response = json.loads(web_channel.SchedulerRunHandler().POST())

    assert response == {
        "status": "error",
        "message": "Scheduler service is not running",
    }


def test_manual_run_is_exposed_by_desktop_controls():
    root = Path(__file__).parents[1]
    web_source = (root / "channel/desktop/desktop_channel.py").read_text(encoding="utf-8")
    desktop_client = (root / "desktop/src/renderer/src/api/client.ts").read_text(encoding="utf-8")
    desktop_page = (root / "desktop/src/renderer/src/pages/TasksPage.tsx").read_text(encoding="utf-8")

    assert "'/api/scheduler/run', 'SchedulerRunHandler'" in web_source
    assert "async runTask(taskId: string)" in desktop_client
    assert "'/api/scheduler/run'" in desktop_client
    assert "const runNow = async ()" in desktop_page
    assert "window.confirm(t('task_run_confirm'))" in desktop_page


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
        "conversation_mode": "reuse",
        "conversation_space": "personal",
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


SchedulerHandler = web_channel.SchedulerHandler


def _post_create(tmp_path, payload):
    with patch("channel.desktop.desktop_channel._require_auth"), \
         patch("channel.desktop.desktop_channel.web.header"), \
         patch("channel.desktop.desktop_channel.web.data", return_value=json.dumps(payload).encode()), \
         patch("channel.desktop.desktop_channel._get_state_root", return_value=str(tmp_path)):
        return json.loads(SchedulerHandler().POST())


def test_web_create_persists_task_for_current_session(tmp_path):
    result = _post_create(tmp_path, {
        "name": "morning briefing",
        "enabled": True,
        "schedule": {"type": "cron", "expression": "0 9 * * *"},
        "action": {"type": "send_message", "content": "good morning",
                   "conversation_mode": "reuse", "conversation_space": "personal"},
        "session_id": "session-web-1",
    })

    assert result["status"] == "success"
    task = result["task"]
    assert task["name"] == "morning briefing"
    assert task["schedule"] == {"type": "cron", "expression": "0 9 * * *"}
    assert task["action"]["type"] == "send_message"
    assert task["action"]["content"] == "good morning"
    assert task["action"]["channel_type"] == "web"
    assert task["action"]["conversation_mode"] == "reuse"
    assert task["action"]["receiver"] == "session-web-1"
    assert task["action"]["notify_session_id"] == "session-web-1"
    assert task["next_run_at"]

    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    saved = store.get_task(task["id"])
    assert saved["name"] == "morning briefing"


def test_web_create_rejects_missing_session(tmp_path):
    result = _post_create(tmp_path, {
        "name": "orphan",
        "schedule": {"type": "cron", "expression": "0 9 * * *"},
        "action": {"type": "send_message", "content": "hi"},
    })
    assert result["status"] == "error"
    assert "session_id" in result["message"]


def test_web_create_rejects_missing_conversation_mode(tmp_path):
    result = _post_create(tmp_path, {
        "name": "orphan",
        "schedule": {"type": "cron", "expression": "0 9 * * *"},
        "action": {"type": "send_message", "content": "hi"},
        "session_id": "session-web-1",
    })
    assert result["status"] == "error"
    assert "conversation mode" in result["message"]


def test_create_is_exposed_by_desktop_controls():
    root = Path(__file__).parents[1]
    web_source = (root / "channel/desktop/desktop_channel.py").read_text(encoding="utf-8")
    desktop_client = (root / "desktop/src/renderer/src/api/client.ts").read_text(encoding="utf-8")
    desktop_page = (root / "desktop/src/renderer/src/pages/TasksPage.tsx").read_text(encoding="utf-8")

    handler = web_source[web_source.index("class SchedulerHandler"):]
    assert "def POST(self):" in handler
    assert "async createTask" in desktop_client
    assert "setEditing('new')" in desktop_page
