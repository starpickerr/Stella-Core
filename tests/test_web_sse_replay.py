import json
import threading
from types import SimpleNamespace

from channel.web import web_channel


WebChannel = dict(zip(
    web_channel.WebChannel.__code__.co_freevars,
    (cell.cell_contents for cell in web_channel.WebChannel.__closure__),
))["cls"]


def _channel(max_events=5000, max_bytes=4 * 1024 * 1024):
    channel = SimpleNamespace(
        sse_streams={},
        _sse_streams_lock=threading.RLock(),
        request_to_session={},
        request_to_agent={},
        SSE_REPLAY_MAX_EVENTS=max_events,
        SSE_REPLAY_MAX_BYTES=max_bytes,
    )
    channel._publish_sse_event = lambda rid, event: WebChannel._publish_sse_event(
        channel, rid, event
    )
    return channel


def _add_stream(channel, request_id):
    channel.sse_streams[request_id] = web_channel.SSEStreamState()


def _events(chunks):
    events, ids = [], []
    for chunk in chunks:
        for line in chunk.decode("utf-8").splitlines():
            if line.startswith("id: "):
                ids.append(int(line[4:]))
            elif line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return ids, events


def test_reconnect_replays_only_events_after_cursor():
    channel = _channel()
    _add_stream(channel, "req")
    for content in ("a", "b", "c"):
        channel._publish_sse_event("req", {"type": "delta", "content": content})
    channel._publish_sse_event("req", {"type": "done", "content": "abc"})
    channel._publish_sse_event("req", {"type": "stream_end"})

    ids, events = _events(WebChannel.stream_response(channel, "req", after_seq=2))

    assert ids == [3, 4, 5]
    assert [event["seq"] for event in events] == [3, 4, 5]
    assert [event["type"] for event in events] == ["delta", "done", "stream_end"]


def test_delivery_interruption_does_not_remove_event_from_log():
    channel = _channel()
    _add_stream(channel, "req")
    channel._publish_sse_event("req", {"type": "delta", "content": "first"})
    channel._publish_sse_event("req", {"type": "delta", "content": "second"})

    first_connection = WebChannel.stream_response(channel, "req")
    ids, _ = _events([next(first_connection)])
    assert ids == [1]
    first_connection.close()

    channel._publish_sse_event("req", {"type": "done", "content": "firstsecond"})
    channel._publish_sse_event("req", {"type": "stream_end"})
    ids, events = _events(WebChannel.stream_response(channel, "req", after_seq=0))

    assert ids == [1, 2, 3, 4]
    assert [event["seq"] for event in events] == [1, 2, 3, 4]


def test_done_and_voice_attachment_are_replayable_until_stream_end():
    channel = _channel()
    _add_stream(channel, "req")
    channel._publish_sse_event("req", {"type": "done", "content": "answer"})
    channel._publish_sse_event("req", {"type": "voice_attach", "url": "/audio.mp3"})
    channel._publish_sse_event("req", {"type": "stream_end"})

    _, events = _events(WebChannel.stream_response(channel, "req", after_seq=1))

    assert [event["type"] for event in events] == ["voice_attach", "stream_end"]


def test_requests_have_independent_sequences_and_logs():
    channel = _channel()
    _add_stream(channel, "a")
    _add_stream(channel, "b")
    channel._publish_sse_event("a", {"type": "delta", "content": "A"})
    channel._publish_sse_event("b", {"type": "delta", "content": "B"})
    channel._publish_sse_event("a", {"type": "stream_end"})
    channel._publish_sse_event("b", {"type": "stream_end"})

    _, a_events = _events(WebChannel.stream_response(channel, "a"))
    _, b_events = _events(WebChannel.stream_response(channel, "b"))

    assert [event.get("content") for event in a_events if "content" in event] == ["A"]
    assert [event.get("content") for event in b_events if "content" in event] == ["B"]
    assert a_events[0]["seq"] == b_events[0]["seq"] == 1


def test_expired_cursor_requires_resync_when_count_limit_evicts_events():
    channel = _channel(max_events=2)
    _add_stream(channel, "req")
    for content in ("a", "b", "c"):
        channel._publish_sse_event("req", {"type": "delta", "content": content})

    ids, events = _events(WebChannel.stream_response(channel, "req", after_seq=0))

    assert ids == []
    assert events == [{
        "type": "resync_required",
        "reason": "event_cursor_expired",
        "after_seq": 0,
        "first_available_seq": 2,
    }]


def test_byte_limit_also_evicts_old_events():
    channel = _channel(max_events=100, max_bytes=160)
    _add_stream(channel, "req")
    for _ in range(4):
        channel._publish_sse_event("req", {"type": "delta", "content": "x" * 80})

    state = channel.sse_streams["req"]
    assert len(state.events) == 1
    assert state.events[0][0]["seq"] == 4
