"""Regressions found by the 2026-10-11 review."""

import ast
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_blank_desktop_receiver_uses_this_client():
    from agent.scheduler.delivery import normalize_proactive_destination

    desktop = normalize_proactive_destination({"channel_type": "desktop", "receiver": ""})
    assert desktop["receiver"] == "desktop"
    with pytest.raises(ValueError, match="recipient"):
        normalize_proactive_destination({"channel_type": "telegram", "receiver": ""})


def test_desktop_queue_completes_and_other_waiting_retries():
    from agent.scheduler.dispatch import DeliveryOutcome
    from agent.scheduler.integration import _delivery_execution_outcome

    assert _delivery_execution_outcome(DeliveryOutcome("waiting", "等待客户端确认通知")) is True
    assert _delivery_execution_outcome(DeliveryOutcome("waiting", "Weixin session expired")) is False
    assert _delivery_execution_outcome(DeliveryOutcome("failed", "platform down", retryable=True)) is False


def test_corrupt_task_file_is_not_replaced(tmp_path):
    from agent.scheduler.store import TaskStore

    path = tmp_path / "tasks.json"
    path.write_text("{", encoding="utf-8")
    store = TaskStore(str(path))
    with pytest.raises(ValueError, match="unreadable"):
        store.add_task({"id": "one", "name": "One"})
    assert path.read_text(encoding="utf-8") == "{"
    missing = TaskStore(str(tmp_path / "missing.json"))
    assert missing.load_tasks() == {}


def test_desktop_claim_rebuilds_waiting_notifications_after_restart(tmp_path):
    from agent.scheduler.automation_store import AutomationStore
    from agent.scheduler.desktop_notify import claim_desktop_notifications, reset_desktop_notifications
    from agent.scheduler.dispatch import dispatch_notification

    store = AutomationStore(tmp_path / "scheduler" / "tasks.json", "agent-a")
    store.add_task({"id": "scheduled", "name": "Scheduled", "enabled": True,
                    "action": {"type": "send_message", "content": "Saved"}})
    job_id = store.claim_occurrence("scheduled", manual=True)
    route = {"primary": {"channel_type": "desktop", "receiver": "this-mac", "is_group": False}}
    result = dispatch_notification(store, job_id, route, "Saved", channel_provider=lambda _name: None)
    assert result.status == "waiting"
    reset_desktop_notifications()
    claimed = claim_desktop_notifications(store)
    assert claimed[0]["body"] == "Saved"
    assert claim_desktop_notifications(store) == []


def test_mailbox_and_weixin_credentials_stay_protected(tmp_path, monkeypatch):
    mailbox = tmp_path / "briefing/mailbox.json"
    mailbox.parent.mkdir()
    mailbox.write_text('{"password":"secret"}', encoding="utf-8")
    monkeypatch.setattr("common.state_dir.briefing_db", lambda **_: mailbox.with_name("briefing.db"))
    from agent.permission.gateway import DecisionKind, SecurityGateway
    from agent.permission.process_sandbox import _protected_paths
    from agent.tools.utils.credentials import is_credential_path
    from config import get_weixin_credentials_path

    assert is_credential_path(str(mailbox))
    files, _folders = _protected_paths()
    assert any(path.endswith(os.path.join("briefing", "mailbox.json")) for path in files)
    assert os.path.realpath(get_weixin_credentials_path()) in files
    decision = SecurityGateway.check(
        "workspace-write", "bash", {"command": "cat /tmp/briefing/mailbox.json"})
    assert decision.kind is DecisionKind.DENY


def test_denied_network_and_install_cover_python_and_npm_shorthand():
    from agent.permission.gateway import DecisionKind, SecurityGateway
    from agent.permission.security_policy import PRESETS

    rules = dict(PRESETS["workspace-write"])
    rules["network"] = "deny"
    rules["install"] = "deny"
    policy = {"preset": "custom", "rules": rules}
    network = SecurityGateway.check(
        "workspace-write", "bash", {"command": "python -c 'import urllib.request'"}, policy=policy, cwd="/tmp")
    install = SecurityGateway.check(
        "workspace-write", "bash", {"command": "npm i left-pad"}, policy=policy, cwd="/tmp")
    assert network.kind is DecisionKind.DENY and "network" in network.reason
    assert install.kind is DecisionKind.DENY and "install" in install.reason


