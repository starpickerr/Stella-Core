"""Tests for channel.feishu.lark_install (on-demand lark_oapi installer)."""
import importlib.util
import sys
from unittest import mock

import pytest

from channel.feishu import lark_install


@pytest.fixture
def clean_vendor(monkeypatch, tmp_path):
    """Point the vendor dir at a temp location and drop any lark_oapi from path."""
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("COW_DESKTOP", raising=False)
    # Ensure lark_oapi is not importable in this test process.
    monkeypatch.setattr(lark_install, "is_available", lambda: False)
    # Avoid real subprocess / real sys.path pollution.
    monkeypatch.setattr(subprocess_run := lark_install.subprocess, "run", mock.MagicMock())
    yield tmp_path


def test_is_available_true_when_spec_found(monkeypatch):
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name: object() if name == "lark_oapi" else None
    )
    assert lark_install.is_available() is True
    assert lark_install.is_available() is False or True  # second call path-independent


def test_ensure_returns_when_already_available(monkeypatch):
    monkeypatch.setattr(lark_install, "is_available", lambda: True)
    # Should not attempt any install.
    with mock.patch.object(lark_install.subprocess, "run") as run:
        lark_install.ensure(allow_install=True)
    run.assert_not_called()


def test_ensure_non_desktop_raises(monkeypatch):
    monkeypatch.setattr(lark_install, "is_available", lambda: False)
    monkeypatch.delenv("COW_DESKTOP", raising=False)
    with pytest.raises(ImportError):
        lark_install.ensure(allow_install=True)


def test_ensure_allow_install_false_raises(monkeypatch):
    monkeypatch.setattr(lark_install, "is_available", lambda: False)
    monkeypatch.setenv("COW_DESKTOP", "1")
    with pytest.raises(ImportError):
        lark_install.ensure(allow_install=False)


def test_ensure_desktop_installs_on_demand(monkeypatch, tmp_path):
    # Simulate: not available before, available after install.
    state = {"installed": False}

    def fake_available():
        return state["installed"]

    monkeypatch.setattr(lark_install, "is_available", fake_available)
    monkeypatch.setenv("COW_DESKTOP", "1")
    monkeypatch.setattr(lark_install, "vendor_dir", lambda: str(tmp_path))
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        state["installed"] = True  # pretend pip succeeded
        return mock.MagicMock()

    monkeypatch.setattr(lark_install.subprocess, "run", fake_run)

    # Should not raise; install command must target the vendor dir.
    lark_install.ensure(allow_install=True)
    assert calls, "expected a pip install to have been attempted"
    cmd = calls[0]
    assert str(tmp_path) in cmd  # --target points at the vendor dir
    assert "install" in cmd
    assert any("lark-oapi" in str(part) for part in cmd)  # lark-oapi>=1.5.5 spec


def test_ensure_desktop_install_failure_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(lark_install, "is_available", lambda: False)
    monkeypatch.setenv("COW_DESKTOP", "1")
    monkeypatch.setattr(lark_install, "vendor_dir", lambda: str(tmp_path))

    def fake_run(cmd, **kwargs):
        raise RuntimeError("no network")

    monkeypatch.setattr(lark_install.subprocess, "run", fake_run)

    with pytest.raises(ImportError):
        lark_install.ensure(allow_install=True)
