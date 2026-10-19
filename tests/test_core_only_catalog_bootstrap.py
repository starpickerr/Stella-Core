"""Core-only packaging: catalog without plugin-seed yields missing_source."""
from __future__ import annotations

import json
from pathlib import Path

from core.plugins.bootstrap import bootstrap_default_plugins
from core.plugins.package_ops import PackageStore


def test_catalog_without_local_paths_reports_missing_source(tmp_path):
    catalog = {
        "coreApi": "1.0.0",
        "plugins": [
            {
                "pluginId": "stella.bills",
                "hostApi": "^1.0.0",
                "version": "1.1.2",
                "sha256": "0" * 64,
            },
            {
                "pluginId": "stella.tasks",
                "hostApi": "^1.0.0",
                "version": "1.1.3",
                "sha256": "1" * 64,
            },
        ],
    }
    catalog_path = tmp_path / "plugin-catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    store = PackageStore(tmp_path / "packages")
    result = bootstrap_default_plugins(
        catalog_path=catalog_path,
        package_store=store,
        plugin_ids=["stella.bills", "stella.tasks"],
    )
    assert result["status"] == "partial"
    assert result["installed"] == []
    assert {row["pluginId"] for row in result["failed"]} == {"stella.bills", "stella.tasks"}
    assert all(row["status"] == "missing_source" for row in result["failed"])
    assert not list((tmp_path / "packages" / "packages").glob("stella.*/current.json"))


def test_sync_script_writes_catalog_without_seed_tree(tmp_path, monkeypatch):
    """desktop/scripts/sync-plugin-seed.mjs must not materialize plugin-seed packages."""
    script = Path("desktop/scripts/sync-plugin-seed.mjs").read_text(encoding="utf-8")
    assert "plugin-seed" in script or "catalog" in script.lower()
    # Contract: packaged extraResources must not ship plugin-seed trees.
    package_json = json.loads(Path("desktop/package.json").read_text(encoding="utf-8"))
    filters = []
    for item in package_json["build"]["extraResources"]:
        if isinstance(item, dict) and "filter" in item:
            filters.extend(item["filter"])
    assert "plugin-seed/**" not in filters
    assert "plugin-catalog.json" in filters