def test_network_deny_reaches_the_process_sandbox(tmp_path):
    from agent.permission import process_sandbox
    from agent.permission.security_policy import PRESETS

    if process_sandbox.capability()["status"] != "enabled":
        pytest.skip("OS sandbox not available")
    rules = dict(PRESETS["workspace-write"])
    rules["network"] = "deny"
    work = tmp_path / "project"
    work.mkdir()
    plan = process_sandbox.prepare(
        "true", str(work), [str(work)], {"preset": "custom", "rules": rules}, os.environ.copy())
    if sys.platform == "darwin":
        assert "(deny network*)" in plan.argv[2]
    if plan.temp_dir:
        import shutil
        shutil.rmtree(plan.temp_dir, ignore_errors=True)


def test_linux_bubblewrap_unshares_pid_and_network(tmp_path, monkeypatch):
    from agent.permission import process_sandbox
    from agent.permission.security_policy import PRESETS

    monkeypatch.setattr(process_sandbox.sys, "platform", "linux")
    monkeypatch.setattr(process_sandbox, "capability", lambda: {"status": "enabled", "reason": ""})
    monkeypatch.setattr(process_sandbox.shutil, "which", lambda _name: "/usr/bin/bwrap")
    work = tmp_path / "work"
    work.mkdir()
    context = SimpleNamespace(session_id="s", agent_id="a", task_id="task",
                              work_root=work, private_root=work)
    rules = dict(PRESETS["full-access"])
    rules["network"] = "deny"
    plan = process_sandbox.prepare(
        "true", str(work), [str(work)], {"preset": "custom", "rules": rules}, {}, context=context)
    assert "--unshare-pid" in plan.argv
    assert "--unshare-net" in plan.argv
    if plan.temp_dir:
        import shutil
        shutil.rmtree(plan.temp_dir, ignore_errors=True)


def test_overlapping_background_starts_stop_at_the_limit(monkeypatch):
    import subprocess
    import threading
    import time
    from agent.tools.bash import background

    monkeypatch.setattr(background, "_MAX_JOBS", 1)
    monkeypatch.setattr(background, "_jobs", {})
    release = threading.Event()
    entered = []

    def blocking_popen(*_args, **_kwargs):
        entered.append(threading.get_ident())
        assert release.wait(2)
        return subprocess.Popen(
            ["sleep", "30"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    monkeypatch.setattr(background.subprocess, "Popen", blocking_popen)
    errors = []

    def launch():
        try:
            background.start("sleep 30", os.getcwd(), os.environ.copy())
        except RuntimeError as exc:
            errors.append(str(exc))

    first = threading.Thread(target=launch)
    second = threading.Thread(target=launch)
    first.start()
    for _ in range(50):
        if entered:
            break
        time.sleep(0.01)
    second.start()
    for _ in range(100):
        if len(entered) > 1 or errors:
            break
        time.sleep(0.01)
    try:
        assert len(entered) == 1
        assert len(errors) == 1
        assert "background job limit" in errors[0]
    finally:
        release.set()
        first.join(3)
        second.join(3)
        background.reset()


def test_running_background_jobs_count_toward_the_limit(monkeypatch):
    from agent.tools.bash import background

    class _Running:
        running = True
        started_at = 0

    monkeypatch.setattr(background, "_jobs", {"bash_existing": _Running()})
    monkeypatch.setattr(background, "_MAX_JOBS", 1)
    with pytest.raises(RuntimeError, match="background job limit"):
        background.start("true", os.getcwd(), os.environ.copy())


def test_stream_error_generators_keep_the_exception_text():
    offenders = []
    for relative in (
        "models/claudeapi/claude_api_bot.py",
        "models/deepseek/deepseek_bot.py",
        "models/doubao/doubao_bot.py",
        "models/linkai/link_ai_bot.py",
        "models/mimo/mimo_bot.py",
        "models/minimax/minimax_bot.py",
        "models/moonshot/moonshot_bot.py",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "error_generator":
                names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
                if "e" in names:
                    offenders.append(relative)
    assert offenders == []


def test_plugin_email_credentials_and_sqlite_sidecars_are_protected(tmp_path, monkeypatch):
    from common import state_dir
    from agent.tools.utils.credentials import is_credential_path
    monkeypatch.setattr(state_dir, 'briefing_db', lambda **_: tmp_path / 'briefing/briefing.db')
    for suffix in ('', '-wal', '-shm', '-journal'):
        assert is_credential_path(str(tmp_path / ('email/email.db' + suffix)))


def test_shell_policy_rejects_direct_email_database_and_backup_reads():
    from agent.permission.gateway import DecisionKind, SecurityGateway
    for path in ('/tmp/email/email.db', '/tmp/email/email.db-wal',
                 '/tmp/plugin-packages/management/backups/op/email.db'):
        decision = SecurityGateway.check('full-access', 'bash', {'command': 'cat ' + path})
        assert decision.kind is DecisionKind.DENY
