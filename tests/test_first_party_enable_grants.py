"""Desktop enable / first-boot must issue required scoped grants for managed plugins."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins.authz import PluginAuthorizationStore
from core.plugins.caller import user_grant_ref
from core.plugins.first_party_grants import issue_required_grants_for_enabled_plugin
from core.plugins.lifecycle import PluginManager
from core.plugins.management import ManagementStore
from core.plugins.package_ops import PackageStore


BILLS = Path("stella-plugins-workspace/plugins/bills")
if not BILLS.is_dir():
    BILLS = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "bills"


@pytest.fixture
def bills_root() -> Path:
    assert BILLS.is_dir(), f"bills plugin missing: {BILLS}"
    return BILLS


def test_issue_required_grants_covers_write_methods(bills_root, tmp_path, monkeypatch):
    from core.plugins import management

    store = ManagementStore(tmp_path / "packages")
    packages = PackageStore(store.root)
    op = packages.stage(bills_root)
    packages.inspect(op.operation_id)
    packages.prepare(op.operation_id)
    packages.commit(op.operation_id)
    monkeypatch.setattr(management, "default_store", lambda: store)

    authz = PluginAuthorizationStore()
    issued = issue_required_grants_for_enabled_plugin(
        plugin_id="stella.bills",
        user_id="local-default",
        package_root=bills_root,
        authz=authz,
    )
    assert issued
    parent = user_grant_ref("bills-default-grant", "local-default")
    authz.check_scoped(
        grant_ref=parent,
        plugin_id="stella.bills",
        user_id="local-default",
        consumer_plugin_id="stella.bills",
        method="create_ledger",
        required_capabilities=["bills.write"],
        resources=[{"kind": "user", "id": "local-default"}],
        purpose="interactive",
    )
    authz.check_scoped(
        grant_ref=parent,
        plugin_id="stella.bills",
        user_id="local-default",
        consumer_plugin_id="stella.bills",
        method="list_ledger",
        required_capabilities=["bills.read"],
        resources=[{"kind": "user", "id": "local-default"}],
        purpose="background",
    )
    # Worker start still must not mint a legacy full grant.
    assert authz.get(parent) is None


def test_complete_install_issues_scoped_grants(bills_root, tmp_path, monkeypatch):
    import json

    from core.plugins import first_party_grants, management
    from core.plugins.package_ops import _sha256_tree

    store = ManagementStore(tmp_path / "packages")
    monkeypatch.setattr(management, "default_store", lambda: store)
    authz = PluginAuthorizationStore()
    monkeypatch.setattr(first_party_grants, "DEFAULT_AUTHZ", authz)

    manifest = json.loads((bills_root / "plugin.json").read_text(encoding="utf-8"))
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "coreApi": "1.0.0",
                "plugins": [
                    {
                        "pluginId": manifest["id"],
                        "hostApi": manifest["hostApi"],
                        "version": manifest["version"],
                        "path": str(bills_root.resolve()),
                        "sha256": _sha256_tree(bills_root),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manager = PluginManager(store, catalog_path=catalog)
    manager.install(
        "stella.bills",
        user_id="local-default",
        data_handle={"dbPath": str(tmp_path / "bills.sqlite"), "namespace": "stella.bills"},
    )
    parent = user_grant_ref("bills-default-grant", "local-default")
    authz.check_scoped(
        grant_ref=parent,
        plugin_id="stella.bills",
        user_id="local-default",
        consumer_plugin_id="stella.bills",
        method="create_ledger",
        required_capabilities=["bills.write"],
        resources=[{"kind": "user", "id": "local-default"}],
        purpose="interactive",
    )


def test_reenable_issues_scoped_grants(bills_root, tmp_path, monkeypatch):
    from core.plugins import management
    from core.plugins import first_party_grants

    store = ManagementStore(tmp_path / "packages")
    packages = PackageStore(store.root)
    op = packages.stage(bills_root)
    packages.inspect(op.operation_id)
    packages.prepare(op.operation_id)
    packages.commit(op.operation_id)
    store.set_intent("stella.bills", "local-default", "disabled")
    monkeypatch.setattr(management, "default_store", lambda: store)
    authz = PluginAuthorizationStore()
    monkeypatch.setattr(first_party_grants, "DEFAULT_AUTHZ", authz)

    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"coreApi":"1.0.0","plugins":[]}', encoding="utf-8")
    manager = PluginManager(store, catalog_path=catalog)
    manager.set_intent("stella.bills", "local-default", "enabled")
    parent = user_grant_ref("bills-default-grant", "local-default")
    authz.check_scoped(
        grant_ref=parent,
        plugin_id="stella.bills",
        user_id="local-default",
        consumer_plugin_id="stella.bills",
        method="create_ledger",
        required_capabilities=["bills.write"],
        resources=[{"kind": "user", "id": "local-default"}],
        purpose="interactive",
    )
