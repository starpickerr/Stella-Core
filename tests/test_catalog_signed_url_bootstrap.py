"""Core-only first boot: catalog relative signed ZIP urls install and recover."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.plugins.bootstrap import bootstrap_default_plugins
from core.plugins.distribution import _package_files, fetch_and_install_from_catalog
from core.plugins.package_ops import PackageStore
from core.plugins.signing import write_signed_zip


DOMAINS = ("bills", "tasks")
SECRET = b"stella-first-edition-plugin-catalog"


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in _package_files(root):
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _layout(tmp_path: Path) -> tuple[Path, Path]:
    """Resources-like layout: catalog.json + plugin-packages/*.zip, no plugin-seed."""
    resources = tmp_path / "Resources"
    packages = resources / "plugin-packages"
    packages.mkdir(parents=True)
    plugins_root = Path("stella-plugins-workspace/plugins")
    if not plugins_root.is_dir():
        plugins_root = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins"
    entries = []
    for domain in DOMAINS:
        src = plugins_root / domain
        archive = packages / f"{domain}.zip"
        write_signed_zip(src, archive, secret=SECRET)
        manifest = json.loads((src / "plugin.json").read_text(encoding="utf-8"))
        entries.append({
            "pluginId": f"stella.{domain}",
            "hostApi": "^1.0.0",
            "version": manifest["version"],
            "url": f"plugin-packages/{domain}.zip",
            "sha256": _tree_digest(src),
            "signatureAlg": "hmac-sha256",
        })
    catalog_path = resources / "plugin-catalog.json"
    catalog_path.write_text(json.dumps({"coreApi": "1.0.0", "plugins": entries}), encoding="utf-8")
    assert not (resources / "plugin-seed").exists()
    return catalog_path, packages


def test_relative_signed_url_installs_without_local_path(tmp_path, monkeypatch):
    catalog_path, _packages = _layout(tmp_path)
    monkeypatch.setenv("STELLA_PLUGIN_SIGNING_SECRET", SECRET.decode("ascii"))
    store = PackageStore(tmp_path / "pkg")
    result = fetch_and_install_from_catalog(
        catalog_path=catalog_path,
        plugin_id="stella.bills",
        package_store=store,
    )
    assert result["status"] == "installed"
    assert store.current_package("stella.bills") is not None


def test_bootstrap_from_signed_urls_installs_all_and_survives_rerun(tmp_path, monkeypatch):
    catalog_path, _packages = _layout(tmp_path)
    monkeypatch.setenv("STELLA_PLUGIN_SIGNING_SECRET", SECRET.decode("ascii"))
    store = PackageStore(tmp_path / "pkg")
    first = bootstrap_default_plugins(
        catalog_path=catalog_path,
        package_store=store,
        plugin_ids=[f"stella.{d}" for d in DOMAINS],
    )
    assert first["status"] == "ok"
    assert set(first["installed"]) == {f"stella.{d}" for d in DOMAINS}
    second = bootstrap_default_plugins(
        catalog_path=catalog_path,
        package_store=store,
        plugin_ids=[f"stella.{d}" for d in DOMAINS],
    )
    assert second["status"] == "ok"
    assert set(second["installed"]) == {f"stella.{d}" for d in DOMAINS}
    currents = list((tmp_path / "pkg" / "packages").glob("stella.*/current.json"))
    assert len(currents) == len(DOMAINS)


def test_sync_script_emits_signed_packages_not_seed_trees():
    script = Path("desktop/scripts/sync-plugin-seed.mjs").read_text(encoding="utf-8")
    assert "plugin-packages" in script
    assert "write_signed_zip" in script or "pack_signed" in script or "signing" in script.lower()
    package_json = json.loads(Path("desktop/package.json").read_text(encoding="utf-8"))
    filters = []
    for item in package_json["build"]["extraResources"]:
        if isinstance(item, dict) and "filter" in item:
            filters.extend(item["filter"])
    assert "plugin-packages/**" in filters
    assert "plugin-seed/**" not in filters
    assert "plugin-catalog.json" in filters
