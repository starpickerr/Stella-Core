import json
import pytest

from agent.permission.audit import recent
from agent.permission.gateway import DecisionKind, Scope, SecurityGateway
from agent.permission.security_policy import (MODE_DEFINITIONS, copy_custom, default_policy, effective_mode,
                                              effective_rules, legacy_policy, resolve, rule, validate_patch)
from agent.workspace import project_store, session_prefs


def test_managed_skills_require_dedicated_settings_flow(tmp_path, monkeypatch):
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
    assert result.kind is DecisionKind.DENY
    assert result.resource_kind.value == "agent-managed"
    assert not SecurityGateway.check("read-only", "edit", {"path": str(skills / "example" / "SKILL.md")},
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
    assert rows[0]["trace"][-1] == "Decision: deny"


def test_full_access_allows_high_risk_and_keeps_hard_denials(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    work = tmp_path / "work"
    monkeypatch.setattr("agent.workspace.context.personal_work_dir", lambda **kwargs: work)
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: state)
    monkeypatch.setattr("common.state_dir.skills_dir", lambda *args, **kwargs: state / "skills")
    monkeypatch.setattr("common.state_dir.mcp_config_file", lambda *args, **kwargs: state / "mcp.json")
    monkeypatch.setattr("config.get_data_root", lambda: str(state))
    from agent.workspace.context import resolve_context
    owner = resolve_context("owner", "alpha", ensure=True)
    (owner.root / "secret.txt").write_text("secret")
    policy = {"preset": "full-access", "rules": {}}
    pushed = SecurityGateway.check("full-access", "bash", {"command": "git push origin main"},
                                   cwd=str(tmp_path), session_id="risk", policy=policy)
    assert pushed.kind is DecisionKind.ALLOW
    assert SecurityGateway.check("full-access", "bash", {"command": "sudo true"},
                                 cwd=str(tmp_path), policy=policy).kind is DecisionKind.DENY
    assert SecurityGateway.check("full-access", "read", {"path": str(state / "config.json")},
                                 cwd=str(tmp_path), policy=policy).kind is DecisionKind.DENY
    denied = SecurityGateway.check("full-access", "read", {"path": str(owner.root / "secret.txt")},
                                   cwd=str(tmp_path), session_id="recipient", agent_id="alpha", policy=policy)
    assert denied.kind is DecisionKind.DENY


def test_risk_confirmation_and_credential_denial(tmp_path, monkeypatch, security_audit_path):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: state)
    monkeypatch.setattr("common.state_dir.skills_dir", lambda *args, **kwargs: state / "skills")
    monkeypatch.setattr("common.state_dir.mcp_config_file", lambda *args, **kwargs: state / "mcp.json")
    monkeypatch.setattr("config.get_data_root", lambda: str(state))
    policy = legacy_policy("workspace-write")
    args = {"command": "git push origin main"}
    first = SecurityGateway.check("workspace-write", "bash", args, cwd=str(tmp_path), session_id="risk", policy=policy)
    assert first.kind is DecisionKind.CONFIRM
    assert SecurityGateway.approve(first.request_id)
    assert SecurityGateway.check("workspace-write", "bash", args, cwd=str(tmp_path), session_id="risk", policy=policy).allowed
    rejected = SecurityGateway.check("workspace-write", "bash", args, cwd=str(tmp_path), session_id="risk", policy=policy)
    assert rejected.kind is DecisionKind.CONFIRM
    assert SecurityGateway.reject(rejected.request_id)
    assert not SecurityGateway.approve(rejected.request_id)
    assert any(row["event"] == "confirmation" and row["decision"] == "deny"
               for row in recent(filters={"conversation": "risk"}))
    assert SecurityGateway.check("workspace-write", "bash", {"command": "sudo true"}, cwd=str(tmp_path), policy=policy).kind is DecisionKind.DENY
    assert SecurityGateway.check("workspace-write", "read", {"path": str(state / "config.json")}, cwd=str(tmp_path), policy=policy).kind is DecisionKind.DENY
    assert "TOPSECRET" not in security_audit_path.read_text()


