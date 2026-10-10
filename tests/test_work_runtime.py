"""Runtime, Desktop and scheduled tools use the same Work context."""

from types import SimpleNamespace

import pytest

from agent.protocol.agent import Agent
from agent.runtime.tool_invocation import execution_workspace
from agent.workspace import project_store
from agent.workspace.context import resolve_context
from bridge.agent_bridge import AgentBridge
from channel.desktop.desktop_channel import _get_workspace_root, _project_state, _session_settings_state
from common.runtime_identity import identity_scope


@pytest.fixture
def roots(tmp_path, monkeypatch):
    work = tmp_path / "work"
    monkeypatch.setattr("agent.workspace.context.personal_work_dir", lambda **kwargs: work)
    monkeypatch.setattr(project_store, "_store_file", lambda: str(tmp_path / "projects.json"))
    return work


def test_agent_tools_and_desktop_file_panel_follow_same_session_root(roots, tmp_path):
    agent = Agent("test", workspace_dir=str(tmp_path), enable_skills=False)
    tool = SimpleNamespace(name="read", cwd=None, config={})
    agent.tools.append(tool)
    bridge = object.__new__(AgentBridge)
    bridge._apply_session_project(agent, "first", "alpha")
    expected = str(roots / "sessions" / "alpha" / "first")
    assert agent.effective_cwd() == expected
    assert tool.cwd == expected and tool.config["cwd"] == expected
    assert _get_workspace_root("first", "alpha") == expected
    assert execution_workspace("first", "alpha") == (expected, [expected])
    assert not roots.exists()

    bridge._apply_session_project(agent, "second", "alpha")
    assert agent.effective_cwd() == str(roots / "sessions" / "alpha" / "second")
    assert tool.cwd == agent.effective_cwd()


def test_scheduled_runs_keep_one_task_root_without_source_file_access(roots):
    with identity_scope(agent_id="alpha", session_id="source", task_id="daily"):
        expected = str(roots / "automations" / "alpha" / "daily")
        assert execution_workspace("source", "alpha") == (expected, [expected])
        assert execution_workspace("new-run", "alpha") == (expected, [expected])
        assert resolve_context("source", "alpha", task_id="daily").kind == "automation"
    assert not roots.exists()


def test_scheduled_project_uses_execution_binding_not_transcript_id(roots, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    project_store.set_project_dir("source", str(project), "alpha")
    with identity_scope(agent_id="alpha", session_id="scheduler_daily", task_id="daily",
                        execution_session_id="source"):
        assert execution_workspace("scheduler_daily", "alpha") == (str(project), [str(project)])


def test_missing_bound_project_stops_runtime_and_file_panel(roots, tmp_path):
    project = tmp_path / "removed"
    project.mkdir()
    project_store.set_project_dir("first", str(project), "alpha")
    project.rmdir()
    agent = Agent("test", workspace_dir=str(tmp_path), enable_skills=False)
    bridge = object.__new__(AgentBridge)
    with pytest.raises(FileNotFoundError, match="project"):
        bridge._apply_session_project(agent, "first", "alpha")
    with pytest.raises(FileNotFoundError, match="project"):
        _get_workspace_root("first", "alpha")
    with pytest.raises(FileNotFoundError, match="project"):
        execution_workspace("first", "alpha")


def test_scheduler_passes_stable_task_id_to_agent_run(roots, monkeypatch):
    from agent.scheduler import integration, result_cache
    from bridge.reply import Reply, ReplyType

    monkeypatch.setattr(integration, "get_task_store", lambda **kwargs: object())
    monkeypatch.setattr(result_cache, "load_output", lambda *args: None)
    monkeypatch.setattr(result_cache, "save_output", lambda *args: None)
    seen = []

    class Bridge:
        def agent_reply(self, prompt, *, context, **kwargs):
            seen.append(context.get("task_id"))
            return Reply(ReplyType.TEXT, "done")

    task = {"id": "daily", "job_run_id": "run-1", "action": {
        "type": "agent_task", "task_description": "prepare report", "silent": True,
        "channel_type": "web", "receiver": "source", "execution_session_id": "source"}}
    assert integration._execute_agent_task(task, Bridge(), "alpha") is True
    assert seen == ["daily"]


def test_uncreated_private_file_panel_is_empty_without_creating_directory(roots):
    from agent.workspace.service import WorkspaceService

    private = roots / "sessions" / "alpha" / "first"
    tree = WorkspaceService(str(private)).list_dir()
    assert tree["entries"] == []
    assert not private.exists()


def test_source_task_rejects_deleted_project_even_without_frozen_path(roots, tmp_path, monkeypatch):
    from agent.scheduler.conversation import validate_conversation_action

    project = tmp_path / "removed"
    project.mkdir()
    project_store.set_project_dir("source", str(project), "alpha")
    project.rmdir()
    monkeypatch.setattr("agent.registry.get_agent_registry", lambda: SimpleNamespace(
        get=lambda agent_id: SimpleNamespace(workspace=str(tmp_path))))
    monkeypatch.setattr("agent.memory.get_conversation_store", lambda workspace: SimpleNamespace(
        list_session_ids=lambda channel_type: ["source"]))
    with identity_scope(agent_id="alpha"):
        with pytest.raises(ValueError, match="project"):
            validate_conversation_action({"channel_type": "web", "conversation_mode": "source",
                                          "source_session_id": "source"})


def test_workspace_picker_and_permission_status_show_private_session_root(roots, monkeypatch):
    monkeypatch.setattr("agent.permission.process_sandbox.capability", lambda: {
        "status": "unavailable", "reason": "test"})
    expected = str(roots / "sessions" / "alpha" / "first")
    assert _project_state("first", "alpha")["default_workspace"] == expected
    assert _session_settings_state("first", "alpha")["permission"]["authorized_roots"][0] == expected
    from agent.permission.center import overview
    assert overview("first", "alpha")["authorized_roots"][0] == expected


def test_agent_prompt_names_private_working_directory(roots, tmp_path):
    agent = Agent("test", workspace_dir=str(tmp_path), enable_skills=False)
    agent.apply_work_context(resolve_context("first", "alpha"))
    prompt = agent.get_full_system_prompt()
    assert f"当前工作目录：`{agent.effective_cwd()}`" in prompt
    assert "用户已打开一个**项目目录**" not in prompt
