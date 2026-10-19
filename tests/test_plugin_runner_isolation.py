"""Frozen/dedicated runner must not boot app.py business stack (R01 evidence).

How to produce the product binary (no system Python needed at runtime):

    pip install pyinstaller
    pyinstaller desktop/build/stella-plugin-runner.spec --noconfirm \\
        --distpath desktop/build/dist --workpath desktop/build/build-work
    # -> desktop/build/dist/stella-plugin-runner/stella-plugin-runner

Ship it next to ``stella-backend`` or export ``STELLA_PLUGIN_RUNNER=<binary>``.
The smoke-build test below does exactly this into a temp dir when PyInstaller
is importable (or ``STELLA_PYINSTALLER_PATH`` points to a site dir that has it).
``STELLA_PLUGIN_RUNNER_BINARY`` can point the smoke test at a prebuilt binary.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.plugins.host import (
    RUNNER_BINARY_NAME,
    RUNNER_DEV_MODULE,
    PluginHostError,
    PluginSession,
    resolve_runner_command,
)
from core.plugins.registry import PluginRegistry

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "desktop" / "build" / "stella-plugin-runner.spec"
ALPHA = REPO / "samples" / "plugins" / "alpha"
BUSINESS_MODULES = ("app", "application", "agent", "channel", "plugins", "models")


# --------------------------------------------------------------------------
# cli refusal / dev -m path
# --------------------------------------------------------------------------


def test_runner_cli_refuses_if_app_imported():
    code = (
        "import app\n"
        "from core.plugins.runner.cli import main\n"
        "raise SystemExit(main())\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "refuses polluted process" in (proc.stderr + proc.stdout)


def test_dedicated_runner_command_starts_sample():
    registry = PluginRegistry()
    session = PluginSession(
        ALPHA,
        source_label="sample",
        registry=registry,
        runner_command=[sys.executable, "-m", RUNNER_DEV_MODULE],
    )
    try:
        started = session.start()
        assert started["initialize"]["pluginId"] == "stella.sample.alpha"
    finally:
        session.dispose()


def test_runner_cli_import_does_not_pull_business_stack():
    code = (
        "import sys\n"
        "import core.plugins.runner.cli, core.plugins.runner.__main__\n"
        f"bad = [m for m in {BUSINESS_MODULES!r} if m in sys.modules]\n"
        "print(','.join(bad))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=str(REPO), capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


# --------------------------------------------------------------------------
# runner command resolution
# --------------------------------------------------------------------------


def test_resolve_prefers_env_override(tmp_path):
    fake = tmp_path / "custom-runner"
    fake.write_text("")
    cmd = resolve_runner_command(environ={"STELLA_PLUGIN_RUNNER": str(fake)}, frozen=True)
    assert cmd == [str(fake)]


def test_resolve_env_override_must_exist(tmp_path):
    with pytest.raises(PluginHostError):
        resolve_runner_command(environ={"STELLA_PLUGIN_RUNNER": str(tmp_path / "nope")})


def test_resolve_frozen_uses_sibling_binary(tmp_path):
    app_dir = tmp_path / "stella-backend"
    app_dir.mkdir()
    app_exe = app_dir / "stella-backend"
    app_exe.write_text("")
    sibling = tmp_path / RUNNER_BINARY_NAME / RUNNER_BINARY_NAME
    sibling.parent.mkdir()
    sibling.write_text("")
    cmd = resolve_runner_command(environ={}, frozen=True, executable=str(app_exe))
    assert cmd == [str(sibling.resolve())]


def test_resolve_frozen_prefers_binary_beside_executable(tmp_path):
    app_exe = tmp_path / "stella-backend"
    app_exe.write_text("")
    beside = tmp_path / RUNNER_BINARY_NAME
    beside.write_text("")
    cmd = resolve_runner_command(environ={}, frozen=True, executable=str(app_exe))
    assert cmd == [str(beside.resolve())]


def test_resolve_frozen_without_binary_never_falls_back_to_dash_m(tmp_path):
    app_exe = tmp_path / "stella-backend"
    app_exe.write_text("")
    with pytest.raises(PluginHostError):
        resolve_runner_command(environ={}, frozen=True, executable=str(app_exe))


def test_resolve_dev_fallback_is_cli_module():
    cmd = resolve_runner_command(environ={}, frozen=False, python_executable="/py")
    assert cmd == ["/py", "-m", "core.plugins.runner.cli"]


def test_session_uses_resolved_command(monkeypatch, tmp_path):
    fake = tmp_path / "runner"
    fake.write_text("")
    monkeypatch.setenv("STELLA_PLUGIN_RUNNER", str(fake))
    seen: dict[str, list[str]] = {}

    def fake_popen(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        raise RuntimeError("stop")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    session = PluginSession(ALPHA, source_label="sample", registry=PluginRegistry())
    with pytest.raises(RuntimeError, match="stop"):
        session.start()
    assert seen["cmd"] == [str(fake)]


# --------------------------------------------------------------------------
# spec validation (AST, no PyInstaller needed)
# --------------------------------------------------------------------------


def _spec_tree() -> ast.Module:
    return ast.parse(SPEC.read_text(encoding="utf-8"), filename=str(SPEC))


def _assigned_list(tree: ast.Module, name: str) -> list[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise AssertionError(f"{name} not assigned in spec")


def _call_kwargs(tree: ast.Module, func: str) -> dict[str, ast.expr]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func:
            return {k.arg: k.value for k in node.keywords if k.arg}
    raise AssertionError(f"{func}(...) not called in spec")


def test_spec_entry_is_runner_cli_not_app():
    tree = _spec_tree()
    analysis = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "Analysis"
    )
    entry_src = ast.unparse(analysis.args[0])
    assert "'core', 'plugins', 'runner', 'cli.py'" in entry_src
    assert "app.py" not in entry_src
    assert (REPO / "core" / "plugins" / "runner" / "cli.py").is_file()


def test_spec_names_binary_and_bundles_only_runtime_modules():
    tree = _spec_tree()
    for func in ("EXE", "COLLECT"):
        kwargs = _call_kwargs(tree, func)
        assert ast.literal_eval(kwargs["name"]) == RUNNER_BINARY_NAME
    hidden = set(_assigned_list(tree, "hiddenimports"))
    assert {
        "core.plugins.protocol",
        "core.plugins.contract",
        "core.plugins.manifest",
        "core.plugins.runner.__main__",
    } <= hidden
    excludes = set(_assigned_list(tree, "excludes"))
    assert {"app", "application", "agent", "channel", "plugins", "core.plugins.host"} <= excludes
    assert not (hidden & excludes)
    # Every hidden core.* module must exist in the repo.
    for mod in hidden:
        if mod.startswith("core"):
            assert importlib.util.find_spec(mod) is not None, mod


def test_runner_modules_import_only_runtime_deps():
    """Runner-side import closure stays inside protocol/contract/manifest/registry."""
    allowed_core = {
        "core",
        "core.plugins",
        "core.plugins.protocol",
        "core.plugins.contract",
        "core.plugins.manifest",
        "core.plugins.registry",
        "core.plugins.runner",
        "core.plugins.runner.__main__",
        "core.plugins.runner.cli",
    }
    code = (
        "import sys\n"
        "import core.plugins.runner.cli, core.plugins.runner.__main__\n"
        "print('\\n'.join(sorted(m for m in sys.modules if m == 'core' or m.startswith('core.'))))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=str(REPO), capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    loaded = set(proc.stdout.split())
    assert loaded <= allowed_core, loaded - allowed_core


# --------------------------------------------------------------------------
# frozen binary smoke (build to temp dist when PyInstaller is available)
# --------------------------------------------------------------------------


def _pyinstaller_env() -> dict[str, str] | None:
    env = os.environ.copy()
    extra = env.get("STELLA_PYINSTALLER_PATH")
    if extra:
        env["PYTHONPATH"] = extra + os.pathsep + env.get("PYTHONPATH", "")
    probe = subprocess.run(
        [sys.executable, "-c", "import PyInstaller"], env=env, capture_output=True
    )
    return env if probe.returncode == 0 else None


def _frozen_binary(tmp_path_factory) -> Path:
    prebuilt = os.environ.get("STELLA_PLUGIN_RUNNER_BINARY")
    if prebuilt:
        path = Path(prebuilt)
        if not path.is_file():
            pytest.skip(f"STELLA_PLUGIN_RUNNER_BINARY missing: {prebuilt}")
        return path
    env = _pyinstaller_env()
    if env is None:
        pytest.skip("PyInstaller not available; see module docstring to build the runner")
    out = tmp_path_factory.mktemp("runner-build")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(SPEC),
            "--noconfirm",
            "--distpath",
            str(out / "dist"),
            "--workpath",
            str(out / "work"),
        ],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    name = RUNNER_BINARY_NAME + (".exe" if sys.platform == "win32" else "")
    binary = out / "dist" / RUNNER_BINARY_NAME / name
    assert binary.is_file()
    return binary


@pytest.fixture(scope="module")
def frozen_runner(tmp_path_factory) -> Path:
    return _frozen_binary(tmp_path_factory)


def test_frozen_runner_runs_alpha_without_system_python(frozen_runner, tmp_path, monkeypatch):
    # Product path: binary selected through the env hook, no -m, no repo cwd,
    # no python on PATH / PYTHONPATH.
    monkeypatch.setenv("STELLA_PLUGIN_RUNNER", str(frozen_runner))
    monkeypatch.setenv("STELLA_RUNNER_CWD", str(tmp_path))
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTHONHOME", raising=False)
    monkeypatch.setenv("STELLA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    session = PluginSession(ALPHA, source_label="sample", registry=PluginRegistry())
    assert session._runner_command is None  # resolved by host, not injected
    try:
        started = session.start()
        assert started["initialize"]["pluginId"] == "stella.sample.alpha"
        assert session._proc is not None
        assert session._proc.args == [str(frozen_runner)]
        assert "-m" not in session._proc.args
        result = session.invoke("ping", {"echo": 7})
        assert result["status"] == "succeeded"
        assert result["value"]["pong"] is True
        assert result["value"]["echo"] == 7
    finally:
        session.dispose()
    # Nothing under STELLA_DATA_DIR/HOME: no app init, watcher, scheduler, run-record recovery.
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "home").exists()


def test_frozen_runner_sibling_discovery(frozen_runner, tmp_path):
    """A frozen app dir with the runner dist beside it resolves without env override."""
    app_dir = tmp_path / "stella-backend"
    app_dir.mkdir()
    app_exe = app_dir / "stella-backend"
    app_exe.write_text("")
    link = tmp_path / RUNNER_BINARY_NAME
    link.symlink_to(frozen_runner.parent, target_is_directory=True)
    cmd = resolve_runner_command(environ={}, frozen=True, executable=str(app_exe))
    assert Path(cmd[0]).resolve() == frozen_runner.resolve()
