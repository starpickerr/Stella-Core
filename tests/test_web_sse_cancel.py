"""SSE teardown after a user cancel.

A cancel only takes effect at the agent's next checkpoint, so the run keeps
emitting events for a while after Stop is pressed. Closing the stream on a
blind timer strands in-flight tool bubbles and makes the client reconnect
onto a reclaimed queue, which surfaces as a bogus "failed to send" bubble.
"""

import json
import threading
import time
from queue import Queue
from types import SimpleNamespace

from channel.web import web_channel

# @singleton replaces the class with a factory, so reach the class through the
# decorator's closure rather than constructing a real channel.
WebChannel = dict(zip(
    web_channel.WebChannel.__code__.co_freevars,
    (cell.cell_contents for cell in web_channel.WebChannel.__closure__),
))["cls"]


def _fake_channel():
    """Minimal stand-in exposing only what stream_response touches."""
    channel = SimpleNamespace(
        sse_queues={},
        sse_last_active={},
        request_to_session={},
        request_to_agent={},
    )
    channel._drop_sse_request = lambda rid: WebChannel._drop_sse_request(channel, rid)
    return channel


def _events(chunks):
    """Parse SSE payloads, skipping keepalive comments."""
    out = []
    for chunk in chunks:
        text = chunk.decode("utf-8")
        for line in text.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def test_events_after_cancel_still_reach_the_client():
    channel = _fake_channel()
    request_id = "req-1"
    q = Queue()
    channel.sse_queues[request_id] = q
    q.put({"type": "cancelled", "content": "已中止"})

    def late_producer():
        # Longer than the old 3s post-cancel tail: the tool the agent was
        # already inside finishes, then the partial reply lands.
        time.sleep(4)
        q.put({"type": "tool_end", "tool_call_id": "t1", "status": "success"})
        q.put({"type": "done", "content": "partial answer"})

    threading.Thread(target=late_producer, daemon=True).start()
    events = _events(WebChannel.stream_response(channel, request_id))

    types = [e["type"] for e in events]
    assert types == ["cancelled", "tool_end", "done"]
    # Queue reclaimed only once the run actually finished.
    assert request_id not in channel.sse_queues


def test_unfinished_run_does_not_hold_the_stream_forever():
    """No trailing "done" (worker died): close instead of leaking the stream."""
    channel = _fake_channel()
    request_id = "req-2"
    channel.sse_queues[request_id] = Queue()
    channel.sse_queues[request_id].put({"type": "cancelled", "content": "已中止"})

    generator = WebChannel.stream_response(channel, request_id)
    assert _events([next(generator)]) == [{"type": "cancelled", "content": "已中止"}]
    generator.close()
