"""R05: revoked grant blocks further writes on frozen runner + installed package."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.plugins.authz import PluginAuthorizationStore
from core.plugins.distribution import fetch_and_install_from_catalog
from core.plugins.host import PluginSession, resolve_runner_command
from core.plugins.package_ops import PackageStore
from core.plugins.registry import PluginRegistry

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO.parent / "Stella-Plugins" / "catalog" / "official.json"
BACKEND = (
    REPO
    / "desktop"
    / "release"
    / "mac-arm64"
    / "Stella.app"
    / "Contents"
    / "Resources"
    / "backend"
    / "stella-backend"
    / "stella-backend"
)


@pytest.mark.skipif(not BACKEND.is_file(), reason="frozen Stella.app backend missing")
@pytest.mark.skipif(not CATALOG.is_file(), reason="Stella-Plugins catalog missing")
def test_revoked_grant_blocks_bills_write_on_frozen_runner(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    store = PackageStore(tmp_path / "plugin-packages")
    installed = fetch_and_install_from_catalog(
        catalog_path=CATALOG,
        plugin_id="stella.bills",
        package_store=store,
    )
    assert installed["status"] == "installed"
    root = Path(store.current_package("stella.bills")["path"])
    runner = resolve_runner_command(frozen=True, executable=str(BACKEND), environ={})
    authz = PluginAuthorizationStore()
    user = "r05-user"
    grant = "bills-r05"
    authz.issue(
        grant_ref=grant,
        plugin_id="stella.bills",
        user_id=user,
        capabilities=["bills.read", "bills.write", "plugin.invoke"],
        purposes=["interactive", "any"],
    )
    session = PluginSession(
        root,
        source_label="r05",
        registry=PluginRegistry(),
        user_id=user,
        runner_command=runner,
        authz=authz,
    )
    db = tmp_path / "bills.db"
    try:
        session.start()

        def create(key: str, name: str):
            return session.invoke_contract(
                contract="stella.bills@1",
                method="create_ledger",
                input_payload={
                    "name": name,
                    "category": "消费",
                    "entry_type": "expense",
                    "amount_minor": 100,
                    "occurred_at": "2026-08-02T12:30:00+08:00",
                },
                origin="system",
                grant_ref=grant,
                permissions=("bills.write",),
                purpose="interactive",
                idempotency_key=key,
                data_handle={"dbPath": str(db), "namespace": "stella.bills"},
            )

        assert create("k1", "a")["status"] == "succeeded"
        authz.revoke(grant)
        with pytest.raises(PermissionError, match="revoked"):
            create("k2", "b")
    finally:
        session.dispose()
