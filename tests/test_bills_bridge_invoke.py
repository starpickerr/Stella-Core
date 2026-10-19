"""Production Bridge invoke path for the Bills page (host-bound identity)."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins.bridge import BridgeRegistry
from core.plugins.page_host import PluginPageHost


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setenv("STELLA_BILLS_PLUGIN", "1")
    root = Path("stella-plugins-workspace/plugins/bills")
    if not root.is_dir():
        root = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "bills"
    monkeypatch.setenv("STELLA_BILLS_PLUGIN_ROOT", str(root.resolve()))
    monkeypatch.setenv("STELLA_REPO_ROOT", str(Path.cwd()))
    from core.services import bills_facade, bills_gateway

    monkeypatch.setattr(bills_facade, "_db_path", lambda: tmp_path / "bills.db")
    yield PluginPageHost(bridges=BridgeRegistry()), root.resolve()
    bills_gateway.shutdown_bills_session()


def test_open_page_binds_bridge_and_resolves_bills_html(host):
    page_host, root = host
    opened = page_host.open_page(
        plugin_id="stella.bills",
        page_id="bills.main",
        user_id="u1",
        instance_id="i1",
        generation=1,
        package_root=root,
    )
    assert opened["pluginId"] == "stella.bills"
    assert opened["pageId"] == "bills.main"
    assert opened["channelNonce"]
    assert Path(opened["resourcePath"]).name == "index.html"
    assert Path(opened["resourcePath"]).is_relative_to(root)


def test_bridge_invoke_creates_ledger_and_rejects_forged_identity(host):
    page_host, root = host
    opened = page_host.open_page(
        plugin_id="stella.bills", page_id="bills.main",
        user_id="u1", instance_id="i1", generation=2, package_root=root,
    )
    created = page_host.invoke(
        channel_nonce=opened["channelNonce"],
        plugin_id="stella.bills",
        page_id="bills.main",
        generation=2,
        method="create_ledger",
        input={
            "name": "午餐",
            "category": "消费",
            "entry_type": "expense",
            "amount_minor": 1250,
            "occurred_at": "2026-10-20T12:00:00+08:00",
        },
    )
    assert created["amount_minor"] == 1250
    rows = page_host.invoke(
        channel_nonce=opened["channelNonce"],
        plugin_id="stella.bills",
        page_id="bills.main",
        generation=2,
        method="list_ledger",
        input={"year": 2026, "month": 10},
    )
    assert any(row.get("name") == "午餐" and row.get("amount_minor") == 1250 for row in rows)
    with pytest.raises(PermissionError):
        page_host.invoke(
            channel_nonce=opened["channelNonce"],
            plugin_id="stella.bills",
            page_id="bills.main",
            generation=99,
            method="list_ledger",
            input={"year": 2026, "month": 10},
        )


def test_revoke_generation_blocks_further_invokes(host):
    page_host, root = host
    opened = page_host.open_page(
        plugin_id="stella.bills", page_id="bills.main",
        user_id="u1", instance_id="i1", generation=3, package_root=root,
    )
    page_host.bridges.revoke_generation("stella.bills", 3)
    with pytest.raises(PermissionError):
        page_host.invoke(
            channel_nonce=opened["channelNonce"],
            plugin_id="stella.bills",
            page_id="bills.main",
            generation=3,
            method="list_ledger",
            input={"year": 2026, "month": 10},
        )
