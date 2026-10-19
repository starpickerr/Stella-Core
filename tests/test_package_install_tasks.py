"""Install the Tasks workspace package via the local package transaction."""

from __future__ import annotations

from pathlib import Path

from core.plugins.host import PluginSession
from core.plugins.package_ops import PackageStage, PackageStore
from core.plugins.runtime_hub import DEFAULT_REGISTRY


def test_commit_tasks_package_and_invoke_service(tmp_path):
    store = PackageStore(tmp_path / "pkg")
    op = store.stage(Path("stella-plugins-workspace/plugins/tasks"))
    op = store.inspect(op.operation_id)
    op = store.prepare(op.operation_id)
    op = store.commit(op.operation_id)
    assert op.stage == PackageStage.COMMITTED
    current = store.current_package("stella.tasks")
    assert current is not None
    session = PluginSession(
        Path(current["path"]),
        source_label="local-cache",
        registry=DEFAULT_REGISTRY,
    )
    try:
        started = session.start()
        assert started["initialize"]["pluginId"] == "stella.tasks"
        listed = session.invoke(
            "list_todos",
            {"_dataHandle": {"dbPath": str(tmp_path / "todos.db")}},
        )
        assert listed["status"] == "succeeded"
        assert listed["value"] == []
    finally:
        session.dispose()


def test_tasks_migration_entry_applies_and_verifies(tmp_path):
    import importlib.util

    path = Path("stella-plugins-workspace/plugins/tasks/backend/migrate.py").resolve()
    spec = importlib.util.spec_from_file_location("stella_tasks_migrate_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handle = {"dbPath": str(tmp_path / "todos.db")}
    assert module.apply("m1", handle)["applied"] is True
    verified = module.verify("m1", handle)
    assert verified["verified"] is True and verified["missingTables"] == []


def test_official_catalog_digest_matches_tasks_package():
    import json

    from core.plugins.distribution import verify_package_digest

    catalog = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "catalog" / "official.json"
    package = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "tasks"
    if not catalog.is_file() or not package.is_dir():
        import pytest

        pytest.skip("Stella-Plugins checkout not present")
    entry = next(e for e in json.loads(catalog.read_text())["plugins"] if e["pluginId"] == "stella.tasks")
    assert verify_package_digest(package, entry["sha256"])
