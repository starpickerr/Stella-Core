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


def test_business_commands_check_current_permissions_before_admission(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr('application.operations.user_root', lambda: tmp_path)
    monkeypatch.setattr('agent.runtime.tool_invocation.global_mode', lambda: 'read-only')
    port = object()
    monkeypatch.setattr(Application, 'port', lambda *_: port)
    with pytest.raises(PermissionError):
        Application.command('todos', 'CreateTodo', {'title': 'Denied'}, RequestContext(idempotency_key='deny'))
    assert not (tmp_path / 'operations.db').exists()


def test_scheduled_tool_records_failure_and_unknown_without_replay(tmp_path, monkeypatch):
    from agent.scheduler import integration
    from agent.tools.tool_manager import ToolManager
    from agent.tools.base_tool import ToolResult
    from types import SimpleNamespace
    from agent.registry import get_agent_registry
    agent_id = get_agent_registry().default_agent_id
    path = tmp_path / 'runs.db'
    monkeypatch.setattr('agent.runtime.run_record.RunRecord', lambda: RunRecord(path))
    monkeypatch.setattr(integration, '_resolve_workspace', lambda *_args, **_kwargs: str(tmp_path))
    monkeypatch.setattr('agent.runtime.tool_invocation.permission_denial', lambda *_args, **_kwargs: None)
    for failure, expected in ((ToolResult.fail('rejected'), 'failed'), (RuntimeError('uncertain'), 'outcome_unknown')):
        store = AutomationStore(tmp_path / expected / 'scheduler' / 'tasks.json', agent_id)
        stamp = (datetime.now() - timedelta(seconds=2)).isoformat()
        task = {'id': expected, 'name': expected, 'enabled': True, 'next_run_at': stamp,
                'schedule': {'type': 'once', 'run_at': stamp},
                'action': {'type': 'tool_call', 'call_name': 'todos', 'call_params': {'action': 'create'}, 'silent': True}}
        store.add_task(task)
        calls = []
        def execute(params):
            calls.append(params)
            if isinstance(failure, Exception):
                raise failure
            return failure
        monkeypatch.setattr(ToolManager, 'create_tool', lambda *_: SimpleNamespace(execute=execute))
        service = SchedulerService(store, lambda run: integration._execute_tool_call(run, None, agent_id))
        service._check_and_execute_tasks()
        assert store.occurrence_status(expected, stamp) == expected
        assert store.get_task(expected)['enabled'] is False
        service._check_and_execute_tasks()
        assert len(calls) == 1
    with sqlite3.connect(path) as db:
        rows = db.execute('SELECT status,job_run_id FROM runs').fetchall()
        assert {row[0] for row in rows} == {'failed', 'outcome_unknown'}
        assert all(row[1] for row in rows)
        assert db.execute("SELECT COUNT(*) FROM run_events WHERE kind='tool_execution_start'").fetchone()[0] == 2


def test_activity_is_agent_scoped_and_queued_timestamp_is_visible(tmp_path):
    record = RunRecord(tmp_path / 'activity.db')
    record.create('queued', agent_id='one')
    record.event('queued', 'permission_denied')
    record.create('hidden', agent_id='two')
    rows = record.recent('one')
    assert len(rows) == 1 and rows[0]['run_id'] == 'queued'
    assert rows[0]['started_at'] and rows[0]['denied_count'] == 1
