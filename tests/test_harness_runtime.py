import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.permission.policy import check_tool_call
from agent.runtime.run_record import RunRecord
from agent.runtime.session_run import SessionRun
from agent.runtime.tool_invocation import permission_denial
from agent.scheduler.automation_store import AutomationStore
from agent.scheduler.service import SchedulerService
from common.runtime_identity import identity_scope
from application import Application, RequestContext
from application.operations import OutcomeUnknown


def test_bills_writes_are_refused_in_read_only():
    for action in ("add", "update", "delete"):
        assert not check_tool_call("read-only", "bills", {"action": action})
    for action in ("list", "get", "statements", "statement"):
        assert check_tool_call("read-only", "bills", {"action": action})
    assert not check_tool_call("read-only", "unclassified_mcp_tool", {})


def test_policy_failure_refuses_tool(monkeypatch):
    class BrokenAgent:
        def effective_permission_mode(self):
            return "read-only"

        def effective_cwd(self):
            raise RuntimeError("policy storage failed")

    assert permission_denial("bills", {"action": "add"}, agent=BrokenAgent())


def test_session_run_serializes_only_matching_session():
    gate = SessionRun()
    entered = threading.Event()
    release = threading.Event()
    same = threading.Event()
    different = threading.Event()

    def first():
        with gate.enter("u", "a", "s"):
            entered.set()
            release.wait(2)

    def second():
        entered.wait(2)
        with gate.enter("u", "a", "s"):
            same.set()

    def third():
        entered.wait(2)
        with gate.enter("u", "a", "other"):
            different.set()

    threads = [threading.Thread(target=fn) for fn in (first, second, third)]
    for thread in threads:
        thread.start()
    assert different.wait(1)
    assert not same.is_set()
    release.set()
    for thread in threads:
        thread.join(2)
    assert same.is_set()


def test_run_record_does_not_mark_live_parallel_run_unknown(tmp_path):
    path = tmp_path / "runs.db"
    first = RunRecord(path)
    first.create("r1")
    first.transition("r1", "running")
    second = RunRecord(path)
    second.create("r2")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT status FROM runs WHERE run_id='r1'").fetchone()[0] == "running"


def test_automation_migrates_once_and_claims_occurrence(tmp_path):
    legacy = tmp_path / "scheduler" / "tasks.json"
    legacy.parent.mkdir(parents=True)
    task = {"id": "daily-briefing", "enabled": True,
            "next_run_at": "2026-10-02T08:00:00", "action": {"type": "tool_call", "silent": True}}
    legacy.write_text(json.dumps({"tasks": {task["id"]: task},
                                  "initialized_defaults": [task["id"]]}))
    store = AutomationStore(legacy, "primary")
    assert store.get_task(task["id"])["action"] == task["action"]
    assert Path(str(legacy) + ".migration.bak").exists()
    assert not store.ensure_default_task(task)
    first = store.claim_occurrence(task["id"], task["next_run_at"])
    assert first
    assert store.claim_occurrence(task["id"], task["next_run_at"]) is None
    store.finish_occurrence(first, True)
    assert store.claim_occurrence(task["id"], task["next_run_at"]) is None
    reopened = AutomationStore(legacy, "primary")
    assert reopened.get_task(task["id"])


def test_application_command_idempotency_and_unknown_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr("application.operations.user_root", lambda: tmp_path)
    calls = []

    class Port:
        def create_todo(self, payload):
            calls.append(payload)
            return {"id": str(len(calls))}

    monkeypatch.setattr(Application, "port", lambda *_args: Port())
    context = RequestContext(idempotency_key="job-1")
    first = Application.command("todos", "CreateTodo", {"title": "Review"}, context)
    second = Application.command("todos", "CreateTodo", {"title": "Review"}, context)
    assert first == second
    assert calls == [{"title": "Review"}]

    from application.operations import OperationStore
    store = OperationStore()
    store.admit("job-2", store.payload_hash("todos", "CreateTodo", [{"title": "Other"}]))
    import pytest
    with pytest.raises(OutcomeUnknown):
        Application.command("todos", "CreateTodo", {"title": "Other"},
                            RequestContext(idempotency_key="job-2"))


def test_automation_queries_are_user_scoped(tmp_path):
    store = AutomationStore(tmp_path / "scheduler" / "tasks.json", "primary")
    with identity_scope(user_id="alice"):
        store.add_task({"id": "alice-job", "enabled": True, "action": {"type": "send_message"}})
        assert store.get_task("alice-job")
    with identity_scope(user_id="bob"):
        assert store.get_task("alice-job") is None
        assert store.list_tasks() == []
        store.add_task({"id": "bob-job", "enabled": True, "action": {"type": "send_message"}})
        assert [row["id"] for row in store.list_tasks()] == ["bob-job"]
        assert store.claim_occurrence("alice-job", "2026-10-02T08:00:00") is None
    assert {row["id"] for row in store.list_tasks(include_all=True)} == {"alice-job", "bob-job"}


def test_completed_occurrence_advances_after_restart_without_reexecution(tmp_path):
    store = AutomationStore(tmp_path / "scheduler" / "tasks.json", "primary")
    scheduled_at = (datetime.now() - timedelta(seconds=5)).isoformat()
    store.add_task({"id": "once", "name": "Once", "enabled": True,
                    "schedule": {"type": "once", "run_at": scheduled_at},
                    "next_run_at": scheduled_at, "action": {"type": "send_message"}})
    job_run_id = store.claim_occurrence("once", scheduled_at)
    store.finish_occurrence(job_run_id, True)
    called = []
    SchedulerService(store, lambda task: called.append(task))._check_and_execute_tasks()
    assert called == []
    completed = store.get_task("once")
    assert completed["enabled"] is False
    assert completed["completed_at"]
    assert completed["next_run_at"] is None
    assert store.occurrence_status("once", scheduled_at) == "completed"


def test_expired_once_task_keeps_its_schedule_for_review(tmp_path):
    store = AutomationStore(tmp_path / "scheduler" / "tasks.json", "primary")
    scheduled_at = (datetime.now() - timedelta(hours=1)).isoformat()
    store.add_task({"id": "once", "name": "Once", "enabled": True,
                    "schedule": {"type": "once", "run_at": scheduled_at},
                    "next_run_at": scheduled_at, "action": {"type": "send_message"}})
    SchedulerService(store, lambda _task: True)._check_and_execute_tasks()
    expired = store.get_task("once")
    assert expired["enabled"] is False
    assert expired["expired_at"]
    assert expired["schedule"]["run_at"] == scheduled_at


def test_expired_running_lease_requires_outcome_review(tmp_path):
    store = AutomationStore(tmp_path / "scheduler" / "tasks.json", "primary")
    store.add_task({"id": "job", "enabled": True, "action": {"type": "tool_call"}})
    scheduled_at = datetime.now().isoformat()
    job_run_id = store.claim_occurrence("job", scheduled_at)
    with sqlite3.connect(store.store_path) as db:
        db.execute("UPDATE job_runs SET lease_until=? WHERE job_run_id=?",
                   ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), job_run_id))
    assert store.claim_occurrence("job", scheduled_at) is None
    assert store.occurrence_status("job", scheduled_at) == "outcome_unknown"
