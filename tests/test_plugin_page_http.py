"""Desktop HTTP open/content/invoke for restricted plugin pages."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("STELLA_BILLS_PLUGIN", "1")
    root = Path("stella-plugins-workspace/plugins/bills")
    if not root.is_dir():
        root = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "bills"
    monkeypatch.setenv("STELLA_BILLS_PLUGIN_ROOT", str(root.resolve()))
    monkeypatch.setenv("STELLA_REPO_ROOT", str(Path.cwd()))
    from channel.desktop import desktop_channel as channel
    from core.services import bills_facade, bills_gateway

    monkeypatch.setattr(bills_facade, "_db_path", lambda: tmp_path / "bills.db")
    channel._PAGE_HOST = None
    channel._PAGE_CONTENT.clear()
    monkeypatch.setattr(channel, "_require_auth", lambda: None)
    monkeypatch.setattr(channel, "_plugin_user", lambda: "u-page")
    monkeypatch.setattr(channel.web, "header", lambda *a, **k: None)
    yield channel
    bills_gateway.shutdown_bills_session()
    channel._PAGE_HOST = None
    channel._PAGE_CONTENT.clear()


def test_open_content_and_bridge_invoke_roundtrip(api, monkeypatch):
    monkeypatch.setattr(api.web, "data", lambda: json.dumps({
        "pluginId": "stella.bills", "pageId": "bills.main", "generation": 1,
    }).encode())
    opened = json.loads(api.PluginPageOpenHandler().POST())
    assert opened["status"] == "ok"
    result = opened["result"]
    assert result["channelNonce"] and "contentUrl" in result

    monkeypatch.setattr(api.web, "input", lambda **kwargs: type("P", (), {"nonce": result["channelNonce"], "file": ""})())
    html = api.PluginPageContentHandler().GET("stella.bills", "bills.main")
    assert "stella.bills" in html and "记一笔" in html

    monkeypatch.setattr(api.web, "data", lambda: json.dumps({
        "channelNonce": result["channelNonce"],
        "pluginId": "stella.bills",
        "pageId": "bills.main",
        "generation": 1,
        "method": "create_ledger",
        "input": {
            "name": "咖啡",
            "category": "消费",
            "entry_type": "expense",
            "amount_minor": 1800,
            "occurred_at": "2026-10-20T09:00:00+08:00",
        },
    }).encode())
    created = json.loads(api.PluginBridgeInvokeHandler().POST())
    assert created["status"] == "ok" and created["value"]["amount_minor"] == 1800
