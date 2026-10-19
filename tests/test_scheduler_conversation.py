"""Scheduled desktop tasks keep an explicit conversation and project scope."""

from types import SimpleNamespace

import pytest

from agent.scheduler import conversation
from agent.tools.scheduler.scheduler_tool import SchedulerTool
from common.runtime_identity import identity_scope


@pytest.fixture
def scope(monkeypatch, tmp_path):
    sessions = {"chat_a", "chat_b"}
    bindings = {}
    project = tmp_path / "project"
    project.mkdir()

    monkeypatch.setattr("agent.registry.get_agent_registry", lambda: SimpleNamespace(
        get=lambda agent_id=None, **kwargs: SimpleNamespace(workspace=str(tmp_path))))
    monkeypatch.setattr("agent.memory.get_conversation_store", lambda workspace: SimpleNamespace(
        list_session_ids=lambda channel_type: list(sessions)))
    monkeypatch.setattr(conversation.project_store, "get_project_dir",
                        lambda session_id, agent_id=None: bindings.get(session_id))
    monkeypatch.setattr(conversation.project_store, "get_project_binding",
                        lambda session_id, agent_id=None: bindings.get(session_id))
    monkeypatch.setattr(conversation.project_store, "set_project_dir",
                        lambda session_id, path, agent_id=None: bindings.__setitem__(session_id, path))
    monkeypatch.setattr(conversation.project_store, "list_known_projects",
                        lambda: [{"path": str(project)}])
    return sessions, bindings, project


def test_bound_chat_freezes_project_and_stops_after_scope_change(scope):
    sessions, bindings, project = scope
    bindings["chat_a"] = str(project)
    with identity_scope(agent_id="agent-a"):
        action = conversation.validate_conversation_action({
            "channel_type": "web", "conversation_mode": "source",
            "source_session_id": "chat_a"})
        assert action["conversation_space"] == "project"
        assert action["execution_project_dir"] == str(project)
        run = conversation.prepare_run({"id": "daily", "action": action}, "agent-a")
        assert run["action"]["execution_session_id"] == "chat_a"
        assert run["action"]["receiver"] == "chat_a"
        assert bindings["chat_a"] == str(project)

        bindings["chat_a"] = None
        with pytest.raises(ValueError, match="changed projects"):
            conversation.prepare_run({"id": "daily", "action": action}, "agent-a")
        sessions.remove("chat_a")
        with pytest.raises(ValueError, match="no longer available"):
            conversation.prepare_run({"id": "daily", "action": action}, "agent-a")


def test_reuse_and_new_modes_keep_selected_project(scope):
    _, bindings, project = scope
    action = {"channel_type": "web", "conversation_mode": "new",
              "conversation_space": "project", "execution_project_dir": str(project)}
    with identity_scope(agent_id="agent-a"):
        first = conversation.prepare_run({"id": "daily", "job_run_id": "run1", "action": action}, "agent-a")
        second = conversation.prepare_run({"id": "daily", "job_run_id": "run2", "action": action}, "agent-a")
        assert first["action"]["receiver"] == "task_daily_run1"
        assert second["action"]["receiver"] == "task_daily_run2"
        assert bindings["task_daily_run1"] == str(project)
        assert conversation.agent_session_id(first) != conversation.agent_session_id(second)

        reuse = conversation.prepare_run({"id": "daily", "action": {**action, "conversation_mode": "reuse"}}, "agent-a")
        assert reuse["action"]["receiver"].startswith("task_daily_")
        assert conversation.prepare_run({"id": "daily", "action": reuse["action"]}, "agent-a")["action"]["receiver"] == reuse["action"]["receiver"]


def test_explicit_web_route_tracks_resolved_conversation_when_it_targets_execution(scope, tmp_path):
    from agent.scheduler.automation_store import AutomationStore
    from agent.scheduler.dispatch import dispatch_notification
    _, _, project = scope
    route = {"primary": {"channel_type": "web", "receiver": "original"},
             "backup_enabled": False, "backup": None}
    for mode in ("reuse", "new"):
        task = {"id": "daily", "job_run_id": "run1", "notification_route": route,
                "action": {"channel_type": "web", "receiver": "original", "conversation_mode": mode,
                           "conversation_space": "project", "execution_project_dir": str(project)}}
        with identity_scope(agent_id="agent-a"):
            prepared = conversation.prepare_run(task, "agent-a")
        assert prepared["notification_route"]["primary"]["receiver"] == prepared["action"]["receiver"]
        assert route["primary"]["receiver"] == "original"
        store = AutomationStore(tmp_path / mode / "tasks.json", "agent-a")
        store.add_task(task)
        sent = []
        with identity_scope(agent_id="agent-a"):
            job_id = store.claim_occurrence("daily", manual=True)
            result = dispatch_notification(store, job_id, prepared["notification_route"], "hello",
                                           channel_provider=lambda _: SimpleNamespace(send=lambda reply, context:
                                               sent.append(context["receiver"]) or {"success": True}))
        assert result.status == "failed" and "重新选择" in result.error
        assert sent == []


