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


def test_bootstrap_keeps_installed_version_without_loading_catalog(tmp_path):
    store = PackageStore(tmp_path / "pkg")
    op = store.stage(Path("samples/plugins/alpha"))
    store.inspect(op.operation_id)
    store.prepare(op.operation_id)
    store.commit(op.operation_id)
    before = store.current_package("stella.sample.alpha")
    result = bootstrap_default_plugins(
        catalog_path=tmp_path / "offline.json", package_store=store,
        plugin_ids=["stella.sample.alpha"],
    )
    assert result["status"] == "ok"
    assert store.current_package("stella.sample.alpha") == before


def test_bootstrap_continues_after_one_catalog_entry_is_missing(tmp_path):
    catalog = _catalog(tmp_path, "stella.sample.alpha", Path("samples/plugins/alpha"))
    store = PackageStore(tmp_path / "pkg")
    result = bootstrap_default_plugins(
        catalog_path=catalog, package_store=store,
        plugin_ids=["stella.missing", "stella.sample.alpha"],
    )
    assert result["status"] == "partial"
    assert result["failed"][0]["pluginId"] == "stella.missing"
    assert result["installed"] == ["stella.sample.alpha"]


@pytest.mark.parametrize("damage", ["missing", "modified"])
def test_bootstrap_does_not_activate_corrupt_committed_package(tmp_path, monkeypatch, damage):
    import shutil
    from core.plugins.bootstrap import run_desktop_bootstrap

    sample = tmp_path / "source"
    shutil.copytree(Path("samples/plugins/alpha"), sample)
    manifest = json.loads((sample / "plugin.json").read_text())
    manifest["id"] = "stella.bills"
    (sample / "plugin.json").write_text(json.dumps(manifest))
    catalog = _catalog(tmp_path, "stella.bills", sample)
    monkeypatch.setattr("core.plugins.bootstrap.load_default_plugin_manifest",
                        lambda: {"plugins": [{"pluginId": "stella.bills"}]})
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    monkeypatch.delenv("STELLA_BILLS_PLUGIN", raising=False)
    result = run_desktop_bootstrap(data_dir=tmp_path / "data", catalog_path=catalog)
    assert result["status"] == "ok"
    monkeypatch.delenv("STELLA_BILLS_PLUGIN", raising=False)
    current = PackageStore(tmp_path / "data" / "plugin-packages").current_package("stella.bills")
    target = Path(current["path"])
    if damage == "missing":
        shutil.rmtree(target)
    else:
        (target / "backend" / "main.py").write_text("tampered")
    result = run_desktop_bootstrap(data_dir=tmp_path / "data", catalog_path=tmp_path / "offline.json")
    assert result["status"] == "partial"
    assert result["installed"] == []
    assert "STELLA_BILLS_PLUGIN" not in result["envApplied"]
