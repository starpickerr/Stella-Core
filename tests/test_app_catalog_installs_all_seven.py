"""Packaged Stella.app catalog must install all signed first-party plugins."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins.distribution import fetch_and_install_from_catalog
from core.plugins.package_ops import PackageStore

REPO = Path(__file__).resolve().parent.parent
APP_CATALOG = (
    REPO / "desktop" / "release" / "mac-arm64" / "Stella.app"
    / "Contents" / "Resources" / "plugin-catalog.json"
)
SECRET = (
    REPO / "desktop" / "release" / "mac-arm64" / "Stella.app"
    / "Contents" / "Resources" / "plugin-signing.secret"
)


@pytest.mark.skipif(not APP_CATALOG.is_file(), reason="Stella.app not built")
def test_app_catalog_installs_all_seven(tmp_path, monkeypatch):
    monkeypatch.setenv("STELLA_PLUGIN_SIGNING_SECRET", SECRET.read_text(encoding="utf-8").strip())
    store = PackageStore(tmp_path / "pkg")
    results = {}
    for plugin_id in (
        "stella.bills", "stella.calendar", "stella.tasks", "stella.email",
        "stella.elearning", "stella.briefing", "stella.automation", "stella.agent-hub",
    ):
        results[plugin_id] = fetch_and_install_from_catalog(
            catalog_path=APP_CATALOG,
            plugin_id=plugin_id,
            package_store=store,
        )["status"]
    assert all(status == "installed" for status in results.values()), results
