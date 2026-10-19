"""Installed PackageStore roots win over missing workspace mirrors (frozen desktop)."""

from __future__ import annotations

import json
from pathlib import Path

from core.plugins.roots import resolve_plugin_package_root


def test_resolve_prefers_installed_package_store(tmp_path, monkeypatch):
    monkeypatch.delenv("STELLA_TODOS_PLUGIN_ROOT", raising=False)
    pkg = tmp_path / "home" / "stella" / "plugin-packages" / "packages" / "stella.tasks" / "1.0.0" / "deadbeef"
    pkg.mkdir(parents=True)
    (pkg / "plugin.json").write_text("{}", encoding="utf-8")
    current = pkg.parent.parent / "current.json"
    # PackageStore layout: packages/<id>/current.json
    store_root = tmp_path / "home" / "stella" / "plugin-packages"
    (store_root / "packages" / "stella.tasks").mkdir(parents=True, exist_ok=True)
    (store_root / "packages" / "stella.tasks" / "current.json").write_text(
        json.dumps({"pluginId": "stella.tasks", "path": str(pkg), "digest": "deadbeef"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("STELLA_DATA_DIR", raising=False)

    # Force state_root under our temp home.
    monkeypatch.setattr(
        "common.state_dir.state_root",
        lambda identity=None: tmp_path / "home" / "stella",
    )
    # Pretend frozen so workspace fallback is skipped even if present.
    monkeypatch.setattr("core.plugins.roots._is_frozen", lambda: True)
    monkeypatch.setattr(
        "core.plugins.roots._repo_root",
        lambda: tmp_path / "missing-core",
    )

    root = resolve_plugin_package_root(
        plugin_id="stella.tasks",
        env_var="STELLA_TODOS_PLUGIN_ROOT",
        folder_name="tasks",
    )
    assert root == pkg
