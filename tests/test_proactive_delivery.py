"""Proactive delivery uses one connected desktop, Telegram, or WeCom target."""

from types import SimpleNamespace

import pytest

from agent.scheduler import delivery
from agent.scheduler.dispatch import dispatch_notification
from agent.scheduler.automation_store import AutomationStore


def test_catalog_lists_only_connected_proactive_channels(monkeypatch):
    monkeypatch.setattr(delivery, "runtime_channel", lambda name: SimpleNamespace(
        mode="websocket", authenticated=True) if name == "wecom_bot" else None)
    monkeypatch.setattr(delivery, "desktop_client_connected", lambda: False)
    names = [row["channel_type"] for row in delivery.destination_catalog()]
    assert names == ["wecom_bot"]


def test_unconnected_catalog_is_empty(monkeypatch):
    monkeypatch.setattr(delivery, "runtime_channel", lambda _name: None)
    monkeypatch.setattr(delivery, "desktop_client_connected", lambda: False)
    assert delivery.destination_catalog() == []


def test_new_route_rejects_backup_and_legacy_channels():
    with pytest.raises(ValueError, match="备用渠道已移除"):
        delivery.normalize_notification_route({
            "primary": {"channel_type": "telegram", "receiver": "100"},
            "backup_enabled": True,
            "backup": {"channel_type": "desktop", "receiver": "client"},
        })
    with pytest.raises(ValueError, match="需要重新选择渠道"):
        delivery.normalize_notification_route({
            "primary": {"channel_type": "weixin", "receiver": "wx_user"},
        })


def test_saved_route_drops_backup_and_marks_legacy_primary():
    loaded = delivery.load_saved_route({
        "primary": {"channel_type": "web", "receiver": "session-1"},
        "backup_enabled": True,
        "backup": {"channel_type": "feishu", "receiver": "ou_old"},
    })
    assert loaded["needs_reselect"] is True
    assert loaded["primary"]["channel_type"] == "web"
    assert "backup" not in loaded
    assert "backup_enabled" not in loaded


def test_dispatch_does_not_send_backup_or_legacy_primary(tmp_path):
    store = AutomationStore(tmp_path / "scheduler" / "tasks.json", "agent-a")
    store.add_task({"id": "scheduled", "name": "Scheduled", "enabled": True,
                    "action": {"type": "send_message", "content": "Saved"}})
    job_id = store.claim_occurrence("scheduled", manual=True)
    sent = []
    route = {
        "primary": {"channel_type": "weixin", "receiver": "wx_user"},
        "backup_enabled": True,
        "backup": {"channel_type": "feishu", "receiver": "ou_backup"},
    }
    result = dispatch_notification(store, job_id, route, "Saved",
                                   channel_provider=lambda name: SimpleNamespace(
                                       send=lambda *_args: sent.append(name) or True))
    assert result.status == "failed"
    assert "重新选择" in result.error
    assert sent == []
    assert store.get_delivery(job_id, "backup") is None
