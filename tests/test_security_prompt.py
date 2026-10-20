"""The model sees current policy guidance, while execution remains gated."""
from types import SimpleNamespace

from common.runtime_identity import identity_scope
from agent.permission.security_policy import describe, legacy_policy
from agent.prompt.builder import build_agent_system_prompt
from agent.workspace import project_store


def test_security_prompt_uses_current_conversation_policy_and_file_grant(tmp_path, monkeypatch):
    state = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: state)
    live = {"knowledge": False, "agent_tool_allowlist": ["read", "elearning"],
            "security_policy": {"preset": "standard", "rules": {"network": "deny"},
                                "connections": {"browser": {"allowed": False}}}}
    monkeypatch.setattr("config.conf", lambda: live)
    monkeypatch.setattr("agent.prompt.builder.conf", lambda: live)
    monkeypatch.setenv("STELLA_ELEARNING_PLUGIN", "1")
    monkeypatch.setattr("core.services.elearning_facade.ElearningPluginFacade.get_settings", lambda self: {
        "enabled": False, "configured": True, "file_sync_enabled": False,
        "file_sync_root": str(tmp_path / "selected"),
        "password": "TOPSECRET",
    }, raising=False)
    project_store.set_project_dir("conversation", str(project))
    project_store.set_security_policy(str(project), {"extra_roots": [str(tmp_path / "extra")]})
    with identity_scope(session_id="conversation"):
        kwargs = {"workspace_dir": str(state), "project_dir": str(project),
                  "permission_mode": "workspace-write", "tools": [SimpleNamespace(name="elearning")]}
        first = build_agent_system_prompt(**kwargs)
        assert "network=deny" in first
        assert "background=confirm" in first
        assert "browser\"=denied" in first
        assert str(project) in first and str(tmp_path / "extra") in first
        assert str(tmp_path / "selected") in first
        assert "TOPSECRET" not in first
        assert "不要用脚本或换工具绕过拒绝" in first
        # Project-internal chats share one project policy; rule changes save on the project.
        project_store.set_security_policy(str(project), {
            "preset": "workspace-write",
            "rules": {"network": "allow"},
            "connections": {"browser": {"allowed": False}},
            "extra_roots": [str(tmp_path / "extra")],
        })
        second = build_agent_system_prompt(**kwargs)
        assert "network=allow" in second
        assert "network=deny" not in second


def test_security_prompt_explains_disabled_sync_and_hard_boundaries():
    text = "\n".join(describe(legacy_policy("read-only"), elearning_sync={"enabled": False}))
    assert "workspace_write=deny" in text
    assert "eLearning 文件同步未就绪" in text
    assert "受保护凭据读取和提权仍被禁止" in text
    assert "会话文件读取被拒绝不代表连接器被拒绝" in text
    assert "不要建议开放 workspace_outside" in text
    assert "elearning list_files" in text
    assert "不要读取 Cookie、用脚本直连 Canvas" in text
