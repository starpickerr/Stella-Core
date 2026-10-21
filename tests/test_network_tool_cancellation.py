"""Stopping a run releases blocking browser, MCP, and Web tool calls."""
import io
import json
import queue
import threading
import time
import pytest
from unittest.mock import Mock, patch

from agent.tools.browser.browser_service import BrowserCancelledError, BrowserService
from agent.tools.mcp.mcp_client import McpClient, McpCancelledError
from agent.tools.web_fetch.web_fetch import WebFetch
from agent.tools.web_search.web_search import WebSearch


def test_browser_waiter_returns_on_cancel_without_running_queued_action():
    service = object.__new__(BrowserService)
    service._request_local = threading.local()
    service._task_queue = queue.Queue()
    service._alive = True
    service._needs_restart = False
    service._start_thread = lambda: None
    service._reset_idle_timer = lambda: None
    event = threading.Event()
    outcome = []

    def invoke():
        with service.cancel_scope(event):
            try:
                service.navigate("https://example.com")
            except BrowserCancelledError:
                outcome.append("cancelled")

    worker = threading.Thread(target=invoke, daemon=True)
    worker.start()
    deadline = time.monotonic() + 1
    while service._task_queue.empty() and time.monotonic() < deadline:
        time.sleep(0.01)
    queued = service._task_queue.get_nowait()
    assert queued[1][1] == 5000
    event.set()
    worker.join(1)
    assert not worker.is_alive() and outcome == ["cancelled"]
    assert queued[4] is event


def test_mcp_stdio_cancel_sends_notification_and_next_call_uses_new_request_id():
    client = McpClient({"name": "fake", "type": "stdio", "timeout": 30})
    client._initialized = True
    output = io.StringIO()
    client._proc = Mock(stdin=output)
    event = threading.Event()
    results = []
    def cancelled_call():
        try:
            client.call_tool("slow", {}, cancel_event=event)
        except McpCancelledError as exc:
            results.append(str(exc))
    worker = threading.Thread(target=cancelled_call, daemon=True)
    worker.start()
    deadline = time.monotonic() + 1
    while not output.getvalue() and time.monotonic() < deadline:
        time.sleep(0.01)
    event.set()
    worker.join(1)
    assert not worker.is_alive() and "cancelled" in results[0]
    sent = [json.loads(line) for line in output.getvalue().splitlines()]
    assert sent[1]["method"] == "notifications/cancelled"
    assert sent[1]["params"]["requestId"] == sent[0]["id"]

    client._read_queue.put(json.dumps({"id": sent[0]["id"], "result": {"content": [{"type": "text", "text": "stale"}]}}))
    client._read_queue.put(json.dumps({"id": sent[0]["id"] + 1, "result": {"content": [{"type": "text", "text": "fresh"}]}}))
    assert client.call_tool("next", {}) == "fresh"


def test_mcp_http_cancel_uses_bounded_socket_wait_and_closes_response():
    client = McpClient({"name": "fake", "type": "streamable-http"})
    client._initialized = True
    client._http_url = "https://example.com/mcp"
    event = threading.Event()

    class Response(io.BytesIO):
        headers = {"Content-Type": "application/json"}
        status = 200

        def read(self, *args):
            event.set()
            return super().read(*args)

    response = Response(b'{"jsonrpc":"2.0","id":1,"result":{"content":[]}}')
    with patch.object(client, '_open_remote', return_value=response) as open_request:
        with pytest.raises(McpCancelledError, match='cancelled'):
            client.call_tool("slow", {}, cancel_event=event)
    assert open_request.call_args.kwargs["timeout"] == 5
    assert response.closed


def test_web_fetch_cancelled_download_removes_partial_file(tmp_path):
    tool = WebFetch({"cwd": str(tmp_path)})
    event = threading.Event()
    tool.cancel_event = event
    response = Mock()
    response.is_redirect = response.is_permanent_redirect = False
    response.headers = {"Content-Length": "6"}
    response.iter_content = lambda chunk_size: _chunks_then_cancel(event)
    with patch("agent.tools.web_fetch.web_fetch.requests.get", return_value=response) as request:
        result = tool.execute({"url": "https://example.com/file.pdf"})
    assert result.status == "error" and "cancelled" in result.result
    assert request.call_args.kwargs["timeout"] == 5
    assert list((tmp_path / "tmp").iterdir()) == []
    response.close.assert_called()


def _chunks_then_cancel(event):
    yield b"abc"
    event.set()
    yield b"def"


def test_web_search_cancelled_response_is_closed():
    tool = WebSearch()
    event = threading.Event()
    tool.cancel_event = event
    response = Mock()

    def post(*args, **kwargs):
        assert kwargs["timeout"] == 5
        event.set()
        return response

    with patch("agent.tools.web_search.web_search.configured_providers", return_value=["bocha"]), \
         patch("agent.tools.web_search.web_search._get_api_key", return_value="fake"), \
         patch("agent.tools.web_search.web_search.requests.post", side_effect=post):
        result = tool.execute({"query": "test"})
    assert result.status == "error" and "cancelled" in result.result
    response.close.assert_called_once()
