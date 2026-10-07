from pathlib import Path

import pytest

from agent.permission.gateway import DecisionKind, Scope, SecurityGateway
from agent.permission.security_policy import default_policy
from agent.skills.authoring import SkillAuthoring
from agent.skills.manager import SkillManager
from agent.tools import ToolManager
from agent.tools.skill.skill_tool import SkillTool


def document(name, body="Do the task."):
    return f"---\nname: {name}\ndescription: Use when asked to do the task.\n---\n\n# {name}\n\n{body}\n"


def test_skill_tool_registered_for_agent():
    manager = ToolManager()
    manager.load_tools()
    assert isinstance(manager.create_tool("skill"), SkillTool)
    assert manager.list_tools()["skill"]["parameters"]["parameters"]["required"] == ["action", "name", "content"]


def test_full_access_skill_tool_is_allowed_without_opening_generic_writes(tmp_path, monkeypatch):
    root = tmp_path / "state"
    skills = root / "skills"
    skills.mkdir(parents=True)
    monkeypatch.setattr("common.state_dir.shared_root", lambda: root)
    monkeypatch.setattr("common.state_dir.state_root", lambda *args, **kwargs: root)
    monkeypatch.setattr("common.state_dir.skills_dir", lambda *args, **kwargs: skills)
    scope = Scope(write_roots=(str(tmp_path / "project"),))
    args = {"action": "create", "name": "sample-skill", "content": document("sample-skill")}
    full = {"preset": "full-access", "rules": {}}
    assert SecurityGateway.check("full-access", "skill", args, scope=scope, policy=full).kind is DecisionKind.ALLOW
    assert SecurityGateway.check("workspace-write", "skill", args, scope=scope,
                                 policy=default_policy(), create_pending=False).kind is DecisionKind.CONFIRM
    assert SecurityGateway.check("full-access", "write", {"path": str(skills / "sample-skill" / "SKILL.md")},
                                 scope=scope, policy=full).kind is DecisionKind.DENY


def test_skill_tool_creates_updates_and_refreshes_catalog(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    monkeypatch.setattr("agent.skills.authoring.skills_dir", lambda ensure=False: root)
    tool = SkillTool()
    created = tool.execute({"action": "create", "name": "sample-skill", "content": document("sample-skill")})
    assert created.status == "success"
    target = root / "sample-skill" / "SKILL.md"
    assert target.read_text() == document("sample-skill")
    assert SkillManager(custom_dir=str(root)).get_skill("sample-skill") is not None
    assert tool.execute({"action": "create", "name": "sample-skill", "content": document("sample-skill")}).status == "error"
    updated = tool.execute({"action": "update", "name": "sample-skill", "content": document("sample-skill", "Updated.")})
    assert updated.status == "success" and "Updated." in target.read_text()
    resource = tool.execute({"action": "write_resource", "name": "sample-skill",
                             "path": "scripts/check.py", "content": "print('ok')\n"})
    assert resource.status == "success"
    assert (root / "sample-skill" / "scripts" / "check.py").read_text() == "print('ok')\n"


def test_skill_tool_rejects_traversal_mismatch_and_symlink(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    outside = tmp_path / "outside.txt"
    outside.write_text("safe")
    monkeypatch.setattr("agent.skills.authoring.skills_dir", lambda ensure=False: root)
    tool = SkillTool()
    assert tool.execute({"action": "create", "name": "../escape", "content": document("escape")}).status == "error"
    assert tool.execute({"action": "create", "name": "sample-skill", "content": document("wrong")}).status == "error"
    assert tool.execute({"action": "create", "name": "sample-skill", "content": document("sample-skill")}).status == "success"
    for path in ("../outside.txt", "scripts/../../outside.txt", "SKILL.md"):
        assert tool.execute({"action": "write_resource", "name": "sample-skill",
                             "path": path, "content": "changed"}).status == "error"
    resource = root / "sample-skill" / "scripts" / "link.py"
    resource.parent.mkdir()
    resource.symlink_to(outside)
    assert tool.execute({"action": "write_resource", "name": "sample-skill",
                         "path": "scripts/link.py", "content": "changed"}).status == "error"
    assert outside.read_text() == "safe"


def test_skill_authoring_refuses_builtin_shadow(tmp_path):
    with pytest.raises(ValueError, match="内置技能"):
        SkillAuthoring(tmp_path / "skills").create("skill-creator", document("skill-creator"))
