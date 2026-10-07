from channel.weixin.weixin_channel import _poll_failure_delay
from channel.weixin.weixin_api import WeixinApi
from types import SimpleNamespace
import requests


def test_weixin_poll_failures_back_off_and_cap():
    assert [_poll_failure_delay(count) for count in (1, 2, 3, 5, 6, 9, 12, 15)] == [
        2, 2, 30, 30, 60, 120, 240, 300,
    ]


def test_poll_falls_back_to_direct_https_after_proxy_failure(monkeypatch):
    calls = []
    def proxy_post(*args, **kwargs):
        calls.append("proxy")
        raise requests.exceptions.ProxyError("proxy disconnected")
    class Direct:
        trust_env = False
        def post(self, *args, **kwargs):
            calls.append("direct")
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {"ret": 0, "msgs": []})
    monkeypatch.setattr(requests, "post", proxy_post)
    monkeypatch.setattr(requests, "Session", Direct)
    monkeypatch.setattr(requests.utils, "get_environ_proxies", lambda _: {"https": "proxy"})
    api = WeixinApi(token="test")
    assert api.get_updates()["ret"] == 0
    assert api.get_updates()["ret"] == 0
    assert calls == ["proxy", "direct", "direct"]