def test_policy_inheritance_and_restart_persistence(tmp_path, monkeypatch):
    state = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    project_store.set_security_policy(str(project), {
        "preset": "custom", "base_preset": "workspace-write",
        "rules": {"network": "deny", "shell": "allow"}, "connections": {},
    })
    project_store.set_project_dir("conversation", str(project))
    session_prefs.set_prefs("conversation", security_policy={
        "preset": "custom", "base_preset": "workspace-write",
        "rules": {"network": "allow"}, "extra_roots": [str(tmp_path / "extra")],
    })
    global_value = {"preset": "read-only", "rules": {}, "connections": {}}
    effective = resolve("workspace-write", project_dir=str(project), session_id="conversation", global_value=global_value)
    assert rule(effective, "network") == "deny"
    assert rule(effective, "shell") == "allow"
    assert rule(effective, "workspace_write") == "allow"
    assert effective["extra_roots"] == [str(tmp_path / "extra")]
    assert project_store.get_security_policy(str(project))["rules"]["network"] == "deny"


def test_global_policy_rejects_custom_preset():
    with pytest.raises(ValueError, match="custom"):
        validate_patch({"preset": "custom", "base_preset": "workspace-write",
                        "rules": {"network": "deny"}}, global_policy=True)


def test_global_policy_switch_strips_legacy_custom_fields(tmp_path, monkeypatch):
    """Old installs stored custom global defaults; switching to a product preset must succeed."""
    from agent.permission import center as security_center
    import config as config_module

    state = tmp_path / "state"
    state.mkdir()
    config_path = state / "config.json"
    config_path.write_text(json.dumps({
        "security_policy": {
            "preset": "custom",
            "base_preset": "workspace-write",
            "rules": {"network": "deny"},
            "connections": {"browser": {"allowed": False}},
        },
    }), encoding="utf-8")
    live = json.loads(config_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(config_module, "get_data_root", lambda: str(state))
    monkeypatch.setattr(config_module, "conf", lambda: live)
    monkeypatch.setattr(config_module, "read_config_template", lambda: {})

    saved = security_center.save_global_policy({
        "preset": "read-only",
        "base_preset": "workspace-write",
        "rules": {},
        "connections": {"browser": {"allowed": False}},
    })
    assert saved == {
        "preset": "read-only",
        "rules": {},
        "connections": {"browser": {"allowed": False}},
    }
    assert "base_preset" not in saved
    assert live["security_policy"]["preset"] == "read-only"


def test_project_policy_ignores_later_global_default_change(tmp_path, monkeypatch):
    state = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    project_store.set_security_policy(str(project), {"preset": "workspace-write", "rules": {}, "connections": {}})
    first = resolve("read-only", project_dir=str(project), global_value={"preset": "workspace-write", "rules": {}, "connections": {}})
    assert rule(first, "workspace_write") == "allow"
    second = resolve("read-only", project_dir=str(project), global_value={"preset": "read-only", "rules": {}, "connections": {}})
    assert rule(second, "workspace_write") == "allow"


def test_standalone_conversation_keeps_independent_snapshot(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    session_prefs.set_prefs("solo", security_policy={"preset": "full-access", "rules": {}, "connections": {}})
    effective = resolve("read-only", session_id="solo", global_value={"preset": "read-only", "rules": {}, "connections": {}})
    assert effective_mode(effective) == "full-access"
    assert rule(effective, "high_risk") == "allow"


def test_create_project_copies_current_global_default(tmp_path, monkeypatch):
    import config as config_module
    from agent.workspace import project_store as store

    state = tmp_path / "state"
    projects = tmp_path / "projects"
    projects.mkdir()
    state.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr(store, "projects_root", lambda: str(projects))
    monkeypatch.setattr(config_module, "conf", lambda: {
        "security_policy": {"preset": "read-only", "rules": {}, "connections": {}},
    })
    path = store.create_project("seeded")
    saved = store.get_security_policy(path)
    assert saved["preset"] == "read-only"
    assert resolve("workspace-write", project_dir=path,
                   global_value={"preset": "full-access", "rules": {}, "connections": {}})["preset"] == "read-only"


def test_migrate_project_conversations_unify_to_project_effective(tmp_path, monkeypatch):
    from agent.permission.security_policy import migrate_project_conversation_policies

    state = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    project_store.set_security_policy(str(project), {"preset": "workspace-write", "rules": {"network": "deny"}, "connections": {}})
    project_store.set_project_dir("chat-a", str(project))
    project_store.set_project_dir("chat-b", str(project))
    session_prefs.set_prefs("chat-a", security_policy={"preset": "read-only", "rules": {}, "connections": {}})
    session_prefs.set_prefs("chat-b", security_policy={"preset": "full-access", "rules": {}, "connections": {}})
    result = migrate_project_conversation_policies(str(project), global_value={"preset": "read-only", "rules": {}, "connections": {}})
    assert result["preset"] == "custom" or result["preset"] == "workspace-write"
    assert rule(result, "network") == "deny"
    assert rule(resolve("read-only", project_dir=str(project), session_id="chat-a",
                        global_value={"preset": "read-only", "rules": {}, "connections": {}}), "network") == "deny"
    assert rule(resolve("read-only", project_dir=str(project), session_id="chat-b",
                        global_value={"preset": "read-only", "rules": {}, "connections": {}}), "network") == "deny"
    assert "security_policy" not in session_prefs.get_prefs("chat-a") or not session_prefs.get_prefs("chat-a").get("security_policy", {}).get("rules")


def test_four_modes_and_legacy_snapshots_are_stable():
    assert [row["id"] for row in MODE_DEFINITIONS] == [
        "read-only", "workspace-write", "full-access", "custom"]
    assert default_policy()["preset"] == "workspace-write"
    assert rule({"preset": "read-only"}, "workspace_write") == "deny"
    assert rule({"preset": "workspace-write"}, "workspace_write") == "allow"
    assert rule({"preset": "workspace-write"}, "workspace_outside") == "confirm"
    assert rule({"preset": "full-access"}, "workspace_outside") == "allow"
    assert rule({"preset": "full-access"}, "high_risk") == "allow"
    approval = validate_patch({"preset": "approval"})
    assert approval["preset"] == "custom"
    assert rule(approval, "workspace_write") == "confirm"
    assert rule(approval, "shell") == "confirm"
    project = validate_patch({"preset": "project-full"})
    assert project["preset"] == "workspace-write"
    assert rule(project, "workspace_outside") == "confirm"
    for old, expected in (("strict", "deny"), ("standard", "allow"), ("custom", "allow")):
        migrated = validate_patch({"preset": old})
        assert migrated["preset"] == "custom"
        assert rule(migrated, "workspace_write") == expected
        assert validate_patch(migrated) == migrated
    copied = copy_custom({"preset": "workspace-write", "rules": {"network": "deny"}})
    assert copied["rules"] == effective_rules(copied)
    assert effective_mode(copied) == "custom"
    assert rule(legacy_policy("read-only"), "workspace_write") == "deny"
    assert rule(legacy_policy("workspace-write"), "workspace_outside") == "deny"


def test_resolve_ignores_caller_mode_when_policy_is_stored():
    stored = {"preset": "read-only", "rules": {}, "connections": {}}
    effective = resolve("full-access", global_value=stored)
    assert rule(effective, "workspace_write") == "deny"
    assert effective_mode(effective) == "read-only"


def test_agent_mode_cannot_widen_persisted_read_only(tmp_path, monkeypatch):
    from agent.runtime.tool_invocation import permission_denial
    import config as config_module

    project = tmp_path / "project"
    project.mkdir()
    live = {
        "security_policy": {"preset": "read-only", "rules": {}, "connections": {}},
        "agent_permission_mode": "workspace-write",
    }
    monkeypatch.setattr(config_module, "conf", lambda: live)
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path / "state")

    class Agent:
        def effective_permission_mode(self):
            return "full-access"

        def effective_cwd(self):
            return str(project)

        def write_roots(self):
            return [str(project)]

    denied = permission_denial("write", {"path": str(project / "note.txt"), "content": "x"}, agent=Agent())
    assert denied


def test_legacy_conversation_permission_is_migrated_once(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    path = state / "session_prefs.json"
    path.write_text(json.dumps({"sessions": {"default::old": {
        "model": "existing-model", "permission": "read-only", "ts": 1,
    }}}))
    prefs = session_prefs.get_prefs("old")
    assert prefs["security_policy"]["preset"] == "custom"
    assert rule(prefs["security_policy"], "workspace_write") == "deny"
    assert prefs["model"] == "existing-model"
    stored = json.loads(path.read_text())["sessions"]["default::old"]
    assert "permission" not in stored
    assert stored["security_policy"]["preset"] == "custom"


def test_trusted_skill_initializer_requires_dedicated_flow(tmp_path, monkeypatch):
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
    assert not SecurityGateway.check("read-only", "bash", {"command": command}, cwd=str(project),
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
    monkeypatch.setattr(channel.web, "data", lambda: json.dumps({"target": "global", "policy": {"preset": "read-only", "rules": {}}}).encode())
    monkeypatch.setattr(channel.web, "input", lambda **defaults: type("Params", (), defaults)())
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.mcp_config_file", lambda *args, **kwargs: state / "mcp.json")
    monkeypatch.setattr(security_center, "_env_path", lambda: tmp_path / "missing.env")
    saved = json.loads(channel.SecurityPolicyHandler().POST())
    assert saved["status"] == "success"
    assert json.loads(config_file.read_text())["security_policy"]["preset"] == "read-only"
    overview = json.loads(channel.SecurityCenterHandler().GET())
    assert overview["global_policy"]["preset"] == "read-only"
    assert rule(overview["global_policy"], "workspace_write") == "deny"
    assert overview["summary"]["app_password_set"] is True
    assert "TOPSECRET" not in json.dumps(overview)


def test_extra_roots_cannot_name_foreign_private_work(tmp_path, monkeypatch):
    from agent.workspace.context import resolve_context

    work = tmp_path / "work"
    monkeypatch.setattr("agent.workspace.context.personal_work_dir", lambda **kwargs: work)
    monkeypatch.setattr("common.state_dir.personal_work_dir", lambda **kwargs: work)
    monkeypatch.setattr("agent.workspace.project_store._store_file", lambda: str(tmp_path / "projects.json"))
    other = resolve_context("other", "alpha", ensure=True)
    with pytest.raises(ValueError, match="private"):
        validate_patch({"extra_roots": [str(other.root / "secret.txt")]})
    with pytest.raises(ValueError, match="private"):
        validate_patch({"extra_roots": [str(work / "shared")]})
    allowed = validate_patch({"extra_roots": [str(tmp_path / "notes")]})
    assert allowed["extra_roots"] == [str(tmp_path / "notes")]


def test_full_access_overview_keeps_enabled_sandbox_status(tmp_path, monkeypatch):
    from agent.permission import center as security_center
    import config as config_module

    live = {"security_policy": {"preset": "full-access", "rules": {}, "connections": {}}}
    work = tmp_path / "work"
    monkeypatch.setattr(config_module, "conf", lambda: live)
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path)
    monkeypatch.setattr("common.state_dir.mcp_config_file", lambda: tmp_path / "mcp.json")
    monkeypatch.setattr("agent.workspace.context.personal_work_dir", lambda **kwargs: work)
    monkeypatch.setattr("agent.permission.process_sandbox.capability",
                        lambda: {"status": "enabled", "reason": "Seatbelt is active."})
    overview = security_center.overview("owner", "alpha")
    assert overview["effective_mode"] == "full-access"
    assert overview["process_isolation"]["status"] == "enabled"
    reason = overview["process_isolation"]["reason"].lower()
    assert "private" in reason or "会话" in overview["process_isolation"]["reason"]


def test_shell_does_not_inherit_backend_secret(tmp_path, monkeypatch):
    from agent.tools.bash.bash import Bash
    monkeypatch.setenv("TEST_SECRET_TOKEN", "TOPSECRET")
    tool = Bash({"cwd": str(tmp_path), "safety_mode": False})
    result = tool.execute({"command": "python3 -c 'import os; print(os.getenv(\"TEST_SECRET_TOKEN\", \"missing\"))'"})
    assert result.status == "success"
    assert "missing" in str(result.result)
    assert "TOPSECRET" not in str(result.result)


def test_global_policy_save_failure_keeps_live_state(tmp_path, monkeypatch):
    from agent.permission import center as security_center
    import config as config_module
    live = {"security_policy": {"preset": "approval", "rules": {}, "connections": {}}}
    monkeypatch.setattr(config_module, "conf", lambda: live)
    monkeypatch.setattr(config_module, "get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(security_center, "_write_config", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        security_center.save_global_policy({"preset": "project-full", "rules": {}})
    assert live["security_policy"]["preset"] == "approval"


def test_corrupt_scoped_stores_fail_closed_and_report_error(tmp_path, monkeypatch):
    from agent.runtime.tool_invocation import permission_denial
    from common.runtime_identity import identity_scope
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path)
    (tmp_path / "projects.json").write_text("{broken", encoding="utf-8")
    with identity_scope(session_id="corrupt-project"):
        assert "Permission check failed" in permission_denial("write", {"path": "note.txt", "content": "x"})
    with pytest.raises(ValueError, match="Project store is invalid"):
        project_store.get_project_dir("corrupt-project")
    (tmp_path / "projects.json").unlink()
    (tmp_path / "session_prefs.json").write_text("{broken", encoding="utf-8")
    policy = resolve("workspace-write", session_id="corrupt-session")
    assert policy["error"] == "Conversation security preferences are invalid."
    assert all(value == "deny" for value in effective_rules(policy).values())


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


def test_skill_write_and_edit_blocked_from_generic_file_tools(tmp_path, monkeypatch):
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
    assert writer.execute_tool({"path": str(target), "content": content}).status == "error"
    target.parent.mkdir(parents=True)
    target.write_text(content)
    editor = Edit({"cwd": str(project)})
    editor.context = ProjectAgent()
    assert editor.execute_tool({"path": str(target), "oldText": "First version.", "newText": "Second version."}).status == "error"
    manager = SkillManager(builtin_dir=str(tmp_path / "builtin"), custom_dir=str(skills))
    manager.refresh_skills()
    assert manager.get_skill("example") is not None
    assert "First version." in target.read_text()
    assert not (project / "SKILL.md").exists()


def test_project_git_and_network_rules_reach_execution(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: state)
    monkeypatch.setattr("common.state_dir.skills_dir", lambda *args, **kwargs: state / "skills")
    strict = legacy_policy("read-only")
    strict["rules"].update({"git": "allow", "network": "deny"})
    scope = Scope(write_roots=(str(tmp_path),))
    assert SecurityGateway.check("read-only", "bash", {"command": "git status"}, cwd=str(tmp_path),
                                 scope=scope, policy=strict).kind is DecisionKind.DENY
    strict["rules"]["shell"] = "allow"
    assert SecurityGateway.check("read-only", "bash", {"command": "git status"}, cwd=str(tmp_path),
                                 scope=scope, policy=strict).allowed
    assert SecurityGateway.check("read-only", "bash", {"command": "git clone https://example.com/repo"},
                                 cwd=str(tmp_path), scope=scope, policy=strict).kind is DecisionKind.DENY
    assert SecurityGateway.check("read-only", "bash", {"command": "python3 -c 'print(1)'"},
                                 cwd=str(tmp_path), scope=scope, policy=strict).allowed
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
    project_store.set_security_policy(str(project), {
        "preset": "custom", "base_preset": "workspace-write",
        "rules": {"network": "deny"}, "connections": {},
    })

    class LiveAgent:
        def effective_permission_mode(self):
            return "workspace-write"

        def effective_cwd(self):
            return str(project)

        def write_roots(self):
            return [str(project)]

    with identity_scope(session_id="live-session"):
        assert permission_denial("web_fetch", {"url": "https://example.com"}, agent=LiveAgent())
        # Project-internal conversation overrides must not widen project policy.
        session_prefs.set_prefs("live-session", security_policy={"rules": {"network": "allow"}})
        assert permission_denial("web_fetch", {"url": "https://example.com"}, agent=LiveAgent())
        project_store.set_security_policy(str(project), {
            "preset": "custom", "base_preset": "workspace-write",
            "rules": {"network": "allow"}, "connections": {},
        })
        assert permission_denial("web_fetch", {"url": "https://example.com"}, agent=LiveAgent()) is None


def test_connections_use_real_service_status(tmp_path, monkeypatch):
    from agent.permission import center as security_center
    import config as config_module

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.mcp_config_file", lambda: state / "mcp.json")
    monkeypatch.setattr(config_module, "conf", lambda: {
        "security_policy": {"preset": "workspace-write", "rules": {}, "connections": {}},
        "github_token": "ghp_test",
    })
    monkeypatch.setattr("agent.briefing.settings.public_mailboxes", lambda: {
        "mailboxes": [{"id": "1", "configured": True, "enabled": True}],
        "configured": True, "missing": [],
    })
    from agent.calendar.apple_sync import AppleCalendarSync
    monkeypatch.setattr(AppleCalendarSync, "status", lambda self: {"connected": True, "authorization": "full_access"})
    monkeypatch.setattr(
        "agent.tools.browser.browser_env.capability_summary",
        lambda config=None: {"ready": False},
    )
    rows = {item["id"]: item for item in security_center.connections()}
    assert rows["email"]["configured"] is True
    assert rows["email"]["available"] is True
    assert rows["email"]["connected"] is True
    assert rows["calendar"]["connected"] is True
    assert rows["browser"]["connected"] is False
    assert rows["browser"]["available"] is False
    assert rows["github"]["configured"] is True
    assert rows["github"]["connected"] is False
    assert rows["github"]["available"] is False
    assert rows["email"]["scopes"] == []
    overview = security_center.overview()
    assert overview["summary"]["connection_count"] == 2


def test_background_tasks_reads_live_automation_store_not_stale_json(tmp_path, monkeypatch):
    """Desktop Security Center must list automation.db tasks, not frozen tasks.json."""
    from agent.permission import center as security_center
    from agent.scheduler.automation_store import AutomationStore
    from types import SimpleNamespace

    state = tmp_path / "state"
    legacy = state / "scheduler" / "tasks.json"
    legacy.parent.mkdir(parents=True)
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr(
        "agent.registry.get_agent_registry",
        lambda: SimpleNamespace(
            default_agent_id="agent-a",
            get=lambda *a, **k: SimpleNamespace(id="agent-a", workspace=str(state)),
        ),
    )
    monkeypatch.setattr("agent.scheduler.integration.get_task_store", lambda *a, **k: None)

    live = AutomationStore(legacy, "agent-a")
    live.add_task({
        "id": "live-task", "name": "项目检查", "enabled": True,
        "schedule": {"type": "cron", "expression": "0 9 * * *"},
        "action": {"type": "agent_task", "task_description": "check", "conversation_mode": "reuse"},
        "run_permission_mode": "read-only",
    })
    # Stale JSON left behind after migration — must not drive the Security Center list.
    legacy.write_text(json.dumps({
        "tasks": {
            "old-briefing": {
                "id": "old-briefing", "name": "morning briefing", "enabled": True,
                "schedule": {"type": "cron", "expression": "0 8 * * *"},
                "action": {"type": "send_message", "content": "hi", "channel_type": "web", "receiver": "x"},
            }
        }
    }), encoding="utf-8")

    rows = security_center.background_tasks()
    names = {row["name"] for row in rows}
    assert "项目检查" in names
    assert "morning briefing" not in names


def test_background_task_permission_independent_and_inherited(tmp_path, monkeypatch):

    from agent.permission import center as security_center
    from agent.workspace import project_store
    import config as config_module

    state = tmp_path / "state"
    project = tmp_path / "repo"
    state.mkdir()
    project.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: state)
    monkeypatch.setattr("common.state_dir.scheduler_file", lambda *args, **kwargs: state / "scheduler" / "tasks.json")
    monkeypatch.setattr(config_module, "conf", lambda: {
        "security_policy": {"preset": "read-only", "rules": {}, "connections": {}},
    })
    project_store.set_security_policy(str(project), {"preset": "workspace-write", "rules": {}})
    project_store.set_project_dir("chat-a", str(project))

    independent = security_center.describe_task_permission({
        "id": "t1", "name": "独立", "enabled": True,
        "run_permission_mode": "full-access",
        "action": {"conversation_mode": "new", "execution_project_dir": str(project)},
    })
    assert independent["effective_mode"] == "full-access"
    assert independent["permission_source"] == "independent"
    assert independent["unknown"] is False

    inherited = security_center.describe_task_permission({
        "id": "t2", "name": "继承", "enabled": False,
        "action": {
            "conversation_mode": "source",
            "source_session_id": "chat-a",
            "execution_session_id": "chat-a",
            "execution_project_dir": str(project),
        },
    })
    assert inherited["effective_mode"] == "workspace-write"
    assert inherited["permission_source"] == "project"
    assert inherited["enabled"] is False

    unknown = security_center.describe_task_permission({
        "id": "t3", "name": "未知", "enabled": True,
        "action": {"conversation_mode": "new"},
    })
    assert unknown["unknown"] is True
    assert unknown["permission_source"] == "unspecified"


def test_privacy_inventory_reports_real_paths(tmp_path, monkeypatch, security_audit_path):
    from agent.permission import privacy as privacy_mod

    state = tmp_path / "state"
    state.mkdir()
    tmp = state / "tmp"
    tmp.mkdir()
    (tmp / "scratch.bin").write_bytes(b"abc")
    security_audit_path.write_text("{}\n")
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: state)
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.tmp_dir", lambda *args, **kwargs: tmp)
    monkeypatch.setattr("common.state_dir.scheduler_file", lambda *args, **kwargs: state / "scheduler" / "tasks.json")
    monkeypatch.setattr("common.state_dir.briefing_db", lambda *args, **kwargs: state / "briefing" / "briefing.db")
    monkeypatch.setattr("common.state_dir.runs_dir", lambda *args, **kwargs: state / "runs")
    monkeypatch.setattr("common.state_dir.memory_index_db", lambda *args, **kwargs: state / "memory" / "long-term" / "index.db")
    monkeypatch.setattr("agent.permission.audit._path", lambda: security_audit_path)

    inventory = privacy_mod.inventory()
    by_id = {row["id"]: row for row in inventory["categories"]}
    assert by_id["temporary"]["bytes"] == 3
    assert str(tmp) in by_id["temporary"]["path"]
    assert by_id["security_activity"]["bytes"] >= 1
    assert "clear_temporary" in by_id["temporary"]["actions"]

    cleared = privacy_mod.cleanup("clear_temporary")
    assert cleared["status"] == "success"
    assert list(tmp.iterdir()) == []
    after = {row["id"]: row for row in privacy_mod.inventory()["categories"]}
    assert after["temporary"]["bytes"] == 0


