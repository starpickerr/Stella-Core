from scripts.quality_check import affected_checks, isolated_env


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
    for adapter in ("agent/todos/apple_sync.py", "agent/todos/scheduler_link.py"):
        checks = affected_checks([adapter])

        assert "tests/test_todos.py" in checks["pytest"]
        assert "tests/test_todos_plugin_gateway.py" in checks["pytest"]
        assert "tests/test_apple_reminder_sync.py" in checks["pytest"]
    facade = affected_checks(["core/services/todos_facade.py"])
    assert "tests/test_todos_plugin_gateway.py" in facade["pytest"]
    assert "tests/test_todos.py" in facade["pytest"]


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
    assert checks["policy"]


def test_project_policy_change_selects_policy_preflight():
    for path in ("AGENTS.md", ".agents/AGENTS.md", ".agents/rules/git.md",
                 ".agents/workflows/development.md", ".codex/config.toml",
                 ".agents/skills/sources.json", ".cursor/rules/stella-development.mdc",
                 "scripts/check_dev_policy.py"):
        assert affected_checks([path])["policy"], path


def test_changed_files_uses_explicit_ci_base(monkeypatch):
    from scripts import quality_check

    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return type("Result", (), {"stdout": "AGENTS.md\n"})()

    monkeypatch.setenv("STELLA_CHECK_BASE", "abc123")
    monkeypatch.setattr(quality_check.subprocess, "run", fake_run)
    assert "AGENTS.md" in quality_check.changed_files()
    assert commands[0] == ["git", "diff", "--name-only", "abc123...HEAD"]


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


def test_nested_isolation_preserves_installed_browser_cache(tmp_path, monkeypatch):
    browser_cache = tmp_path / "ms-playwright"
    browser_cache.mkdir()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(browser_cache))
    monkeypatch.setenv("HOME", str(tmp_path / "outer-home"))

    env = isolated_env(tmp_path / "inner-home")

    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(browser_cache)


def test_removed_backend_and_dependency_changes_expand_checks():
    deleted = affected_checks(["agent/briefing/removed.py"])
    assert "tests/test_briefing_plugin_gateway.py" in deleted["pytest"]
    dependencies = affected_checks(["requirements.txt"])
    assert "tests/test_todos.py" in dependencies["pytest"]
    assert "tests/test_briefing_plugin_gateway.py" in dependencies["pytest"]


def test_frontend_checks_include_lint_build_and_new_node_tests():
    checks = affected_checks(["desktop/package.json"])
    assert checks["eslint"] and checks["typecheck"] and checks["build"]
    assert affected_checks(["tests/todoViews.test.mjs"])["node"]
    checks = affected_checks(["agent/briefing/actions.py"])
    assert "tests/test_todos.py" in checks["pytest"]
    assert "tests/test_calendar.py" in checks["pytest"]


def test_audit_report_does_not_overwrite_history(tmp_path):
    from scripts.quality_check import markdown_report
    report=tmp_path / "audit.md"
    report.write_text("existing review")
    markdown_report([], report)
    assert report.read_text() == "existing review"
    assert len(list(tmp_path.glob("audit*.md"))) == 2


def test_isolation_redirects_windows_profile_and_temp_state(tmp_path):
    env = isolated_env(tmp_path)
    assert env['USERPROFILE'] == str(tmp_path)
    assert env['APPDATA'] == str(tmp_path / 'config')
    assert env['LOCALAPPDATA'] == str(tmp_path / 'cache')
    assert env['TEMP'] == str(tmp_path / 'tmp')
    assert env['TMP'] == str(tmp_path / 'tmp')


def test_quality_tools_select_explicit_interpreter(tmp_path, monkeypatch):
    from scripts.check_runtime import python_path
    interpreter = tmp_path / 'ci-python'
    interpreter.touch()
    interpreter.chmod(0o755)
    monkeypatch.setenv('STELLA_PYTHON', str(interpreter))
    assert python_path(tmp_path) == interpreter


def test_isolation_preserves_resolved_python_for_nested_checks(tmp_path):
    from scripts.quality_check import PYTHON

    assert isolated_env(tmp_path)['STELLA_PYTHON'] == str(PYTHON)


def test_python_selection_changes_run_environment_regressions():
    checks = affected_checks(['scripts/check_runtime.py'])
    assert 'tests/test_python_environment.py' in checks['pytest']
    assert 'tests/test_quality_check.py' in checks['pytest']
    assert checks['node']


def test_runtime_node_regressions_are_in_incremental_and_full_gates(monkeypatch):
    import sys
    from scripts import quality_check

    commands = []

    def record(name, command, _env, _timeout):
        commands.append((name, command))
        return name, 'PASS', command, ''

    monkeypatch.setattr(quality_check, 'run_check', record)
    monkeypatch.setattr(quality_check, 'markdown_report', lambda *_: None)
    for mode in ('incremental', 'full'):
        commands.clear()
        args = ['quality_check.py', mode]
        if mode == 'incremental':
            args += ['--files', 'scripts/check_runtime.py']
        monkeypatch.setattr(sys, 'argv', args)
        assert quality_check.main() == 0
        node = next(command for name, command in commands if name == 'node')
        assert 'tests/pythonRuntime.test.mjs' in node
