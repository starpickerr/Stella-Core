import json

from agent.permission.audit import recent
from agent.permission.gateway import DecisionKind, Scope, SecurityGateway
from agent.permission.security_policy import legacy_policy, resolve
from agent.workspace import project_store, session_prefs


def test_managed_skills_are_not_workspace_writes(tmp_path, monkeypatch):
    state = tmp_path / "state"
    skills = state / "skills"
    project = tmp_path / "project"
    other = tmp_path / "other"
    for path in (skills, project, other):
        path.mkdir(parents=True)
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: state)
    monkeypatch.setattr("common.state_dir.skills_dir", lambda *args, **kwargs: skills)
    monkeypatch.setattr("common.state_dir.mcp_config_file", lambda *args, **kwargs: state / "mcp.json")
    policy = legacy_policy("read-only")
    scope = Scope(write_roots=(str(project),))
    result = SecurityGateway.check("read-only", "write", {"path": str(skills / "example" / "SKILL.md")},
                                   cwd=str(project), scope=scope, policy=policy, session_id="skill")
    assert result.kind is DecisionKind.ALLOW
    assert result.resource_kind.value == "agent-managed"
    assert SecurityGateway.check("read-only", "edit", {"path": str(skills / "example" / "SKILL.md")},
                                 cwd=str(project), scope=scope, policy=policy).allowed
    assert not SecurityGateway.check("read-only", "write", {"path": str(project / "user.py")},
                                     cwd=str(project), scope=scope, policy=policy).allowed
    assert not SecurityGateway.check("workspace-write", "write", {"path": str(other / "user.py")},
                                     cwd=str(project), scope=scope, policy=legacy_policy("workspace-write")).allowed
    assert SecurityGateway.check("workspace-write", "write", {"path": str(project / "user.py")},
                                 cwd=str(project), scope=scope, policy=legacy_policy("workspace-write")).allowed
    assert SecurityGateway.check("workspace-write", "read", {"path": str(project / "user.py")},
                                 cwd=str(project), scope=scope, policy=legacy_policy("workspace-write")).allowed
    denied_read = SecurityGateway.check("workspace-write", "read", {"path": str(other / "user.py")},
                                        cwd=str(project), scope=scope, policy=legacy_policy("workspace-write"))
    assert denied_read.kind is DecisionKind.DENY
    assert "workspace_outside" in denied_read.reason
    rows = recent(filters={"conversation": "skill"})
    assert rows[0]["resource"] == "Agent Skill Store"
    assert rows[0]["trace"][-1] == "Decision: allow"


def test_risk_confirmation_and_credential_denial(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: state)
    monkeypatch.setattr("common.state_dir.skills_dir", lambda *args, **kwargs: state / "skills")
    monkeypatch.setattr("common.state_dir.mcp_config_file", lambda *args, **kwargs: state / "mcp.json")
    monkeypatch.setattr("config.get_data_root", lambda: str(state))
    policy = legacy_policy("full-access")
    args = {"command": "rm -rf ./old"}
    first = SecurityGateway.check("full-access", "bash", args, cwd=str(tmp_path), session_id="risk", policy=policy)
    assert first.kind is DecisionKind.CONFIRM
    assert SecurityGateway.approve(first.request_id)
    assert SecurityGateway.check("full-access", "bash", args, cwd=str(tmp_path), session_id="risk", policy=policy).allowed
    rejected = SecurityGateway.check("full-access", "bash", args, cwd=str(tmp_path), session_id="risk", policy=policy)
    assert rejected.kind is DecisionKind.CONFIRM
    assert SecurityGateway.reject(rejected.request_id)
    assert not SecurityGateway.approve(rejected.request_id)
    assert any(row["event"] == "confirmation" and row["decision"] == "deny"
               for row in recent(filters={"conversation": "risk"}))
    assert SecurityGateway.check("full-access", "bash", {"command": "sudo true"}, cwd=str(tmp_path), policy=policy).kind is DecisionKind.DENY
    assert SecurityGateway.check("full-access", "read", {"path": str(state / "config.json")}, cwd=str(tmp_path), policy=policy).kind is DecisionKind.DENY
    assert "TOPSECRET" not in (state / "security-activity.jsonl").read_text()