def test_activity_counts_dedupe_by_operation_id(security_audit_path):
    from agent.permission.audit import activity_counts, record

    now = 1_700_000_000.0
    record(tool="bash", decision="allow", event="tool_decision", operation_id="auto-1")
    record(tool="bash", decision="confirm", event="tool_decision", operation_id="ask-1")
    record(tool="bash", decision="allow", event="confirmation", operation_id="ask-1")
    record(tool="write", decision="deny", event="tool_decision", operation_id="deny-1")
    record(tool="write", decision="deny", event="tool_decision", operation_id="deny-1")
    # Rewrite timestamps into a known window.
    rows = [json.loads(line) for line in security_audit_path.read_text().splitlines() if line.strip()]
    for index, row in enumerate(rows):
        row["at"] = now - 60 + index
        if row["decision"] == "confirm":
            row["at"] = now - 30
    security_audit_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    counts = activity_counts(days=7, now=now)
    assert counts == {
        "auto_allow": 1,
        "user_authorized": 1,
        "denied": 1,
        "uncertain": False,
        "since": now - 7 * 86400,
        "until": now,
    }


def test_activity_counts_marks_legacy_rows_uncertain(security_audit_path):
    from agent.permission.audit import activity_counts

    now = 1_700_000_100.0
    security_audit_path.write_text(json.dumps({
        "at": now - 10, "tool": "read", "decision": "allow", "event": "tool_decision",
        "conversation": "c1",
    }) + "\n")
    counts = activity_counts(days=7, now=now)
    assert counts["auto_allow"] == 1
    assert counts["uncertain"] is True


