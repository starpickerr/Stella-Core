"""Bounded notification delivery with durable platform acceptance records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger


@dataclass(frozen=True)
class DeliveryOutcome:
    status: str
    error: str = ""
    retryable: bool = False


def _log_delivery_outcome(delivery_id, leg, outcome: DeliveryOutcome) -> DeliveryOutcome:
    if outcome.status not in ("accepted", "waiting"):
        logger.warning(
            "[Scheduler] Delivery %s/%s → %s: %s",
            delivery_id, leg, outcome.status, outcome.error or "(no detail)",
        )
    return outcome


def _channel_for(channel_type):
    if channel_type == "weixin":
        from agent.scheduler.delivery import runtime_channel
        return runtime_channel("weixin")
    from channel.channel_factory import create_channel
    return create_channel(channel_type)


def _response_details(response):
    if not isinstance(response, dict):
        return {"accepted": response is not False}
    safe_keys = ("success", "ret", "errcode", "code", "message_id", "msg_id", "request_id")
    details = {key: response[key] for key in safe_keys if key in response and
               isinstance(response[key], (str, int, float, bool, type(None)))}
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("message_id"), str):
        details["message_id"] = data["message_id"]
    return details


def _one_delivery(store, delivery_id, leg, destination, content, *, agent_id, channel_provider):
    channel_type = destination["channel_type"]
    receiver = destination["receiver"]
    store.queue_delivery(delivery_id, leg, channel_type, receiver)
    decision = store.begin_delivery(delivery_id, leg, channel_type, receiver)
    if decision != "send":
        row = store.get_delivery(delivery_id, leg)
        return _log_delivery_outcome(delivery_id, leg, DeliveryOutcome(
            decision, row.get("error") or "" if row else "",
            bool(row and row.get("retryable") and row.get("attempts", 0) < 3)))

    if channel_type == "desktop":
        from agent.scheduler.desktop_notify import enqueue_desktop_notification
        enqueue_desktop_notification(delivery_id, receiver, content)
        error = "等待客户端确认通知"
        store.finish_delivery(delivery_id, leg, "waiting", error=error,
                              platform_response={"body": content})
        return DeliveryOutcome("waiting", error)
    channel = channel_provider(channel_type)
    if channel is None:
        error = f"{channel_type} is unavailable"
        store.finish_delivery(delivery_id, leg, "failed", error=error, retryable=True)
        return _log_delivery_outcome(delivery_id, leg, DeliveryOutcome("failed", error, retryable=True))
    if channel_type == "weixin":
        if getattr(channel, "login_status", "logged_in") != "logged_in":
            error = "Weixin login is required"
            store.finish_delivery(delivery_id, leg, "failed", error=error, retryable=True)
            return _log_delivery_outcome(delivery_id, leg, DeliveryOutcome("failed", error, retryable=True))
        tokens = getattr(channel, "_context_tokens", None)
        if tokens is not None and not tokens.get(receiver):
            error = "Weixin conversation context expired"
            store.finish_delivery(delivery_id, leg, "failed", error=error, retryable=True)
            return _log_delivery_outcome(delivery_id, leg, DeliveryOutcome("failed", error, retryable=True))

    context = Context(ContextType.TEXT, content)
    context["receiver"] = receiver
    context["isgroup"] = destination.get("is_group", False)
    context["session_id"] = destination.get("notify_session_id") or receiver
    context["channel_type"] = channel_type
    context["agent_id"] = agent_id
    context["scheduled_delivery"] = True
    if channel_type == "feishu":
        context["receive_id_type"] = destination.get("receive_id_type") or (
            "chat_id" if destination.get("is_group") else "open_id")
        context["msg"] = None
    if channel_type == "web":
        context["request_id"] = f"scheduled_{delivery_id}_{leg}"
        if hasattr(channel, "request_to_session"):
            channel.request_to_session[context["request_id"]] = receiver
    try:
        if channel_type in ("desktop", "telegram", "wecom_bot") and hasattr(channel, "send_proactive"):
            response = channel.send_proactive(receiver, content, destination.get("is_group", False))
            if isinstance(response, dict) and response.get("queued") and not response.get("shown"):
                error = response.get("error") or "等待客户端确认通知"
                store.finish_delivery(delivery_id, leg, "waiting", error=error, platform_response=response)
                return DeliveryOutcome("waiting", error)
        else:
            response = channel.send(Reply(ReplyType.TEXT, content), context)
        details = _response_details(response)
        if response is False or details.get("success") is False:
            error = "Channel rejected scheduled delivery"
            store.finish_delivery(delivery_id, leg, "failed", error=error,
                                  platform_response=details)
            return _log_delivery_outcome(delivery_id, leg, DeliveryOutcome("failed", error))
        store.finish_delivery(delivery_id, leg, "accepted", platform_response=details)
        return DeliveryOutcome("accepted")
    except requests.exceptions.ConnectTimeout as exc:
        error = str(exc)[:500]
        row = store.get_delivery(delivery_id, leg)
        retryable = row["attempts"] < 3
        store.finish_delivery(delivery_id, leg, "failed", error=error, retryable=retryable)
        return _log_delivery_outcome(delivery_id, leg, DeliveryOutcome("failed", error, retryable))
    except (requests.exceptions.Timeout, TimeoutError, requests.exceptions.ConnectionError,
            ConnectionError) as exc:
        error = str(exc)[:500]
        store.finish_delivery(delivery_id, leg, "unknown", error=error)
        return _log_delivery_outcome(delivery_id, leg, DeliveryOutcome("unknown", error))
    except Exception as exc:
        error = str(exc)[:500]
        if getattr(exc, "delivery_uncertain", False):
            status, retryable = "unknown", False
        elif channel_type == "weixin" and ("-14" in error or "context token expired" in error.lower()):
            status, retryable = "waiting", False
        else:
            status, retryable = "failed", False
        row = store.get_delivery(delivery_id, leg)
        retryable = retryable and row["attempts"] < 3
        store.finish_delivery(delivery_id, leg, status, error=error, retryable=retryable)
        return _log_delivery_outcome(delivery_id, leg, DeliveryOutcome(status, error, retryable))


def dispatch_notification(store, delivery_id, route, content, *, agent_id=None, expires_at=None,
                          now=None, channel_provider=None):
    """Send the saved primary once. A legacy or backup route fails in place."""
    from agent.scheduler.delivery import PROACTIVE, load_saved_route
    if not isinstance(route, dict) or not isinstance(route.get("primary"), dict):
        raise ValueError("A primary notification destination is required")
    loaded = load_saved_route(route)
    primary = loaded["primary"]
    if loaded["needs_reselect"] or primary.get("channel_type") not in PROACTIVE:
        channel_type = primary.get("channel_type") or ""
        receiver = primary.get("receiver") or ""
        store.queue_delivery(delivery_id, "primary", channel_type, receiver)
        error = "需要重新选择渠道"
        if store.begin_delivery(delivery_id, "primary", channel_type, receiver) == "send":
            store.finish_delivery(delivery_id, "primary", "failed", error=error)
        return _log_delivery_outcome(delivery_id, "primary", DeliveryOutcome("failed", error))
    store.queue_delivery(delivery_id, "primary", primary["channel_type"], primary["receiver"])
    recorded = store.get_delivery(delivery_id, "primary")
    if recorded and recorded["status"] == "accepted":
        return DeliveryOutcome("accepted")
    if recorded and recorded["status"] in ("unknown", "sending"):
        if recorded["status"] == "sending":
            store.begin_delivery(delivery_id, "primary", primary["channel_type"], primary["receiver"])
        return _log_delivery_outcome(
            delivery_id, "primary",
            DeliveryOutcome("unknown", recorded.get("error") or "Previous send outcome is unknown"),
        )
    instant = now or datetime.now(timezone.utc)
    if expires_at is not None and instant >= expires_at:
        store.expire_delivery(delivery_id, "primary", primary["channel_type"], primary["receiver"])
        return _log_delivery_outcome(
            delivery_id, "primary", DeliveryOutcome("expired", "Notification is past its useful time"),
        )
    provider = channel_provider or _channel_for
    result = _one_delivery(store, delivery_id, "primary", primary, content,
                           agent_id=agent_id, channel_provider=provider)
    return result


class _TestDeliveryStore:
    """Record one test attempt without adding a scheduled job or persistent outbox."""

    def __init__(self):
        self.rows = {}

    def queue_delivery(self, _delivery_id, leg, channel_type, receiver):
        self.rows.setdefault(leg, {"status": "pending", "attempts": 0,
                                   "channel_type": channel_type, "receiver": receiver})

    def get_delivery(self, _delivery_id, leg):
        return self.rows.get(leg)

    def begin_delivery(self, _delivery_id, leg, _channel_type, _receiver):
        row = self.rows[leg]
        row.update(status="sending", attempts=row["attempts"] + 1)
        return "send"

    def finish_delivery(self, _delivery_id, leg, status, *, error="", retryable=False,
                        platform_response=None):
        self.rows[leg].update(status=status, error=error, retryable=retryable,
                              platform_response=platform_response or {})


def dispatch_test_notification(route, *, agent_id=None, channel_provider=None):
    """Send a fixed test message to the selected primary destination only."""
    store = _TestDeliveryStore()
    result = dispatch_notification(store, "test", {"primary": route["primary"],
                                                    "backup_enabled": False},
                                   "Stella 测试通知", agent_id=agent_id,
                                   channel_provider=channel_provider)
    return {"delivery_status": result.status, "error": result.error,
            "platform_response": store.rows.get("primary", {}).get("platform_response", {})}
