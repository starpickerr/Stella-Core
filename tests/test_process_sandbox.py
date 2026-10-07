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
