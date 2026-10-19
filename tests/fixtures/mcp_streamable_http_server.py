"""Local Streamable HTTP MCP echo server for C0 tests."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


def make_handler() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                msg = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._json(400, {"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}, "id": None})
                return
            method = msg.get("method")
            req_id = msg.get("id")
            if method == "initialize":
                self._json(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "stella-echo-http", "version": "0.0.1"},
                        },
                    },
                )
                return
            if method == "notifications/initialized":
                self.send_response(202)
                self.end_headers()
                return
            if method == "tools/list":
                self._json(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "tools": [
                                {
                                    "name": "echo",
                                    "description": "Echo text",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"text": {"type": "string"}},
                                        "required": ["text"],
                                    },
                                }
                            ]
                        },
                    },
                )
                return
            if method == "tools/call":
                args = (msg.get("params") or {}).get("arguments") or {}
                text = args.get("text", "")
                self._json(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": f"echo:{text}"}],
                            "isError": False,
                        },
                    },
                )
                return
            self._json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"unknown method {method}"},
                },
            )

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def start_server() -> tuple[ThreadingHTTPServer, str, Callable[[], None]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler())
    host, port = server.server_address
    url = f"http://{host}:{port}/mcp"

    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def stop() -> None:
        server.shutdown()
        server.server_close()

    return server, url, stop
