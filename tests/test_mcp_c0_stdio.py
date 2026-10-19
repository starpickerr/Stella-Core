"""C0: original MCP stdio path without plugin.json."""

from __future__ import annotations

import sys
from pathlib import Path

from agent.tools.mcp.mcp_client import McpClient


def test_stdio_echo_tool_roundtrip():
    server = Path("tests/fixtures/mcp_echo_server.py").resolve()
    client = McpClient(
        {
            "name": "echo-stdio",
            "type": "stdio",
            "command": sys.executable,
            "args": [str(server)],
        }
    )
    try:
        assert client.initialize() is True
        tools = client.list_tools()
        names = {t.get("name") for t in tools}
        assert "echo" in names
        text = client.call_tool("echo", {"text": "hello"})
        assert "echo:hello" in text
    finally:
        client.shutdown()
