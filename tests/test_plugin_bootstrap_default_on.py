"""First-boot default install activates plugins on the desktop path (G5 / D)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.plugins.bootstrap import (
    DOMAIN_ENV,
    apply_desktop_plugin_defaults,
    bootstrap_default_plugins,
)
from core.plugins.package_ops import PackageStore


def _catalog(tmp_path: Path, plugin_id: str, source: Path) -> Path:
    import hashlib

    from core.plugins.distribution import _package_files

    h = hashlib.sha256()
    for path in _package_files(source):
        h.update(path.relative_to(source).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    catalog = {
        "coreApi": "1.0.0",
        "plugins": [
            {
                "pluginId": plugin_id,
                "hostApi": "^1.0.0",
                "path": str(source.resolve()),
                "sha256": h.hexdigest(),
            }
        ],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path


def test_bootstrap_installs_and_records_intents(tmp_path, monkeypatch):
    sample = Path("samples/plugins/alpha")
    catalog = _catalog(tmp_path, "stella.sample.alpha", sample)
    store = PackageStore(tmp_path / "pkg")
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    result = bootstrap_default_plugins(
        catalog_path=catalog,
        package_store=store,
        plugin_ids=["stella.sample.alpha"],
        user_intents={},
    )
    assert result["status"] == "ok"
    assert "stella.sample.alpha" in result["installed"]
    assert store.current_package("stella.sample.alpha") is not None


def test_removed_intent_not_resurrected_on_retry(tmp_path, monkeypatch):
    sample = Path("samples/plugins/alpha")
    catalog = _catalog(tmp_path, "stella.sample.alpha", sample)
    store = PackageStore(tmp_path / "pkg")
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    result = bootstrap_default_plugins(
        catalog_path=catalog,
        package_store=store,
        plugin_ids=["stella.sample.alpha"],
        user_intents={"stella.sample.alpha": "removed"},
    )
    assert result["installed"] == []
    assert result["skipped"][0]["status"] == "skipped_user_intent"


def test_desktop_defaults_enable_env_for_installed_domains(tmp_path, monkeypatch):
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    monkeypatch.delenv("STELLA_BILLS_PLUGIN", raising=False)
    intents = tmp_path / "intents.json"
    intents.write_text(json.dumps({"stella.bills": "enabled"}), encoding="utf-8")
    apply_desktop_plugin_defaults(
        installed_ids=["stella.bills"],
        intents_path=intents,
    )
    assert __import__("os").environ.get("STELLA_BILLS_PLUGIN") == "1"
    assert DOMAIN_ENV["stella.bills"] == "STELLA_BILLS_PLUGIN"


def test_explicit_zero_wins_over_desktop_default(tmp_path, monkeypatch):
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    monkeypatch.setenv("STELLA_BILLS_PLUGIN", "0")
    apply_desktop_plugin_defaults(
        installed_ids=["stella.bills"],
        intents_path=tmp_path / "missing.json",
    )
    assert __import__("os").environ.get("STELLA_BILLS_PLUGIN") == "0"