def test_overview_exposes_activity_counts(tmp_path, monkeypatch, security_audit_path):
    from agent.permission import center as security_center
    from agent.permission.audit import record
    import config as config_module

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("common.state_dir.shared_root", lambda: state)
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: state)
    monkeypatch.setattr("common.state_dir.mcp_config_file", lambda: state / "mcp.json")
    monkeypatch.setattr(config_module, "conf", lambda: {
        "security_policy": {"preset": "workspace-write", "rules": {}, "connections": {}},
    })
    monkeypatch.setattr("agent.briefing.settings.public_mailboxes", lambda: {
        "mailboxes": [], "configured": False, "missing": [],
    })
    monkeypatch.setattr(
        "agent.tools.browser.browser_env.capability_summary",
        lambda config=None: {"ready": False},
    )
    from agent.calendar.apple_sync import AppleCalendarSync
    monkeypatch.setattr(AppleCalendarSync, "status", lambda self: {"connected": False})
    record(tool="read", decision="allow", event="tool_decision", operation_id="ov-1")
    overview = security_center.overview()
    assert overview["summary"]["activity_counts"]["auto_allow"] == 1
    assert overview["summary"]["activity_counts"]["user_authorized"] == 0
    assert overview["summary"]["activity_counts"]["denied"] == 0


