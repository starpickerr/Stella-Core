from common import const
from bridge.agent_event_handler import AgentEventHandler


class _FakeChannel:
    def __init__(self):
        self.sent = []

    def _send(self, reply, context):
        self.sent.append(reply.content)


class _FakeContext:
    def __init__(self, kwargs):
        self.kwargs = kwargs

    def get(self, key, default=None):
        return default


def _context(channel_type, channel):
    return _FakeContext({"channel": channel, "channel_type": channel_type})


def test_weixin_does_not_forward_pre_tool_thinking_as_reply():
    channel = _FakeChannel()
    handler = AgentEventHandler(_context(const.WEIXIN, channel))
    handler.handle_event({"type": "turn_start", "data": {"turn": 1}})
    handler.handle_event({"type": "message_update", "data": {"delta": "I should call a tool..."}})
    handler.handle_event({
        "type": "message_end",
        "data": {"tool_calls": [{"id": "call_1", "name": "search"}], "content": "I should call a tool..."},
    })
    assert channel.sent == []


def test_web_still_forwards_pre_tool_commentary():
    channel = _FakeChannel()
    handler = AgentEventHandler(_context("web", channel))
    handler.handle_event({"type": "turn_start", "data": {"turn": 1}})
    handler.handle_event({"type": "message_update", "data": {"delta": "Looking that up."}})
    handler.handle_event({
        "type": "message_end",
        "data": {"tool_calls": [{"id": "call_1", "name": "search"}], "content": "Looking that up."},
    })
    assert channel.sent == ["Looking that up."]