def test_policy_inheritance_and_restart_persistence(tmp_path, monkeypatch):
    state = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    project_store.set_security_policy(str(project), {"rules": {"network": "deny"}})
    project_store.set_project_dir("conversation", str(project))
    session_prefs.set_prefs("conversation", security_policy={"rules": {"network": "allow"}, "extra_roots": [str(tmp_path / "extra")]})
    global_value = {"preset": "standard", "rules": {"shell": "confirm"}, "connections": {}}
    effective = resolve("workspace-write", project_dir=str(project), session_id="conversation", global_value=global_value)
    assert effective["rules"] == {"shell": "confirm", "network": "allow"}
    assert effective["extra_roots"] == [str(tmp_path / "extra")]
    assert project_store.get_security_policy(str(project))["rules"]["network"] == "deny"
    assert json.loads((state / "projects.json").read_text())["meta"][str(project)]["security_policy"]["rules"]["network"] == "deny"
    assert json.loads((state / "session_prefs.json").read_text())["sessions"]["default::conversation"]["security_policy"]["rules"]["network"] == "allow"


def test_legacy_conversation_permission_is_migrated_once(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    path = state / "session_prefs.json"
    path.write_text(json.dumps({"sessions": {"default::old": {
        "model": "existing-model", "permission": "read-only", "ts": 1,
    }}}))
    prefs = session_prefs.get_prefs("old")
    assert prefs["security_policy"]["preset"] == "strict"
    assert prefs["model"] == "existing-model"
    stored = json.loads(path.read_text())["sessions"]["default::old"]
    assert "permission" not in stored
    assert stored["security_policy"]["preset"] == "strict"


def test_trusted_skill_initializer_works_under_strict_policy(tmp_path, monkeypatch):
    from pathlib import Path
    state = tmp_path / "state"
    skills = state / "skills"
    project = tmp_path / "project"
    skills.mkdir(parents=True)
    project.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: state)
    monkeypatch.setattr("common.state_dir.skills_dir", lambda *args, **kwargs: skills)
    script = Path(__file__).parents[1] / "skills" / "skill-creator" / "scripts" / "init_skill.py"
    command = f"python3 {script} my-skill --path {skills}"
    assert SecurityGateway.check("read-only", "bash", {"command": command}, cwd=str(project),
                                 scope=Scope(write_roots=(str(project),)), policy=legacy_policy("read-only")).allowed
    assert SecurityGateway.check("read-only", "bash", {"command": command + "; rm -rf /"}, cwd=str(project),
                                 scope=Scope(write_roots=(str(project),)), policy=legacy_policy("read-only")).kind is DecisionKind.DENY