def test_secrets_include_custom_providers_without_plaintext(tmp_path, monkeypatch):
    from agent.permission import center as security_center
    import config as config_module

    monkeypatch.setattr(config_module, "conf", lambda: {
        "open_ai_api_key": "sk-live",
        "custom_providers": [
            {"id": "my-lab", "name": "My Lab", "api_key": "secret-key"},
            {"id": "empty", "name": "Empty", "api_key": ""},
        ],
    })
    monkeypatch.setattr(security_center, "_env_path", lambda: tmp_path / "missing.env")
    status = security_center.secrets()
    names = {row["name"] for row in status}
    assert "OPENAI_API_KEY" in names
    assert "CUSTOM:my-lab" in names
    assert "CUSTOM:empty" not in names
    custom = next(row for row in status if row["name"] == "CUSTOM:my-lab")
    assert custom["display_name"] == "My Lab"
    assert "secret-key" not in json.dumps(status)


def test_custom_secret_names_follow_provider_renames(tmp_path, monkeypatch):
    from agent.permission import center as security_center
    import config as config_module

    provider = {"id": "c483bd9c", "name": "  灵算  ", "api_key": "private-test-key"}
    monkeypatch.setattr(config_module, "conf", lambda: {"custom_providers": [provider]})
    monkeypatch.setattr(security_center, "_env_path", lambda: tmp_path / "missing.env")
    assert security_center.secrets() == [{
        "name": "CUSTOM:c483bd9c", "display_name": "灵算",
        "source": "custom model provider", "configured": True,
    }]
    provider["name"] = "packyapi"
    assert security_center.secrets()[0]["display_name"] == "packyapi"
    assert "private-test-key" not in json.dumps(security_center.secrets())


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
    pending = SecurityGateway.check("workspace-write", "create_issue", {"title": "Example"}, policy=policy)
    assert pending.kind is DecisionKind.CONFIRM
    assert SecurityGateway.approve(pending.request_id)
    assert SecurityGateway.check("workspace-write", "create_issue", {"title": "Example"}, policy=policy).allowed
    policy["connections"]["mcp:github"]["allowed"] = False
    assert SecurityGateway.check("workspace-write", "create_issue", {"title": "Example"}, policy=policy).kind is DecisionKind.DENY
