"""H0 ExecutionService: authoritative status, cancel, reconcile, workspace lease, artifacts."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from core.execution.artifacts import seal_artifact
from core.execution.service import ExecutionService, TerminalConflict
from core.execution.workspace_lease import allocate_workspace_lease


@pytest.fixture
def exec_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("STELLA_DATA_DIR", str(root))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return root


def _svc(exec_root: Path) -> ExecutionService:
    return ExecutionService(db_path=exec_root / "executions.db", work_root=exec_root / "work")


def test_create_get_list_and_terminal_immune_to_late_progress(exec_root):
    svc = _svc(exec_root)
    created = svc.create(
        owner_plugin_id="stella.agent-hub",
        task_kind="research.report",
        goal="summarize notes",
        budget={"maxWallTime": 30, "maxAttempts": 1, "maxConcurrent": 1},
    )
    eid = created["executionId"]
    assert created["status"] == "queued"
    assert svc.get(eid)["attemptId"]
    svc.transition(eid, "running")
    svc.append_event(eid, "progress", {"message": "working"})
    svc.transition(eid, "succeeded", summary="done")
    with pytest.raises(TerminalConflict):
        svc.transition(eid, "running")
    with pytest.raises(TerminalConflict):
        svc.append_event(eid, "progress", {"message": "late"})
    row = svc.get(eid)
    assert row["status"] == "succeeded"
    assert row["summary"] == "done"
    listed = svc.list(owner_plugin_id="stella.agent-hub")
    assert [r["executionId"] for r in listed] == [eid]


def test_cancel_race_records_actual_completion(exec_root):
    svc = _svc(exec_root)
    created = svc.create(
        owner_plugin_id="stella.agent-hub",
        task_kind="local.echo",
        goal="finish before cancel",
        budget={"maxWallTime": 10, "maxAttempts": 1, "maxConcurrent": 1},
    )
    eid = created["executionId"]
    svc.transition(eid, "running")
    ack = svc.request_cancel(eid)
    assert ack["status"] == "cancel_requested"
    # Provider already finished — record real outcome, not forged cancelled.
    svc.transition(eid, "succeeded", summary="completed despite cancel request")
    row = svc.get(eid)
    assert row["status"] == "succeeded"
    assert row["cancelRequested"] is True


def test_restart_marks_active_unknown_and_reconcile_without_blind_start(exec_root):
    db = exec_root / "executions.db"
    work = exec_root / "work"
    svc = ExecutionService(db_path=db, work_root=work)
    created = svc.create(
        owner_plugin_id="stella.agent-hub",
        task_kind="local.sleep",
        goal="interrupted",
        budget={"maxWallTime": 60, "maxAttempts": 2, "maxConcurrent": 1},
    )
    eid = created["executionId"]
    svc.transition(eid, "running")
    # Simulate process restart: new service instance recovers active rows.
    recovered = ExecutionService(db_path=db, work_root=work)
    row = recovered.get(eid)
    assert row["status"] == "outcome_unknown"
    result = recovered.reconcile(eid, evidence={"externalStatus": "still_running"})
    assert result["status"] == "running"
    # Blind start is refused while outcome is unknown without evidence.
    svc2 = ExecutionService(db_path=db, work_root=work)
    row2 = svc2.get(eid)
    assert row2["status"] in {"running", "outcome_unknown"}
    with pytest.raises(ValueError, match="blind start|reconcile|unknown"):
        svc2.blind_start(eid)


def test_workspace_lease_rejects_path_escape(exec_root, tmp_path):
    lease = allocate_workspace_lease(
        work_root=exec_root / "work",
        execution_id="ex-1",
        attempt_id="at-1",
        source_project=None,
    )
    assert lease["path"].startswith(str(exec_root / "work"))
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(PermissionError):
        lease["assert_inside"](outside)


def test_seal_artifact_immutable_digest(exec_root):
    work = exec_root / "work" / "ex" / "out"
    work.mkdir(parents=True)
    src = work / "report.md"
    src.write_text("# ok\n", encoding="utf-8")
    ref = seal_artifact(store_root=exec_root / "artifacts", source_path=src, execution_id="ex-1")
    assert ref["artifactRef"].startswith("artifact:")
    assert len(ref["sha256"]) == 64
    sealed = Path(ref["path"])
    assert sealed.is_file()
    # Mutating original must not change sealed bytes.
    src.write_text("# changed\n", encoding="utf-8")
    assert sealed.read_text(encoding="utf-8") == "# ok\n"


def test_process_supervisor_kills_tree_on_revoke(exec_root):
    from core.execution.process_supervisor import ProcessSupervisor

    sup = ProcessSupervisor()
    # Sleep long enough that revoke must kill it.
    proc = subprocess.Popen(
        ["python3", "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        lease_id = "lease-1"
        sup.register(lease_id, proc)
        assert proc.poll() is None
        sup.revoke(lease_id)
        deadline = time.time() + 5
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)


def test_fake_provider_end_to_end_with_service(exec_root):
    from core.execution.fake_provider import FakeLocalProvider

    svc = _svc(exec_root)
    provider = FakeLocalProvider(work_root=exec_root / "work")
    created = svc.create(
        owner_plugin_id="stella.agent-hub",
        task_kind="local.echo",
        goal="write hello",
        budget={"maxWallTime": 15, "maxAttempts": 1, "maxConcurrent": 1},
        acceptance={"contains": "hello"},
    )
    eid = created["executionId"]
    lease = allocate_workspace_lease(
        work_root=exec_root / "work",
        execution_id=eid,
        attempt_id=created["attemptId"],
        source_project=None,
    )
    svc.attach_workspace(eid, lease["workspaceLeaseRef"], lease["path"])
    svc.transition(eid, "running")
    start = provider.start(
        {
            "executionId": eid,
            "attemptId": created["attemptId"],
            "goal": "write hello",
            "workspacePath": lease["path"],
        }
    )
    assert start["externalRunRef"]
    events = list(provider.observe(start["externalRunRef"]))
    assert any(e["type"] == "progress" for e in events)
    final = events[-1]
    assert final["type"] == "terminal"
    out = Path(lease["path"]) / "result.txt"
    assert out.read_text(encoding="utf-8").strip() == "hello"
    art = seal_artifact(store_root=exec_root / "artifacts", source_path=out, execution_id=eid)
    svc.attach_artifacts(eid, [art["artifactRef"]])
    svc.transition(eid, "succeeded", summary="echo ok")
    watched = list(svc.watch(eid))
    assert watched[-1]["status"] == "succeeded"
    assert Path(svc.db_path).is_file()
