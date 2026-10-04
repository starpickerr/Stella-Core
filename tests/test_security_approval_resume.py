"""A confirmed tool call resumes in the same run and keeps one request ID."""
import threading
import time

from agent.permission.gateway import DecisionKind, SecurityGateway
from agent.permission.security_policy import legacy_policy
from agent.runtime.tool_invocation import ApprovalRejectedError, permission_denial
from common.runtime_identity import identity_scope


class _Agent:
    def __init__(self, cwd):
        self.cwd = str(cwd)

    def effective_permission_mode(self):
        return "full-access"

    def effective_cwd(self):
        return self.cwd

    def write_roots(self):
        return [self.cwd]


def _pending(session):
    return [row for row in SecurityGateway.pending() if row["session"] == session]


def _wait_for_pending(session):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        rows = _pending(session)
        if rows:
            return rows[0]
        time.sleep(0.01)
    raise AssertionError("approval request was not created")


def test_approval_resumes_same_call_and_request_id_is_stable(tmp_path, monkeypatch, security_audit_path):
    monkeypatch.setattr("agent.permission.security_policy.resolve", lambda *args, **kwargs: legacy_policy("full-access"))
    session = "approval-resume-case"
    args = {"command": "rm -rf old"}
    agent = _Agent(tmp_path)
    finished = []

    def run():
        with identity_scope(session_id=session):
            finished.append(permission_denial("bash", args, agent=agent, wait_for_approval=True,
                                              cancel_event=threading.Event()))

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    request = _wait_for_pending(session)
    assert worker.is_alive()
    second = SecurityGateway.check("full-access", "bash", args, cwd=str(tmp_path), session_id=session,
                                   policy=legacy_policy("full-access"))
    assert second.kind is DecisionKind.CONFIRM and second.request_id == request["id"]
    assert len(_pending(session)) == 1

    assert SecurityGateway.approve(request["id"])
    worker.join(2)
    assert not worker.is_alive() and finished == [None]
    assert not _pending(session)
    next_request = SecurityGateway.check("full-access", "bash", args, cwd=str(tmp_path), session_id=session,
                                         policy=legacy_policy("full-access"))
    assert next_request.kind is DecisionKind.CONFIRM
    assert SecurityGateway.reject(next_request.request_id)


def test_rejection_stops_waiting_run_without_executing(tmp_path, monkeypatch, security_audit_path):
    monkeypatch.setattr("agent.permission.security_policy.resolve", lambda *args, **kwargs: legacy_policy("full-access"))
    session = "approval-reject-case"
    outcome = []

    def run():
        with identity_scope(session_id=session):
            try:
                permission_denial("bash", {"command": "rm -rf old"}, agent=_Agent(tmp_path),
                                  wait_for_approval=True, cancel_event=threading.Event())
            except ApprovalRejectedError:
                outcome.append("rejected")

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    request = _wait_for_pending(session)
    assert SecurityGateway.reject(request["id"])
    worker.join(2)
    assert not worker.is_alive() and outcome == ["rejected"]
    assert not _pending(session)


def test_stopping_conversation_removes_pending_request(tmp_path, monkeypatch, security_audit_path):
    from agent.protocol.cancel import AgentCancelledError

    monkeypatch.setattr("agent.permission.security_policy.resolve", lambda *args, **kwargs: legacy_policy("full-access"))
    session = "approval-cancel-case"
    event = threading.Event()
    outcome = []

    def run():
        with identity_scope(session_id=session):
            try:
                permission_denial("bash", {"command": "rm -rf old"}, agent=_Agent(tmp_path),
                                  wait_for_approval=True, cancel_event=event)
            except AgentCancelledError:
                outcome.append("cancelled")

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    request = _wait_for_pending(session)
    event.set()
    worker.join(2)
    assert not worker.is_alive() and outcome == ["cancelled"]
    assert not _pending(session)
    assert not SecurityGateway.approve(request["id"])


def test_rejected_approval_stops_agent_turn_instead_of_inviting_a_workaround():
    from agent.protocol.agent_stream import AgentStreamExecutor

    executor = object.__new__(AgentStreamExecutor)
    executor.tools = {}
    executor._permission_denial = lambda *_: (_ for _ in ()).throw(ApprovalRejectedError("rejected"))
    executor._required_params = lambda *_: []
    events = []
    executor._emit_event = lambda kind, data: events.append((kind, data))

    result = executor._execute_tool({"id": "call-1", "name": "bash", "arguments": {"command": "rm -rf old"}})

    assert result["status"] == "critical_error"
    assert events[-1][1]["permission_denied"] is True


def test_agent_executes_original_tool_once_after_inline_approval(tmp_path, monkeypatch, security_audit_path):
    from agent.protocol.agent_stream import AgentStreamExecutor
    from agent.tools.base_tool import BaseTool, ToolResult

    monkeypatch.setattr("agent.permission.security_policy.resolve", lambda *args, **kwargs: legacy_policy("full-access"))
    session = "approval-agent-case"
    called = []

    class Tool(BaseTool):
        name = "bash"
        params = {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}

        def execute(self, params):
            called.append(params["command"])
            return ToolResult.success("done")

    agent = _Agent(tmp_path)
    agent.skill_manager = None
    executor = object.__new__(AgentStreamExecutor)
    executor.tools = {"bash": Tool()}
    executor.agent = agent
    executor.model = None
    executor.cancel_event = threading.Event()
    executor._check_consecutive_failures = lambda *_: (False, None, False)
    executor._record_tool_result = lambda *_: None
    executor._emit_event = lambda *_: None
    results = []

    def run():
        with identity_scope(session_id=session):
            results.append(executor._execute_tool({"id": "call-1", "name": "bash",
                                                   "arguments": {"command": "rm -rf old"}}))

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    request = _wait_for_pending(session)
    assert called == [] and worker.is_alive()
    assert SecurityGateway.approve(request["id"])
    worker.join(2)
    assert not worker.is_alive()
    assert called == ["rm -rf old"]
    assert results[0]["status"] == "success"


def test_interactive_approval_is_reserved_even_if_approved_before_wait_starts(tmp_path, security_audit_path):
    session = "approval-early-case"
    args = {"command": "rm -rf old"}
    policy = legacy_policy("full-access")
    first = SecurityGateway.check("full-access", "bash", args, cwd=str(tmp_path),
                                  session_id=session, policy=policy, reserve_for_waiter=True)
    assert first.kind is DecisionKind.CONFIRM
    assert SecurityGateway.approve(first.request_id)
    # A different caller cannot spend the one-use approval reserved for the paused run.
    other = SecurityGateway.check("full-access", "bash", args, cwd=str(tmp_path),
                                  session_id=session, policy=policy)
    assert other.kind is DecisionKind.DENY
    assert SecurityGateway.wait_for_decision(first.request_id) == "approved"
    resumed = SecurityGateway.check("full-access", "bash", args, cwd=str(tmp_path),
                                    session_id=session, policy=policy,
                                    approval_request_id=first.request_id)
    assert resumed.allowed
    next_request = SecurityGateway.check("full-access", "bash", args, cwd=str(tmp_path),
                                         session_id=session, policy=policy)
    assert next_request.kind is DecisionKind.CONFIRM
    assert SecurityGateway.reject(next_request.request_id)
