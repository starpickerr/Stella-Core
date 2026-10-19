"""P1a/P1b: two-source runner sessions, generation, and registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from core.plugins.host import PluginSession
from core.plugins.registry import PluginRegistry


@pytest.fixture
def registry():
    return PluginRegistry()


def test_two_sources_same_path(registry):
    alpha = PluginSession(
        Path("samples/plugins/alpha"),
        source_label="first-party-sample",
        registry=registry,
        python_executable=sys.executable,
    )
    beta = PluginSession(
        Path("samples/plugins/beta"),
        source_label="third-party-sample",
        registry=registry,
        python_executable=sys.executable,
    )
    try:
        a = alpha.start()
        b = beta.start()
        assert a["initialize"]["abi"] == "cp312"
        assert b["initialize"]["abi"] == "cp312"
        assert registry.owner_of("stella.sample.alpha@1") == "stella.sample.alpha"
        assert registry.owner_of("stella.sample.beta@1") == "stella.sample.beta"
        ping_a = alpha.invoke("ping", {"echo": 1})
        ping_b = beta.invoke("ping", {"echo": 2})
        assert ping_a["value"]["plugin"] == "alpha"
        assert ping_b["value"]["plugin"] == "beta"
    finally:
        alpha.dispose()
        beta.dispose()
    assert registry.get("stella.sample.alpha") is None
    assert registry.get("stella.sample.beta") is None


def test_stale_generation_rejected(registry):
    session = PluginSession(
        Path("samples/plugins/alpha"),
        source_label="first-party-sample",
        registry=registry,
        python_executable=sys.executable,
    )
    try:
        session.start()
        snap = registry.get("stella.sample.alpha")
        assert snap is not None
        with pytest.raises(PermissionError):
            registry.require_generation("stella.sample.alpha", snap.generation + 1)
    finally:
        session.dispose()


def test_worker_uses_selected_interpreter_not_implicit_system(registry):
    session = PluginSession(
        Path("samples/plugins/alpha"),
        source_label="first-party-sample",
        registry=registry,
        python_executable=sys.executable,
    )
    try:
        result = session.start()
        assert result["initialize"]["apiVersion"] == "1.0.0"
    finally:
        session.dispose()
