"""Run Stella quality checks with temporary user state."""

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_runtime import npm_path, python_path


ROOT = Path(__file__).resolve().parent.parent
PYTHON = python_path(ROOT)
SKILL_SERVER = ROOT / ".agents/skills/webapp-testing/scripts/with_server.py"
DOMAIN_TESTS = {
    # Core keeps only the Tasks adapters (Apple Reminders sync, scheduler links); the
    # domain's own tests live in Stella-Plugins/plugins/tasks/tests.
    "agent/todos/": ("tests/test_todos.py", "tests/test_todos_plugin_gateway.py",
                     "tests/test_apple_reminder_sync.py", "tests/test_apple_reminder_todos.py"),
    "core/services/todos_": ("tests/test_todos_plugin_gateway.py", "tests/test_todos.py"),
    "agent/calendar/": ("tests/test_calendar.py",),
    "agent/permission/": ("tests/test_security_gateway.py", "tests/test_security_center.py",
                          "tests/test_security_approval_resume.py", "tests/test_process_sandbox.py"),
    "agent/runtime/": ("tests/test_harness_runtime.py", "tests/test_security_gateway.py",
                       "tests/test_security_approval_resume.py", "tests/test_parallel_tool_calls.py"),
    "agent/memory/": ("tests/test_memory_global_config.py", "tests/test_session_resurrect.py"),
    "agent/skills/": ("tests/test_skill_authoring.py", "tests/test_skill_tool_binding.py"),
    "core/services/bills_": ("tests/test_bills_facade_port.py", "tests/test_bills_web.py"),
    "agent/workspace/": ("tests/test_project_conversation_scope.py",),
}
DOMAIN_GLOBS = {
    "agent/scheduler/": ("test_scheduler_*.py",),
    "agent/tools/browser/": ("test_browser_*.py", "test_security_ssrf_browser_*.py"),
    "agent/tools/bash/": ("test_bash_*.py",),
    "agent/tools/edit/": ("test_edit_*.py", "test_security_edit_*.py"),
    "agent/tools/read/": ("test_read_*.py", "test_security_read_*.py"),
    "agent/tools/subagent/": ("test_subagent*.py",),
}


def affected_checks(files):
    changed = {Path(path).as_posix() for path in files}
    python_files = sorted(path for path in changed if path.endswith(".py")
                          and not path.startswith(".agents/skills/") and (ROOT / path).is_file())
    tests = set()
    for path in changed:
        for prefix, related in DOMAIN_TESTS.items():
            if path.startswith(prefix):
                tests.update(related)
        for prefix, patterns in DOMAIN_GLOBS.items():
            if path.startswith(prefix):
                for pattern in patterns:
                    tests.update(p.relative_to(ROOT).as_posix()
                                 for p in (ROOT / "tests").glob(pattern))
        parts = Path(path).parts
        if len(parts) > 1 and parts[0] in {"models", "channel"}:
            tests.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob(
                f"test_{parts[1]}*.py"))
        if path.startswith("tests/test_"):
            tests.add(path)
        else:
            candidate = f"tests/test_{Path(path).stem}.py"
            if (ROOT / candidate).is_file():
                tests.add(candidate)
        if path.startswith("agent/permission/"):
            tests.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("test_security_*.py"))
            tests.add("tests/test_process_sandbox.py")
        if path.startswith("agent/briefing/"):
            tests.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("test_briefing_*.py"))
        if path.startswith("agent/runtime/") or path.startswith("agent/tools/"):
            tests.update(["tests/test_harness_runtime.py", "tests/test_tool_path_and_eval.py"])
        if path.startswith("application/") or path in {"app.py", "config.py"}:
            tests.update(["tests/test_web_sse_replay.py", "tests/test_security_center.py"])
        if path.startswith("agent/memory/") and ("store" in path or "storage" in path):
            tests.add("tests/test_shared_db_recovery.py")
    if (changed & {"AGENTS.md", "scripts/quality_check.py"}
            or any(path.startswith(".agents/skills/") for path in changed)):
        tests.add("tests/test_quality_check.py")
    if (changed & {"AGENTS.md", ".agents/AGENTS.md", ".codex/config.toml", "scripts/check_dev_policy.py"}
            or any(path.startswith((".agents/rules/", ".agents/workflows/", ".cursor/rules/")) for path in changed)):
        tests.add("tests/test_dev_policy.py")
    if any(path.startswith(("agent/briefing/", "agent/tools/briefing/")) for path in changed):
        tests.update(("tests/test_todos.py", "tests/test_calendar.py"))
        tests.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("test_briefing_*.py"))
    shared = any(path in {"requirements.txt", "requirements-dev.txt", "pyproject.toml", "tests/conftest.py", "config.py", "app.py"}
                 or path.startswith(("application/", "common/", "agent/protocol/")) for path in changed)
    if shared:
        tests.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("test_*.py"))
    if any(path.startswith("agent/tools/web_fetch/") for path in changed):
        tests.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("test_security_ssrf*.py"))
        tests.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("test_*cancel*.py"))
    desktop_config = any(path.startswith("desktop/") and (path.endswith(".json") or path.endswith(".mjs") or "preload/" in path) for path in changed)
    renderer = any(path.startswith("desktop/src/renderer/") for path in changed)
    renderer = renderer or desktop_config or any(path in changed for path in
        ("tests/ui_smoke.py", "tests/ui_briefing.py", "tests/ui_apple_calendar.py"))
    desktop = renderer or any(path.startswith("desktop/src/main/") for path in changed)
    return {
        "ruff": python_files,
        "pytest": sorted(path for path in tests if (ROOT / path).is_file()),
        "typecheck": desktop,
        "node": renderer or bool(changed & {
            "tests/todoFocus.test.mjs", "tests/todoViews.test.mjs",
            "tests/briefingSort.test.mjs", "tests/renderSafety.test.mjs",
            "tests/knowledgeLinks.test.mjs", "tests/taskChannel.test.mjs",
        }),
        "ui": renderer,
        "eslint": desktop,
        "build": desktop,
        "policy": any(path in {"AGENTS.md", ".agents/AGENTS.md", ".codex/config.toml", "scripts/check_dev_policy.py"}
                      or path.startswith((".agents/rules/", ".agents/skills/", ".agents/workflows/", ".cursor/rules/")) for path in changed),
    }


