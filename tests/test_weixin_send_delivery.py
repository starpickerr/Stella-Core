from types import SimpleNamespace

import pytest
import requests

from bridge.reply import Reply, ReplyType
from channel.weixin.weixin_api import WeixinApi
from channel.weixin.weixin_channel import WeixinChannel


@pytest.mark.parametrize("response", [{}, {"ret": 0}, {"errcode": 0}])
def test_weixin_success_response_sends_one_reply(monkeypatch, response):
    channel = WeixinChannel()
    calls = []

    def send_text(receiver, text, context_token):
        calls.append((receiver, text, context_token))
        return response

    monkeypatch.setattr(channel, "api", SimpleNamespace(send_text=send_text))
    monkeypatch.setattr(channel, "_context_tokens", {"user": "context-token"})

    channel._send(Reply(ReplyType.TEXT, "hello"), {"receiver": "user"})

    assert calls == [("user", "hello", "context-token")]


def test_weixin_explicit_send_failure_is_not_resent_with_new_client_id(monkeypatch):
    channel = WeixinChannel()
    calls = []

    def send_text(*args):
        calls.append(args)
        return {"ret": -2, "errmsg": "prepare failed"}

    monkeypatch.setattr(channel, "api", SimpleNamespace(send_text=send_text))
    monkeypatch.setattr(channel, "_context_tokens", {"user": "context-token"})

    channel._send(Reply(ReplyType.TEXT, "hello"), {"receiver": "user"})

    assert len(calls) == 1


def test_weixin_transport_retry_reuses_client_id(monkeypatch):
    payloads = []

    def post(_url, *, json, **_kwargs):
        payloads.append(json["msg"]["client_id"])
        if len(payloads) == 1:
            raise requests.exceptions.SSLError("connection closed")
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr("channel.weixin.weixin_api.time.sleep", lambda _: None)

    assert WeixinApi("https://example.invalid", "fake").send_text("user", "hello", "token") == {}
    assert len(payloads) == 2
    assert payloads[0] == payloads[1]
