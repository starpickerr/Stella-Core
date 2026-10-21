"""MCP transport waits obey the same budget as their original caller."""
import io
import json
import threading
import time
from unittest.mock import Mock, patch

import pytest

from agent.tools.mcp.mcp_client import McpClient
from core.plugins.caller import invocation_budget


def client():
    value = McpClient({'name': 'budget', 'type': 'stdio', 'timeout': 30})
    value._initialized = True
    value._proc = Mock(stdin=io.StringIO())
    return value


def reply(identity, text):
    return json.dumps({'id': identity, 'result': {'content': [{'type': 'text', 'text': text}]}})


def test_stdio_deadline_cancels_wait_and_rejects_late_result():
    value = client()
    timer = threading.Timer(.35, lambda: value._read_queue.put(reply(1, 'late')))
    timer.start()
    started = time.monotonic()
    try:
        with invocation_budget(60), pytest.raises((PermissionError, TimeoutError)):
            value.call_tool('slow', {})
        assert time.monotonic() - started < .25
    finally:
        timer.join()
    sent = [json.loads(line) for line in value._proc.stdin.getvalue().splitlines()]
    assert sent[1]['method'] == 'notifications/cancelled'
    value._read_queue.put(reply(2, 'fresh'))
    assert value.call_tool('next', {}) == 'fresh'


def test_deadline_while_waiting_for_shared_connection_does_not_dispatch():
    value = client()
    value._call_lock.acquire()
    timer = threading.Timer(.35, value._call_lock.release)
    timer.start()
    value._read_queue.put(reply(1, 'late'))
    try:
        with invocation_budget(60), pytest.raises((PermissionError, TimeoutError)):
            value.call_tool('queued', {})
        assert value._proc.stdin.getvalue() == ''
    finally:
        timer.join()


def test_http_socket_timeout_is_limited_by_caller_budget():
    value = McpClient({'name': 'budget', 'type': 'streamable-http'})
    value._initialized = True
    value._http_url = 'https://example.test/mcp'

    class Response(io.BytesIO):
        headers = {'Content-Type': 'application/json'}
        status = 200

    response = Response(reply(1, 'fresh').encode())
    with invocation_budget(100), patch('agent.tools.mcp.mcp_client.urllib.request.urlopen', return_value=response) as request:
        assert value.call_tool('read', {}) == 'fresh'
        assert 0 < request.call_args.kwargs['timeout'] <= .1
