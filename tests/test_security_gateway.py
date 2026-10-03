import json
import logging

from agent.permission.gateway import Capability, Scope, SecurityGateway
from agent.runtime.tool_invocation import permission_denial
from agent.tools.write.write import Write
from agent.permission.policy import normalize_mode
from common.log import _SecretFilter


def test_gateway_read_only_and_project_scope(tmp_path, monkeypatch):
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path / "state")
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir()
    other.mkdir()
    scope = Scope(write_roots=(str(project),))
    assert not SecurityGateway.check("read-only", "write", {"path": str(project / "a")}, cwd=str(project), scope=scope)
    assert SecurityGateway.check("workspace-write", "write", {"path": str(project / "a")}, cwd=str(project), scope=scope)
    assert not SecurityGateway.check("workspace-write", "write", {"path": str(other / "a")}, cwd=str(project), scope=scope)
    link = project / "escape"
    link.symlink_to(other, target_is_directory=True)
    assert not SecurityGateway.check("workspace-write", "write", {"path": str(link / "a")}, cwd=str(project), scope=scope)


def test_gateway_allowlist_unknown_capability_and_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path)
    assert not SecurityGateway.check("full-access", "write", {"path": "x"}, allowlist=["read"])
    assert not SecurityGateway.check("full-access", "mystery_tool", {})
    assert not SecurityGateway.check("full-access", "read", {"path": "x"}, capability="unknown")
    accounts = Scope(accounts=("authorized",))
    assert SecurityGateway.check("full-access", "browser", {"action": "navigate", "account_id": "authorized"}, scope=accounts)
    assert not SecurityGateway.check("full-access", "browser", {"action": "navigate", "account_id": "other"}, scope=accounts)
    assert not SecurityGateway.check("full-access", "browser", {"action": "navigate"}, scope=accounts)
    args = {"action": "evaluate", "script": "document.title"}
    assert not SecurityGateway.check("full-access", "browser", args, session_id="s")
    pending = [row for row in SecurityGateway.pending() if row["session"] == "s"]
    assert pending
    assert pending[-1]["summary"] == "document.title"
    assert SecurityGateway.approve(pending[-1]["id"])
    assert SecurityGateway.check("full-access", "browser", args, session_id="s")
    assert not SecurityGateway.check("full-access", "browser", args, session_id="s")
    assert not SecurityGateway.check("full-access", "bash", {"command": "rm -rf password=TOPSECRET"}, session_id="secret")
    assert "TOPSECRET" not in str(SecurityGateway.pending())


def test_direct_tool_entry_cannot_skip_gateway(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.runtime.tool_invocation.global_mode", lambda: "read-only")
    target = tmp_path / "denied.txt"
    result = Write({"cwd": str(tmp_path)}).execute_tool({"path": str(target), "content": "no"})
    assert result.status == "error"
    assert not target.exists()


def test_session_override_and_audit_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path)
    from config import conf

    class SessionAgent:
        def effective_permission_mode(self):
            return "read-only"

        def effective_cwd(self):
            return str(tmp_path)

        def write_roots(self):
            return [str(tmp_path)]

    assert permission_denial("write", {"path": str(tmp_path / "file"), "content": "api_key=TOPSECRET"}, agent=SessionAgent())
    monkeypatch.setitem(conf(), "agent_account_allowlist", ["authorized"])
    monkeypatch.setitem(conf(), "agent_tool_allowlist", ["browser"])
    assert permission_denial("browser", {"action": "navigate", "account_id": "other"}, agent=SessionAgent())
    assert permission_denial("read", {"path": str(tmp_path / "file")}, agent=SessionAgent())
    audit = (tmp_path / "security-activity.jsonl").read_text()
    assert "TOPSECRET" not in audit
    assert all("arguments" not in row for row in map(json.loads, audit.splitlines()))

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "Authorization: Bearer TOPSECRET, password=TOPSECRET", (), None)
    _SecretFilter().filter(record)
    assert "TOPSECRET" not in record.getMessage()


def test_unknown_mode_denied():
    assert not SecurityGateway.check("unexpected", "read", {"path": "x"})
    assert normalize_mode("unexpected") == "read-only"
