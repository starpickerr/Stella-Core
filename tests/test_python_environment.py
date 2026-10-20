"""Development tooling must use Conda Stella without depending on a checkout venv."""

import sys
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import check_runtime


@pytest.fixture
def discovery(monkeypatch, tmp_path):
    for name in ('STELLA_PYTHON', 'CONDA_PREFIX', 'CONDA_EXE', 'CONDA_ENVS_PATH'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(sys, 'prefix', str(tmp_path / 'unrelated-python'))
    monkeypatch.setattr(check_runtime, '_standard_roots', lambda *_: [], raising=False)
    return tmp_path


def conda_python(prefix, platform='posix'):
    (prefix / 'conda-meta').mkdir(parents=True)
    executable = prefix / ('python.exe' if platform == 'nt' else 'bin/python')
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.touch()
    executable.chmod(0o755)
    return executable


def register(home, prefix):
    registry = home / '.conda/environments.txt'
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(str(prefix) + '\n')


def test_registered_stella_is_found_without_activation(discovery):
    interpreter = conda_python(discovery / 'custom location/envs/Stella')
    register(discovery, interpreter.parent.parent)
    assert check_runtime.python_path(discovery) == interpreter


def test_active_stella_is_selected(discovery, monkeypatch):
    prefix = discovery / 'envs/stella'
    interpreter = conda_python(prefix)
    monkeypatch.setenv('CONDA_PREFIX', str(prefix))
    assert check_runtime.python_path(discovery) == interpreter


def test_unrelated_active_environment_does_not_override_stella(discovery, monkeypatch):
    other = discovery / 'envs/other'
    conda_python(other)
    interpreter = conda_python(discovery / 'envs/Stella')
    register(discovery, interpreter.parent.parent)
    monkeypatch.setenv('CONDA_PREFIX', str(other))
    assert check_runtime.python_path(discovery) == interpreter


def test_running_stella_survives_a_temporary_home(discovery, monkeypatch):
    prefix = discovery / 'envs/Stella'
    interpreter = conda_python(prefix)
    monkeypatch.setattr(sys, 'prefix', str(prefix))
    assert check_runtime.python_path(discovery) == interpreter


def test_windows_conda_uses_prefix_python_exe(discovery, monkeypatch):
    prefix = discovery / 'envs/Stella'
    interpreter = conda_python(prefix, 'nt')
    monkeypatch.setenv('CONDA_PREFIX', str(prefix))
    assert check_runtime.python_path(discovery, 'nt') == interpreter


def test_explicit_missing_interpreter_does_not_fall_back(discovery, monkeypatch):
    interpreter = conda_python(discovery / 'envs/Stella')
    register(discovery, interpreter.parent.parent)
    monkeypatch.setenv('STELLA_PYTHON', str(discovery / 'missing-python'))
    with pytest.raises(FileNotFoundError, match='STELLA_PYTHON'):
        check_runtime.python_path(discovery)


def test_ci_override_can_resolve_an_executable_on_path(discovery, monkeypatch):
    interpreter = discovery / 'ci-python'
    interpreter.touch()
    interpreter.chmod(0o755)
    monkeypatch.setenv('STELLA_PYTHON', 'ci-python')
    monkeypatch.setattr(check_runtime.shutil, 'which', lambda name: str(interpreter))
    assert check_runtime.python_path(discovery) == interpreter


def test_checkout_venv_is_not_a_fallback(discovery):
    stale = discovery / '.venv/bin/python'
    stale.parent.mkdir(parents=True)
    stale.touch()
    with pytest.raises(FileNotFoundError, match='Stella'):
        check_runtime.python_path(discovery)


def test_make_explicit_python_needs_no_other_python_on_path():
    make = shutil.which('make')
    if make is None:
        pytest.skip('make is not installed')
    env = {key: value for key, value in os.environ.items()
           if key in {'SYSTEMROOT', 'WINDIR', 'HOME', 'USERPROFILE'}}
    env.update(PATH='', STELLA_PYTHON=sys.executable)
    result = subprocess.run(
        [make, '--no-print-directory', '-s', '-f', 'Makefile', '-f', '-', 'print-python'],
        input='print-python:\n\t@echo "$(STELLA_PYTHON)"\n',
        cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == sys.executable