def test_agent_scheduler_schema_and_execute_cannot_raise_run_permission(scope, tmp_path):
    from agent.scheduler import TaskStore
    assert "run_permission_mode" not in SchedulerTool.params["properties"]
    sessions, bindings, project = scope
    bindings["chat_a"] = str(project)
    tool = SchedulerTool({"channel_type": "web"})
    tool.task_store = TaskStore(str(tmp_path / "tasks.json"))
    context = {"receiver": "chat_a", "session_id": "chat_a", "isgroup": False}
    tool.current_context = type("ToolContext", (dict,), {"kwargs": {}})(context)
    with identity_scope(agent_id="agent-a"):
        refused = tool.execute({"action": "create", "name": "daily", "message": "hello",
                                "schedule_type": "interval", "schedule_value": "3600",
                                "run_permission_mode": "full-access"})
    assert refused.status == "error"
    assert "运行权限" in refused.result
    assert tool.task_store.load_tasks() == {}


def test_agent_created_task_defaults_to_source_even_before_chat_is_saved(scope):
    sessions, bindings, project = scope
    sessions.clear()  # The Agent can call the tool before its current turn is persisted.
    bindings["chat_a"] = str(project)
    tool = SchedulerTool({"channel_type": "web"})
    saved = []
    tool.task_store = SimpleNamespace(add_task=saved.append)
    context = {"receiver": "chat_a", "session_id": "chat_a", "isgroup": False}
    tool.current_context = type("ToolContext", (dict,), {"kwargs": {}})(context)
    with identity_scope(agent_id="agent-a"):
        result = tool.execute({"action": "create", "name": "daily", "message": "hello",
                               "schedule_type": "interval", "schedule_value": "3600"})
    assert result.status == "success"
    assert saved[0]["action"]["conversation_mode"] == "source"
    assert saved[0]["action"]["source_session_id"] == "chat_a"
    assert saved[0]["action"]["execution_project_dir"] == str(project)


def test_desktop_task_requires_explicit_mode_and_other_channels_keep_routing(scope):
    task = {"id": "missing", "action": {"channel_type": "web", "receiver": "original"}}
    with pytest.raises(ValueError, match="conversation mode"):
        conversation.prepare_run(task)
    other = {"id": "feishu", "action": {"channel_type": "feishu", "receiver": "recipient"}}
    assert conversation.prepare_run(other) is other


def test_bound_chat_supplies_recent_visible_context(scope, monkeypatch):
    from agent.memory import get_conversation_store
    store = get_conversation_store("unused")
    store.load_messages = lambda session_id, max_turns: [
        {"role": "user", "content": [{"type": "text", "text": "Write the report in Chinese"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "name": "write"},
                                            {"type": "text", "text": "Understood"}]},
    ]
    monkeypatch.setattr("agent.memory.get_conversation_store", lambda workspace: store)
    context = conversation.source_context({"conversation_mode": "source", "source_session_id": "chat_a"}, "agent-a")
    assert "Write the report in Chinese" in context
    assert "Understood" in context
    assert "tool_use" not in context


def test_telegram_delivery_keeps_bound_conversation(scope):
    from agent.scheduler.mutations import SchedulerMutations
    from agent.scheduler import TaskStore
    from datetime import datetime, timedelta

    sessions, bindings, project = scope
    bindings["chat_a"] = str(project)
    store = TaskStore(str(project.parent / "scheduler" / "tasks.json"))
    mutations = SchedulerMutations(store)
    with identity_scope(agent_id="agent-a"):
        action = conversation.validate_conversation_action({
            "type": "agent_task", "channel_type": "web", "conversation_mode": "source",
            "source_session_id": "chat_a", "task_description": "daily brief",
        })
        task = {
            "id": "task-channel", "name": "brief", "enabled": True,
            "created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat(),
            "next_run_at": (datetime.now() + timedelta(hours=1)).isoformat(),
            "schedule": {"type": "interval", "seconds": 3600}, "action": action,
        }
        mutations.create(task)
        updated = mutations.update("task-channel", {
            "notification_route": {"primary": {"channel_type": "telegram", "receiver": "123", "is_group": False}},
        })
        assert updated["action"]["conversation_mode"] == "source"
        assert updated["action"]["source_session_id"] == "chat_a"
        assert updated["action"]["execution_project_dir"] == str(project)
        assert updated["action"]["channel_type"] == "telegram"


def test_scoped_output_persists_full_text_and_does_not_recreate_deleted_chat():
    from bridge.agent_bridge import AgentBridge
    written = []
    store = SimpleNamespace(
        append_messages=lambda session_id, messages, **kwargs: written.append((messages, kwargs)) or True,
        prune_scheduled_messages=lambda *args, **kwargs: 0,
    )
    bridge = SimpleNamespace(
        _SCHEDULED_MARKER="[SCHEDULED]",
        get_conversation_store=lambda agent_id=None: store,
        get_cached_agent=lambda session_id, agent_id=None: None,
    )
    AgentBridge.remember_scheduled_output(bridge, "chat_a", "x" * 3000,
                                          channel_type="web", force=True, require_existing=True)
    assert written[0][0][1]["content"][0]["text"] == "x" * 3000
    assert written[0][1]["create_if_missing"] is False