def test_security_api_persists_real_policy_and_returns_no_secret(tmp_path, monkeypatch):
    from channel.desktop import desktop_channel as channel
    import config as config_module
    from agent.permission import center as security_center
    state = tmp_path / "state"
    state.mkdir()
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"agent_permission_mode": "workspace-write", "web_password": "TOPSECRET"}))
    live = {"agent_permission_mode": "workspace-write", "web_password": "TOPSECRET"}
    monkeypatch.setattr(config_module, "conf", lambda: live)
    monkeypatch.setattr(config_module, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(channel, "_require_auth", lambda: None)
    monkeypatch.setattr(channel.web, "header", lambda *args: None)
    monkeypatch.setattr(channel.web, "data", lambda: json.dumps({"target": "global", "policy": {"preset": "strict", "rules": {"network": "deny"}}}).encode())
    monkeypatch.setattr(channel.web, "input", lambda **defaults: type("Params", (), defaults)())
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.mcp_config_file", lambda *args, **kwargs: state / "mcp.json")
    monkeypatch.setattr(security_center, "_env_path", lambda: tmp_path / "missing.env")
    saved = json.loads(channel.SecurityPolicyHandler().POST())
    assert saved["status"] == "success"
    assert json.loads(config_file.read_text())["security_policy"]["rules"]["network"] == "deny"
    overview = json.loads(channel.SecurityCenterHandler().GET())
    assert overview["global_policy"]["preset"] == "strict"
    assert overview["summary"]["app_password_set"] is True
    assert "TOPSECRET" not in json.dumps(overview)


def test_shell_does_not_inherit_backend_secret(tmp_path, monkeypatch):
    from agent.tools.bash.bash import Bash
    monkeypatch.setenv("TEST_SECRET_TOKEN", "TOPSECRET")
    tool = Bash({"cwd": str(tmp_path), "safety_mode": False})
    result = tool.execute({"command": "python3 -c 'import os; print(os.getenv(\"TEST_SECRET_TOKEN\", \"missing\"))'"})
    assert result.status == "success"
    assert "missing" in str(result.result)
    assert "TOPSECRET" not in str(result.result)


def test_file_search_and_send_cannot_expose_config_secret(tmp_path, monkeypatch):
    from agent.tools.search_files.search_files import SearchFiles
    from agent.tools.send.send import Send
    monkeypatch.setattr("config.get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path / "state")
    monkeypatch.setattr("common.state_dir.mcp_config_file", lambda *args, **kwargs: tmp_path / "state" / "mcp.json")
    (tmp_path / "config.json").write_text('TOPSECRET')
    (tmp_path / "ordinary.txt").write_text('hello')
    search = SearchFiles({"cwd": str(tmp_path)})
    result = search.execute({"pattern": "TOPSECRET", "path": str(tmp_path)})
    assert result.status == "success"
    assert "TOPSECRET" not in str(result.result)
    assert "config.json" not in str(result.result)
    try:
        Send({"cwd": str(tmp_path)})._resolve_path(str(tmp_path / "config.json"))
        assert False, "credential file could be sent"
    except PermissionError:
        pass


def test_skill_write_edit_and_registry_under_read_only_project(tmp_path, monkeypatch):
    from agent.skills.manager import SkillManager
    from agent.tools.write.write import Write
    from agent.tools.edit.edit import Edit
    state = tmp_path / "state"
    skills = state / "skills"
    project = tmp_path / "project"
    skills.mkdir(parents=True)
    project.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: state)
    monkeypatch.setattr("common.state_dir.skills_dir", lambda *args, **kwargs: skills)
    monkeypatch.setattr("common.state_dir.mcp_config_file", lambda *args, **kwargs: state / "mcp.json")

    class ProjectAgent:
        def effective_permission_mode(self):
            return "read-only"

        def effective_cwd(self):
            return str(project)

        def write_roots(self):
            return [str(project)]

    target = skills / "example" / "SKILL.md"
    writer = Write({"cwd": str(project), "restrict_to_workspace": True})
    writer.context = ProjectAgent()
    content = "---\nname: example\ndescription: Example skill\n---\n# Example\nFirst version.\n"
    assert writer.execute_tool({"path": str(target), "content": content}).status == "success"
    editor = Edit({"cwd": str(project)})
    editor.context = ProjectAgent()
    assert editor.execute_tool({"path": str(target), "oldText": "First version.", "newText": "Second version."}).status == "success"
    manager = SkillManager(builtin_dir=str(tmp_path / "builtin"), custom_dir=str(skills))
    manager.refresh_skills()
    assert manager.get_skill("example") is not None
    assert "Second version." in target.read_text()
    assert not (project / "SKILL.md").exists()


def test_project_git_and_network_rules_reach_execution(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: state)
    monkeypatch.setattr("common.state_dir.skills_dir", lambda *args, **kwargs: state / "skills")
    strict = legacy_policy("read-only")
    strict["rules"] = {"git": "allow", "network": "deny"}
    scope = Scope(write_roots=(str(tmp_path),))
    assert SecurityGateway.check("read-only", "bash", {"command": "git status"}, cwd=str(tmp_path),
                                 scope=scope, policy=strict).allowed
    assert SecurityGateway.check("read-only", "bash", {"command": "git clone https://example.com/repo"},
                                 cwd=str(tmp_path), scope=scope, policy=strict).kind is DecisionKind.DENY
    assert SecurityGateway.check("read-only", "bash", {"command": "python3 -c 'print(1)'"},
                                 cwd=str(tmp_path), scope=scope, policy=strict).kind is DecisionKind.DENY
    standard = legacy_policy("workspace-write")
    standard["connections"] = {"browser": {"allowed": False, "scopes": ["*"]}}
    assert SecurityGateway.check("workspace-write", "browser", {"action": "navigate"},
                                 policy=standard).kind is DecisionKind.DENY
    standard["connections"]["browser"]["allowed"] = True
    assert SecurityGateway.check("workspace-write", "browser", {"action": "screenshot"},
                                 policy=standard).allowed


def test_model_secret_status_and_revoke_without_plaintext(tmp_path, monkeypatch):
    import config as config_module
    from agent.permission import center as security_center
    saved = {"open_ai_api_key": ""}
    (tmp_path / "config.json").write_text(json.dumps(saved))
    monkeypatch.setattr(config_module, "conf", lambda: saved)
    monkeypatch.setattr(config_module, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(security_center, "_env_path", lambda: tmp_path / "empty.env")
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path / "state")
    security_center.set_secret("OPENAI_API_KEY", "TOPSECRET")
    assert saved["open_ai_api_key"] == "TOPSECRET"
    assert (tmp_path / "config.json").stat().st_mode & 0o777 == 0o600
    status = security_center.secrets()
    assert status == [{"name": "OPENAI_API_KEY", "source": "model configuration", "configured": True}]
    assert "TOPSECRET" not in json.dumps(status)
    security_center.set_secret("OPENAI_API_KEY", None)
    assert saved["open_ai_api_key"] == ""
    assert "OPENAI_API_KEY" not in config_module.os.environ


def test_live_tool_gate_uses_project_and_conversation_context(tmp_path, monkeypatch):
    from agent.runtime.tool_invocation import permission_denial
    from common.runtime_identity import identity_scope
    import config as config_module
    state = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr(config_module, "conf", lambda: {
        "agent_permission_mode": "workspace-write",
        "security_policy": {"preset": "standard", "rules": {}, "connections": {}},
    })
    project_store.set_project_dir("live-session", str(project))
    project_store.set_security_policy(str(project), {"rules": {"network": "deny"}})

    class LiveAgent:
        def effective_permission_mode(self):
            return "workspace-write"

        def effective_cwd(self):
            return str(project)

        def write_roots(self):
            return [str(project)]

    with identity_scope(session_id="live-session"):
        assert permission_denial("web_fetch", {"url": "https://example.com"}, agent=LiveAgent())
        session_prefs.set_prefs("live-session", security_policy={"rules": {"network": "allow"}})
        assert permission_denial("web_fetch", {"url": "https://example.com"}, agent=LiveAgent()) is None


def test_mcp_connection_scope_controls_registered_tools(tmp_path, monkeypatch):
    from agent.permission.gateway import Capability, register_tool
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path)
    register_tool("create_issue", Capability.EXTERNAL, connection="mcp:github")
    policy = legacy_policy("workspace-write")
    policy["connections"] = {"mcp:github": {"allowed": True, "scopes": ["read"]}}
    denied = SecurityGateway.check("workspace-write", "create_issue", {"title": "Example"}, policy=policy)
    assert denied.kind is DecisionKind.DENY
    assert "scope create" in denied.reason
    policy["connections"]["mcp:github"]["scopes"] = ["create"]
    assert SecurityGateway.check("workspace-write", "create_issue", {"title": "Example"}, policy=policy).allowed
    policy["connections"]["mcp:github"]["allowed"] = False
    assert SecurityGateway.check("workspace-write", "create_issue", {"title": "Example"}, policy=policy).kind is DecisionKind.DENY
