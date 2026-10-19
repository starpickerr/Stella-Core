#!/usr/bin/env python3
"""Minimal MCP stdio echo server (newline JSON) for C0 tests."""

from __future__ import annotations

import json
import sys


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        req_id = msg.get("id")
        if method == "initialize":
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "stella-echo", "version": "0.0.1"},
                        },
                    }
                ),
                flush=True,
            )
            continue
        if method == "notifications/initialized":
            continue
        if method == "tools/list":
            print(
                json.dumps(
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
                    }
                ),
                flush=True,
            )
            continue
        if method == "tools/call":
            args = (msg.get("params") or {}).get("arguments") or {}
            text = args.get("text", "")
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": f"echo:{text}"}],
                            "isError": False,
                        },
                    }
                ),
                flush=True,
            )
            continue
        if req_id is not None:
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"unknown method {method}"},
                    }
                ),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
