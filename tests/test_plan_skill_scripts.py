"""The project-installed planning skill must run without an absent sibling skill."""

import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/executing-plans/scripts"


def _run(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_inline_plan_skill_uses_its_own_scripts(tmp_path, monkeypatch):
    _run("git", "init", "-q", str(tmp_path), cwd=tmp_path)
    _run("git", "config", "user.name", "Skill Test", cwd=tmp_path)
    _run("git", "config", "user.email", "skill-test@example.invalid", cwd=tmp_path)
    plan = tmp_path / "plan.md"
    plan.write_text("# Example\n\n### Task 1: Verify\n\n- [ ] Run a check\n", encoding="utf-8")
    _run("git", "add", "plan.md", cwd=tmp_path)
    _run("git", "commit", "-qm", "add test plan", cwd=tmp_path)

    started = _run(str(SCRIPTS / "task-start"), str(plan), "1", cwd=tmp_path)
    base = started.split("base: ", 1)[1]
    assert "Task 1: Verify" in (tmp_path / ".superpowers/sdd/plan/task-1-brief.md").read_text()

    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("STELLA_DATA_DIR", "real-user-state")
    browser_cache = tmp_path / "outer-home/.cache/ms-playwright"
    browser_cache.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path / "outer-home"))
    _run(str(SCRIPTS / "task-done"), str(plan), "1", base, "--",
         sys.executable, "-c",
         "import os; print('SAFE=' + str('OPENAI_API_KEY' not in os.environ and os.environ['STELLA_DATA_DIR'] != 'real-user-state')); print('BROWSER=' + os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')); print('1 passed')",
         cwd=tmp_path)
    ledger = (tmp_path / ".superpowers/sdd/plan/progress.md").read_text()
    assert "Task 1: complete" in ledger
    assert "1 passed" in ledger
    log = (tmp_path / ".superpowers/sdd/plan/task-1-tests.log").read_text()
    assert "SAFE=True" in log
    assert f"BROWSER={browser_cache}" in log
    assert "test-secret" not in log

    (tmp_path / "result.txt").write_text("done\n", encoding="utf-8")
    _run("git", "add", "result.txt", cwd=tmp_path)
    _run("git", "commit", "-qm", "complete task", cwd=tmp_path)
    head = _run("git", "rev-parse", "HEAD", cwd=tmp_path)
    package = _run(str(SCRIPTS / "review-package"), str(plan), base, head, cwd=tmp_path)
    assert "1 commit(s)" in package
