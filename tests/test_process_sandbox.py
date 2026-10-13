import os
import shutil
import subprocess
import sys

import pytest

from agent.permission import process_sandbox
from agent.permission.security_policy import default_policy, PRESETS


def _run(plan, cwd, env):
    try:
        return subprocess.run(plan.argv, shell=plan.shell, cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=10)
    finally:
        if plan.temp_dir:
            shutil.rmtree(plan.temp_dir, ignore_errors=True)


@pytest.mark.skipif(sys.platform not in ("darwin", "linux"), reason="sandbox backend unavailable")
def test_project_command_cannot_write_outside_actual_sandbox(tmp_path):
    if process_sandbox.capability()["status"] != "enabled":
        pytest.skip("OS sandbox not available")
    work = tmp_path / "project"
    work.mkdir()
    inside, outside = work / "inside.txt", tmp_path / "outside.txt"
    env = os.environ.copy()
    plan = process_sandbox.prepare(f"touch {inside}", str(work), [str(work)], default_policy(), env)
    assert _run(plan, str(work), env).returncode == 0
    assert inside.exists()

    env = os.environ.copy()
    plan = process_sandbox.prepare(f"touch {outside}", str(work), [str(work)], default_policy(), env)
    assert _run(plan, str(work), env).returncode != 0
    assert not outside.exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt-specific Unicode paths")
def test_seatbelt_can_write_unicode_project_only(tmp_path):
    if process_sandbox.capability()["status"] != "enabled":
        pytest.skip("Seatbelt unavailable")
    work = tmp_path / "课程资料"
    work.mkdir()
    inside, outside = work / "new.txt", tmp_path / "outside.txt"
    env = os.environ.copy()
    plan = process_sandbox.prepare(f"touch '{inside}'", str(work), [str(work)], default_policy(), env)
    assert _run(plan, str(work), env).returncode == 0
    assert inside.exists()
    env = os.environ.copy()
    plan = process_sandbox.prepare(f"touch '{outside}'", str(work), [str(work)], default_policy(), env)
    assert _run(plan, str(work), env).returncode != 0
    assert not outside.exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt-specific exact path grant")
def test_seatbelt_approval_opens_only_named_outside_file(tmp_path):
    if process_sandbox.capability()["status"] != "enabled":
        pytest.skip("Seatbelt unavailable")
    work = tmp_path / "project"
    work.mkdir()
    allowed, sibling = tmp_path / "approved.txt", tmp_path / "sibling.txt"
    env = os.environ.copy()
    plan = process_sandbox.prepare(f"touch {allowed}", str(work), [str(work)], default_policy(), env,
                                   approved_target=str(allowed))
    assert _run(plan, str(work), env).returncode == 0
    assert allowed.exists()
    env = os.environ.copy()
    plan = process_sandbox.prepare(f"touch {sibling}", str(work), [str(work)], default_policy(), env,
                                   approved_target=str(allowed))
    assert _run(plan, str(work), env).returncode != 0
    assert not sibling.exists()


def test_unavailable_sandbox_fails_closed_for_project_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(process_sandbox, "capability", lambda: {"status": "unavailable", "reason": "probe failed"})
    with pytest.raises(process_sandbox.SandboxUnavailable, match="probe failed"):
        process_sandbox.prepare("true", str(tmp_path), [str(tmp_path)], default_policy(), {})

    with pytest.raises(process_sandbox.SandboxUnavailable, match="probe failed"):
        process_sandbox.prepare("true", str(tmp_path), [str(tmp_path)],
                                {"preset": "full-access", "rules": PRESETS["full-access"]}, {})


