"""Package digests and signed ZIPs must ignore local test caches."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from core.plugins.distribution import (
    _package_files,
    fetch_and_install_from_catalog,
    verify_package_digest,
)
from core.plugins.package_ops import PackageStore, _sha256_tree
from core.plugins.signing import write_signed_zip
import zipfile


_MANIFEST = """{
  "manifestVersion": 1,
  "id": "stella.demo",
  "name": "Demo",
  "version": "1.0.0",
  "hostApi": "^1.0.0",
  "contributes": {"services": ["stella.demo@1"]},
  "permissions": []
}
"""


def _dirty_pkg(tmp_path: Path) -> Path:
    root = tmp_path / "pkg"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / "main.py").write_text("ok\n", encoding="utf-8")
    (root / "plugin.json").write_text(_MANIFEST, encoding="utf-8")
    cache = root / ".pytest_cache" / "v" / "cache"
    cache.mkdir(parents=True)
    (cache / "nodeids").write_text("x\n", encoding="utf-8")
    git = root / ".git" / "objects"
    git.mkdir(parents=True)
    (git / "deadbeef").write_text("blob\n", encoding="utf-8")
    return root


def test_package_files_skips_pytest_cache_and_git(tmp_path):
    root = _dirty_pkg(tmp_path)
    names = {path.relative_to(root).as_posix() for path in _package_files(root)}
    assert names == {"backend/main.py", "plugin.json"}


def test_sha256_tree_matches_package_files_when_caches_present(tmp_path):
    """Lifecycle integrity must use the same filters as catalog digests."""
    root = _dirty_pkg(tmp_path)
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "backend").mkdir()
    (clean / "backend" / "main.py").write_text("ok\n", encoding="utf-8")
    (clean / "plugin.json").write_text(_MANIFEST, encoding="utf-8")
    expected = _sha256_tree(clean)
    assert _sha256_tree(root) == expected
    assert verify_package_digest(root, expected)


def test_package_store_stage_digest_ignores_source_caches(tmp_path):
    root = _dirty_pkg(tmp_path)
    store = PackageStore(tmp_path / "store")
    op = store.stage(root)
    clean_digest = _sha256_tree(tmp_path / "pkg")  # dirty root, filtered digest
    assert op.digest == clean_digest
    # staged tree must not carry caches into the immutable package path
    staged = tmp_path / "store" / "staging" / op.operation_id
    assert not (staged / ".pytest_cache").exists()
    assert not (staged / ".git").exists()


def test_signed_zip_omits_pytest_cache(tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "plugin.json").write_text('{"id":"x"}', encoding="utf-8")
    cache = root / ".pytest_cache"
    cache.mkdir()
    (cache / "README.md").write_text("cache\n", encoding="utf-8")
    archive = tmp_path / "pkg.zip"
    write_signed_zip(root, archive, secret=b"test-secret")
    with zipfile.ZipFile(archive) as outer:
        inner = tmp_path / "inner.zip"
        inner.write_bytes(outer.read("package.zip"))
    with zipfile.ZipFile(inner) as zf:
        names = set(zf.namelist())
    assert "plugin.json" in names
    assert not any(name.startswith(".pytest_cache") for name in names)


def _official_bills_entry() -> tuple[dict, Path]:
    catalog_path = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "catalog" / "official.json"
    if not catalog_path.is_file():
        catalog_path = Path("..") / "Stella-Plugins" / "catalog" / "official.json"
    if not catalog_path.is_file():
        import pytest
        pytest.skip("Stella-Plugins sibling checkout not present")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entry = next(p for p in catalog["plugins"] if p["pluginId"] == "stella.bills")
    root = (catalog_path.parent / entry["path"]).resolve()
    return entry, root


def test_dirty_path_catalog_prepare_digest_matches_official(tmp_path):
    """Path catalog install must store the catalog sha even when the source tree has caches."""
    entry, src = _official_bills_entry()
    dirty = tmp_path / "plugins" / "bills"
    shutil.copytree(src, dirty, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (dirty / ".pytest_cache").mkdir()
    (dirty / ".pytest_cache" / "v").write_text("x\n", encoding="utf-8")
    (dirty / ".git").mkdir()
    (dirty / ".git" / "config").write_text("y\n", encoding="utf-8")
    assert verify_package_digest(dirty, entry["sha256"])

    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps({"coreApi": "1.0.0", "plugins": [{**entry, "path": str(dirty)}]}),
        encoding="utf-8",
    )
    store = PackageStore(tmp_path / "store")
    result = fetch_and_install_from_catalog(
        catalog_path=catalog,
        plugin_id="stella.bills",
        package_store=store,
        prepare_only=True,
    )
    assert result["status"] == "prepared"
    assert result["digest"] == entry["sha256"]


def test_installed_package_digest_stable_after_cache_inject(tmp_path):
    """Lifecycle integrity must ignore caches that appear after install."""
    entry, src = _official_bills_entry()
    clean = tmp_path / "plugins" / "bills"
    shutil.copytree(src, clean, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".git"))
    store = PackageStore(tmp_path / "store")
    op = store.stage(clean)
    op = store.inspect(op.operation_id)
    op = store.prepare(op.operation_id)
    op = store.commit(op.operation_id)
    current = store.current_package("stella.bills")
    assert current is not None
    assert current["digest"] == entry["sha256"]

    package = Path(current["path"])
    cache = package / ".pytest_cache"
    cache.mkdir()
    (cache / "pollute").write_text("x\n", encoding="utf-8")
    assert _sha256_tree(package) == current["digest"]
    assert verify_package_digest(package, current["digest"])


def test_release_builder_preserves_manifest_versions(tmp_path, monkeypatch):
    import importlib.util
    script = Path(__file__).resolve().parents[2] / 'Stella-Plugins/scripts/build_release_catalog.py'
    spec = importlib.util.spec_from_file_location('stella_release_builder_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'catalog').mkdir()
    source = tmp_path / 'plugins/demo'
    source.mkdir(parents=True)
    manifest = json.loads(_MANIFEST)
    manifest['version'] = '1.2.3'
    source.joinpath('plugin.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'DOMAINS', ('demo',))
    monkeypatch.setenv('STELLA_PLUGIN_SIGNING_SECRET', 'test-release-secret')
    assert module.main() == 0
    catalog = tmp_path / 'catalog/release.json'
    row = json.loads(catalog.read_text())['plugins'][0]
    assert row['version'] == '1.2.3'
    assert '1.2.3' in row['url']
    result = fetch_and_install_from_catalog(catalog_path=catalog, plugin_id='stella.demo',
                                            package_store=PackageStore(tmp_path / 'packages'))
    assert result['status'] == 'installed'


def test_desktop_source_catalog_installs_all_first_party_plugins(tmp_path, monkeypatch):
    import importlib.util
    script = Path('desktop/scripts/pack_signed_plugin_catalog.py').resolve()
    spec = importlib.util.spec_from_file_location('stella_pack_catalog_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    resources = tmp_path / 'resources'
    monkeypatch.setattr(module, 'RESOURCES', resources)
    monkeypatch.setattr(module, 'PACKAGES', resources / 'plugin-packages')
    monkeypatch.setattr(module, 'CATALOG_OUT', resources / 'plugin-catalog.json')
    monkeypatch.setattr(module, 'SECRET_FILE', resources / 'plugin-signing.secret')
    monkeypatch.setenv('STELLA_PLUGIN_SIGNING_SECRET', 'test-source-catalog-secret')
    assert module.main() == 0
    catalog = resources / 'plugin-catalog.json'
    rows = json.loads(catalog.read_text())['plugins']
    expected = {f'stella.{name}' for name in
                ['bills', 'calendar', 'tasks', 'email', 'elearning', 'briefing', 'automation', 'agent-hub']}
    assert {row['pluginId'] for row in rows} == expected
    store = PackageStore(tmp_path / 'installed')
    for row in rows:
        assert fetch_and_install_from_catalog(catalog_path=catalog, plugin_id=row['pluginId'],
                                               package_store=store)['status'] == 'installed'


def test_desktop_management_bootstrap_adopts_all_first_party_plugins(tmp_path, monkeypatch):
    from core.plugins.bootstrap import run_desktop_bootstrap
    import sqlite3
    hub_db = tmp_path / 'old-hub.db'
    schema = Path('../Stella-Plugins/plugins/agent-hub/backend/domain/schema.sql').read_text()
    schema = schema.replace('    agent_id TEXT,\n    access_mode TEXT,\n', '')
    with sqlite3.connect(hub_db) as db:
        db.executescript(schema)
        db.execute("INSERT INTO provider_configs(provider_config_id,provider_local_id,display_name,created_at,updated_at) VALUES ('old','codex-cli','Old','now','now')")
    monkeypatch.setattr('common.state_dir.agent_hub_db', lambda **_: hub_db)
    catalog = Path('../Stella-Plugins/catalog/official.json').resolve()
    result = run_desktop_bootstrap(data_dir=tmp_path / 'data', catalog_path=catalog)
    assert result['status'] == 'ok', result['failed']
    assert 'stella.agent-hub' in result['installed']
    with sqlite3.connect(hub_db) as db:
        assert db.execute("SELECT agent_id, access_mode FROM provider_configs WHERE provider_config_id='old'").fetchone() == ('codex', 'cli')


def test_package_store_never_copies_ignored_bytecode(tmp_path):
    source = _dirty_pkg(tmp_path)
    (source / 'standalone.pyc').write_bytes(b'cached bytecode')
    store = PackageStore(tmp_path / 'store')
    operation = store.stage(source)
    assert not (store.staging / operation.operation_id / 'standalone.pyc').exists()
