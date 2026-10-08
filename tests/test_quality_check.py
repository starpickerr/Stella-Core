import sys

import pytest

from scripts.quality_check import affected_checks, isolated_env, markdown_report, run_check


def test_python_change_selects_related_tests_without_full_suite():
    checks = affected_checks(["agent/permission/gateway.py"])

    assert "tests/test_security_gateway.py" in checks["pytest"]
    assert "tests/test_security_center.py" in checks["pytest"]
    assert checks["ruff"] == ["agent/permission/gateway.py"]
    assert not checks["typecheck"]


def test_renderer_change_selects_ui_and_typecheck():
    checks = affected_checks(["desktop/src/renderer/src/pages/TasksPage.tsx"])

    assert checks["typecheck"]
    assert checks["ui"]
    assert not checks["pytest"]


def test_todo_change_selects_its_behavior_tests():
    checks = affected_checks(["agent/todos/service.py"])

    assert "tests/test_todos.py" in checks["pytest"]


def test_runtime_permission_change_selects_denial_and_recovery_tests():
    checks = affected_checks(["agent/runtime/tool_invocation.py"])

    assert "tests/test_security_gateway.py" in checks["pytest"]
    assert "tests/test_security_approval_resume.py" in checks["pytest"]
    assert "tests/test_harness_runtime.py" in checks["pytest"]


def test_scheduler_and_browser_changes_select_domain_regressions():
    scheduler = affected_checks(["agent/scheduler/store.py"])
    browser = affected_checks(["agent/tools/browser/browser_tool.py"])

    assert "tests/test_scheduler_delivery.py" in scheduler["pytest"]
    assert "tests/test_browser_request_scope.py" in browser["pytest"]
    assert "tests/test_security_ssrf_browser_navigate.py" in browser["pytest"]


def test_provider_and_channel_changes_select_matching_tests():
    model = affected_checks(["models/moonshot/moonshot_bot.py"])
    channel = affected_checks(["channel/feishu/feishu_channel.py"])

    assert "tests/test_moonshot_reasoning_effort.py" in model["pytest"]
    assert "tests/test_feishu_progress_card.py" in channel["pytest"]


def test_skill_reference_change_validates_skills_without_linting_vendored_examples():
    checks = affected_checks([".agents/skills/webapp-testing/examples/console_logging.py"])

    assert checks["ruff"] == []
    assert "tests/test_quality_check.py" in checks["pytest"]


def test_project_skills_have_codex_metadata():
    from scripts.quality_check import ROOT

    for skill in (ROOT / ".agents" / "skills").glob("*/SKILL.md"):
        text = skill.read_text(encoding="utf-8")
        assert text.startswith("---\n"), skill
        assert f"name: {skill.parent.name}" in text.split("---", 2)[1], skill
        assert "description:" in text.split("---", 2)[1], skill


def test_isolated_env_never_points_at_real_state(tmp_path):
    env = isolated_env(tmp_path)

    assert env["HOME"] == str(tmp_path)
    assert env["STELLA_DATA_DIR"] == str(tmp_path / "data")
    assert env["TMPDIR"] == str(tmp_path / "tmp")


def test_isolated_env_drops_provider_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sentinel")
    monkeypatch.setenv("GITHUB_TOKEN", "sentinel")

    env = isolated_env(tmp_path)

    assert "OPENAI_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env


def test_failed_quality_check_prints_actionable_failure(capsys, tmp_path):
    script = tmp_path / "failing_check.py"
    script.write_text("print('specific failure')\nprint('1 failed')\nraise SystemExit(1)\n")
    command = [sys.executable, str(script)]

    result = run_check("pytest", command, {}, 10)

    assert result[1] == "FAIL"
    assert "specific failure" in capsys.readouterr().out


def test_full_audit_report_does_not_overwrite_manual_review(tmp_path):
    report = tmp_path / "Full-Audit-2026-10-08.md"
    report.write_text("reviewed findings\n")

    with pytest.raises(FileExistsError):
        markdown_report([], report)

    assert report.read_text() == "reviewed findings\n"