def isolated_env(root):
    # Only process mechanics cross into test subprocesses. Provider credentials,
    # cloud profiles and proxies must not reach tests by accident.
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT", "WINDIR"}}
    browser_cache = (Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'ms-playwright'
                     if os.name == 'nt' else Path.home() / ('Library/Caches/ms-playwright' if sys.platform == 'darwin' else '.cache/ms-playwright'))
    inherited_browser_cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if inherited_browser_cache:
        candidate = Path(inherited_browser_cache)
        if candidate.name == "ms-playwright" and candidate.is_dir():
            browser_cache = candidate
    env.update({
        "HOME": str(root),
        "USERPROFILE": str(root),
        "APPDATA": str(root / "config"),
        "LOCALAPPDATA": str(root / "cache"),
        "TEMP": str(root / "tmp"),
        "TMP": str(root / "tmp"),
        "STELLA_DATA_DIR": str(root / "data"),
        "TMPDIR": str(root / "tmp"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    if browser_cache.is_dir():
        # Browser binaries are immutable test tooling, not application state;
        # keep them outside the temporary HOME so isolated UI tests can launch.
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache)
    for key in ("data", "tmp", "cache", "config"):
        (root / key).mkdir(parents=True, exist_ok=True)
    return env


def changed_files():
    base = os.environ.get("STELLA_CHECK_BASE", "develop")
    commands = [
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    changed = set()
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
        changed.update(result.stdout.splitlines())
    return sorted(changed)


def run_check(name, command, env, timeout):
    if command[0] == 'npm':
        command = [npm_path(), *command[1:]]
    print(f"RUN  {name}: {' '.join(command)}", flush=True)
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
        output = (result.stdout + result.stderr).strip()
        status = "PASS" if result.returncode == 0 else "FAIL"
    except (OSError, subprocess.TimeoutExpired) as error:
        output = str(error)
        status = "FAIL"
    print(f"{status} {name}: {output.splitlines()[-1] if output else 'no output'}", flush=True)
    if status == "FAIL":
        print(output, flush=True)
    return name, status, " ".join(command), output


def markdown_report(results, output_path):
    categories = [
        "代码质量与潜在 Bug", "项目架构及模块依赖", "前后端功能完整性", "Agent 工具调用和执行可靠性",
        "数据库一致性与并发安全", "权限控制和安全漏洞", "UI 交互与用户体验", "性能与资源占用",
        "异常恢复与系统稳定性", "核心业务流程及回归测试",
    ]
    if output_path.exists():
        stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H%M%S-%f")
        output_path = output_path.with_name(f"{output_path.stem}-{stamp}{output_path.suffix}")
    lines = [f"# Stella Full Audit — {date.today().isoformat()}", "", "## 范围与环境", "",
             f"- 基线：`{subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, text=True).strip()}`",
             "- 自动化检查在临时 HOME 和 STELLA_DATA_DIR 中执行；未连接真实业务数据。", "",
             "## 自动化证据", "", "| 检查 | 状态 | 命令 |", "| --- | --- | --- |"]
    for name, status, command, _ in results:
        lines.append(f"| {name} | {status} | `{command}` |")
    lines.extend(["", "## 检测范围", "", "| 领域 | 状态 |", "| --- | --- |"])
    lines.extend(f"| {category} | 待人工审查 |" for category in categories)
    lines.extend(["", "## 已确认问题", ""])
    failures = [item for item in results if item[1] == "FAIL"]
    if failures:
        lines.extend(
            f"- **中**：自动化检查 `{name}` 失败；复现命令见自动化证据，需按失败输出修复或豁免并补充回归证据。"
            for name, _, _, _ in failures
        )
    else:
        lines.append("无自动确认项。")
    lines.extend(["",
                  "## 潜在风险", "", "待人工审查。", "", "## 未执行与限制", "",
                  "人工审查及外部服务端到端测试尚未执行。", ""])
    if failures:
        lines.extend(["## 失败证据", ""])
        for name, _, command, output in failures:
            lines.extend([f"### {name}", "", f"命令：`{command}`", "", "```text", *output.splitlines()[-35:], "```", ""])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"REPORT {output_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["incremental", "full"])
    parser.add_argument("--files", nargs="*", help="Explicit changed paths for incremental checks")
    parser.add_argument("--report", type=Path, default=ROOT / ".agents/audits/code-review" / f"Full-Audit-{date.today().isoformat()}.md")
    args = parser.parse_args()
    if not PYTHON.is_file():
        parser.error(
            "Stella Python not found; activate conda env Stella "
            "(or set STELLA_PYTHON). CI may use .venv/bin/python."
        )
    selected = affected_checks(args.files if args.files is not None else changed_files()) if args.mode == "incremental" else None
    commands = []
    if args.mode == "full":
        commands = [
            ("ruff", [str(PYTHON), "-m", "ruff", "check", "--select", "E4,E7,E9,F", "agent", "application", "bridge", "channel", "cli", "common", "models", "scripts", "tests", "evals", "translate", "voice", "app.py", "config.py"], 120),
            ("pytest", [str(PYTHON), "-m", "pytest", "tests", "-q"], 900),
            ("eslint", ["npm", "--prefix", "desktop", "run", "lint"], 180),
            ("build", ["npm", "--prefix", "desktop", "run", "build"], 180),
            ("typecheck", ["npm", "--prefix", "desktop", "run", "typecheck"], 180),
            ("node", ["node", "--experimental-strip-types", "--test", "tests/todoFocus.test.mjs", "tests/todoViews.test.mjs", "tests/briefingSort.test.mjs", "tests/renderSafety.test.mjs", "tests/knowledgeLinks.test.mjs", "tests/taskChannel.test.mjs"], 60),
            ("ui", [str(PYTHON), "scripts/ui_check.py"], 120),
        ]
        if (ROOT / "AGENTS.md").is_file():
            commands.append(("policy", [str(PYTHON), "scripts/check_dev_policy.py"], 60))
    else:
        if selected["ruff"]:
            commands.append(("ruff", [str(PYTHON), "-m", "ruff", "check", "--select", "E4,E7,E9,F", *selected["ruff"]], 60))
        if selected["pytest"]:
            commands.append(("pytest", [str(PYTHON), "-m", "pytest", *selected["pytest"], "-q"], 300))
        if selected["eslint"]:
            commands.append(("eslint", ["npm", "--prefix", "desktop", "run", "lint"], 180))
        if selected["build"]:
            commands.append(("build", ["npm", "--prefix", "desktop", "run", "build"], 180))
        if selected["typecheck"]:
            commands.append(("typecheck", ["npm", "--prefix", "desktop", "run", "typecheck"], 180))
        if selected["node"]:
            commands.append(("node", ["node", "--experimental-strip-types", "--test", "tests/todoFocus.test.mjs", "tests/todoViews.test.mjs", "tests/briefingSort.test.mjs", "tests/renderSafety.test.mjs", "tests/knowledgeLinks.test.mjs", "tests/taskChannel.test.mjs"], 60))
        if selected["ui"]:
            commands.append(("ui", [str(PYTHON), "scripts/ui_check.py"], 120))
        if selected["policy"]:
            commands.append(("policy", [str(PYTHON), "scripts/check_dev_policy.py"], 60))
    with tempfile.TemporaryDirectory(prefix="stella-quality-") as directory:
        env = isolated_env(Path(directory))
        results = [run_check(name, command, env, timeout) for name, command, timeout in commands]
    if args.mode == "full":
        markdown_report(results, args.report)
    for name in ("ruff", "pytest", "eslint", "typecheck", "build", "node", "ui", "policy"):
        if name not in {item[0] for item in results}:
            print(f"SKIP {name}: no relevant changes")
    return int(any(item[1] == "FAIL" for item in results))


if __name__ == "__main__":
    sys.exit(main())