@pytest.mark.skipif(sys.platform not in ("darwin", "linux"), reason="sandbox backend unavailable")
def test_full_access_shell_child_cannot_read_other_private_work(tmp_path, monkeypatch):
    if process_sandbox.capability()["status"] != "enabled":
        pytest.skip("OS sandbox not available")
    from agent.workspace import project_store
    from agent.workspace.context import resolve_context
    from agent.workspace.shares import create_share, revoke_share

    work = tmp_path / "work"
    monkeypatch.setattr("agent.workspace.context.personal_work_dir", lambda **kwargs: work)
    monkeypatch.setattr("agent.workspace.shares._manifest_file", lambda: tmp_path / "shares.json")
    monkeypatch.setattr(project_store, "_store_file", lambda: str(tmp_path / "projects.json"))
    owner = resolve_context("owner", "alpha", ensure=True)
    recipient = resolve_context("recipient", "alpha", ensure=True)
    secret = owner.root / "secret.txt"
    own = recipient.root / "own.txt"
    secret.write_text("SECRET")
    own.write_text("OWN")
    shared = create_share("owner", "alpha", "secret.txt", "recipient", "read")
    policy = {"preset": "full-access", "rules": PRESETS["full-access"]}

    def run_cat(path):
        env = os.environ.copy()
        plan = process_sandbox.prepare(f"/bin/cat '{path}'", str(recipient.root),
                                       [str(recipient.root)], policy, env, context=recipient)
        return _run(plan, str(recipient.root), env)

    assert run_cat(own).stdout.strip() == "OWN"
    assert run_cat(secret).returncode != 0
    assert run_cat(shared["path"]).stdout.strip() == "SECRET"
    sibling = owner.root / "sibling.txt"
    sibling.write_text("HIDDEN")
    assert run_cat(sibling).returncode != 0
    env = os.environ.copy()
    plan = process_sandbox.prepare(f"/bin/sh -c 'echo CHANGED > {shared['path']}'", str(recipient.root),
                                   [str(recipient.root)], policy, env, context=recipient)
    assert _run(plan, str(recipient.root), env).returncode != 0
    assert open(shared["path"]).read() == "SECRET"
    revoke_share(shared["id"], "owner", "alpha")
    assert run_cat(shared["path"]).returncode != 0


@pytest.mark.skipif(sys.platform not in ("darwin", "linux"), reason="sandbox backend unavailable")
def test_revoking_share_terminates_running_shell_with_old_grant(tmp_path, monkeypatch):
    if process_sandbox.capability()["status"] != "enabled":
        pytest.skip("OS sandbox not available")
    from agent.workspace import project_store
    from agent.workspace.context import resolve_context
    from agent.workspace.shares import create_share, revoke_share

    work = tmp_path / "work"
    monkeypatch.setattr("agent.workspace.context.personal_work_dir", lambda **kwargs: work)
    monkeypatch.setattr("agent.workspace.shares._manifest_file", lambda: tmp_path / "shares.json")
    monkeypatch.setattr(project_store, "_store_file", lambda: str(tmp_path / "projects.json"))
    owner = resolve_context("owner", "alpha", ensure=True)
    recipient = resolve_context("recipient", "alpha", ensure=True)
    (owner.root / "file.txt").write_text("data")
    shared = create_share("owner", "alpha", "file.txt", "recipient", "read")
    env = os.environ.copy()
    policy = {"preset": "full-access", "rules": PRESETS["full-access"]}
    plan = process_sandbox.prepare("sleep 30", str(recipient.root), [str(recipient.root)],
                                   policy, env, context=recipient)
    process = subprocess.Popen(plan.argv, cwd=str(recipient.root), env=env,
                               start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        process_sandbox.register_share_process(process, plan)
        assert process.poll() is None
        revoke_share(shared["id"], "owner", "alpha")
        process.wait(timeout=5)
        assert process.returncode != 0
    finally:
        process_sandbox.unregister_share_process(process)
        if process.poll() is None:
            os.killpg(process.pid, __import__("signal").SIGKILL)
            process.wait()
        if plan.temp_dir:
            shutil.rmtree(plan.temp_dir, ignore_errors=True)
