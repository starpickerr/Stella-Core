"""MCP transport waits obey the same budget as their original caller."""
import io
import json
import threading
import time
from unittest.mock import Mock, patch

import pytest

from agent.tools.mcp.mcp_client import McpClient
from core.plugins.caller import invocation_budget
from core.plugins.cancellation import cancellation_scope
from agent.tools.mcp.mcp_client import McpCancelledError


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
    with invocation_budget(100), patch.object(value, '_open_remote', return_value=response) as request:
        assert value.call_tool('read', {}) == 'fresh'
        assert 0 < request.call_args.kwargs['timeout'] <= .1


def test_bound_cancellation_interrupts_stdio_without_explicit_event():
    value = client()
    event = threading.Event()
    cancel = threading.Timer(.04, event.set)
    late = threading.Timer(.4, lambda: value._read_queue.put(reply(1, 'late')))
    cancel.start()
    late.start()
    started = time.monotonic()
    try:
        with cancellation_scope(event), pytest.raises(McpCancelledError):
            value.call_tool('slow', {})
        assert time.monotonic() - started < .25
    finally:
        cancel.join()
        late.join()


@pytest.mark.parametrize('phase', ['body', 'headers'])
def test_progressing_http_response_cannot_extend_deadline_or_leak_worker(phase):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            slow = request['params']['name'] == 'slow'
            body = reply(request['id'], 'slow response' if slow else 'fresh').encode()
            if slow and phase == 'headers':
                try:
                    self.wfile.write(b'HTTP/1.1 200 OK\r\nX-Slow: ')
                    for _ in range(40):
                        self.wfile.write(b'x')
                        self.wfile.flush()
                        time.sleep(.025)
                except (BrokenPipeError, ConnectionResetError):
                    return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                if not slow:
                    self.wfile.write(body)
                    return
                for offset in range(0, len(body), 5):
                    self.wfile.write(body[offset:offset + 5])
                    self.wfile.flush()
                    time.sleep(.025)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    worker.start()
    value = McpClient({'name': 'budget', 'type': 'streamable-http'})
    value._initialized = True
    value._http_url = f'http://127.0.0.1:{server.server_port}/mcp'
    original_workers = {thread.ident for thread in threading.enumerate() if thread.name == 'mcp-http-request'}
    started = time.monotonic()
    try:
        with invocation_budget(60), pytest.raises((PermissionError, TimeoutError)):
            value.call_tool('slow', {})
        assert time.monotonic() - started < .25
        cleanup_deadline = time.monotonic() + .5
        def pending():
            return [thread for thread in threading.enumerate()
                    if thread.name == 'mcp-http-request' and thread.ident not in original_workers]
        while (value._remote_responses or pending()) and time.monotonic() < cleanup_deadline:
            time.sleep(.01)
        assert not value._remote_responses and not pending()
        assert value.call_tool('next', {}) == 'fresh'
    finally:
        server.shutdown()
        server.server_close()
        worker.join(1)
