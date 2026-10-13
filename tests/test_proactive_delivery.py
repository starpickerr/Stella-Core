"""Proactive delivery uses one connected desktop, Telegram, or WeCom target."""

import asyncio
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


def test_telegram_proactive_send_needs_an_existing_chat_and_a_message_id():
    from channel.telegram.telegram_channel import TelegramChannel

    channel = TelegramChannel()
    channel._known_chats = set()
    channel._loop = None
    channel._bot = None
    with pytest.raises(ValueError, match="建立聊天"):
        channel.send_proactive("100", "hello")

    channel._known_chats.add("100")
    loop = asyncio.new_event_loop()
    import threading
    ready = threading.Event()

    def _run():
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()

    threading.Thread(target=_run, daemon=True).start()
    assert ready.wait(2)
    sent = {}

    async def send_message(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(message_id=42)

    channel._loop = loop
    channel._bot = SimpleNamespace(send_message=send_message)
    try:
        result = channel.send_proactive("100", "hello")
    finally:
        loop.call_soon_threadsafe(loop.stop)
    assert result["message_id"] == "42"
    assert sent["chat_id"] == "100"
    assert sent["text"] == "hello"


def test_wecom_proactive_send_waits_for_the_long_connection():
    from channel.wecom_bot.wecom_bot_channel import WecomBotChannel

    channel = WecomBotChannel()
    channel.mode = "webhook"
    channel._connected = False
    channel._known_chats = set()
    with pytest.raises(RuntimeError, match="长连接"):
        channel.send_proactive("chat-1", "hello")
    channel.mode = "websocket"
    channel._connected = True
    with pytest.raises(ValueError, match="建立会话"):
        channel.send_proactive("chat-1", "hello")
    channel._known_chats.add("chat-1")
    channel._send_and_wait = lambda payload: {"errcode": 0, "msgid": "wx-9"}
    assert channel.send_proactive("chat-1", "hello")["errcode"] == 0


def test_desktop_notification_waits_until_the_client_reports_the_banner(tmp_path):
    from agent.scheduler.desktop_notify import acknowledge_desktop_notification, claim_desktop_notifications

    store = AutomationStore(tmp_path / "scheduler" / "tasks.json", "agent-a")
    store.add_task({"id": "scheduled", "name": "Scheduled", "enabled": True,
                    "action": {"type": "send_message", "content": "Saved"}})
    job_id = store.claim_occurrence("scheduled", manual=True)
    route = {"primary": {"channel_type": "desktop", "receiver": "this-mac", "is_group": False}}
    result = dispatch_notification(store, job_id, route, "Saved", channel_provider=lambda _name: None)
    assert result.status == "waiting"
    assert store.get_delivery(job_id, "primary")["status"] == "waiting"
    claimed = claim_desktop_notifications()
    assert claimed[0]["body"] == "Saved"
    acknowledge_desktop_notification(store, job_id, False, "系统未允许通知")
    assert store.get_delivery(job_id, "primary")["status"] == "failed"
    assert "系统未允许通知" in store.get_delivery(job_id, "primary")["error"]
