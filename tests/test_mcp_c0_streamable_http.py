"""C0: Streamable HTTP MCP without plugin.json."""

from __future__ import annotations

from agent.tools.mcp.mcp_client import McpClient
from tests.fixtures.mcp_streamable_http_server import start_server


def test_streamable_http_echo_roundtrip():
    _server, url, stop = start_server()
    client = McpClient({"name": "echo-http", "type": "streamable-http", "url": url})
    try:
        assert client.initialize() is True
        tools = client.list_tools()
        assert "echo" in {t.get("name") for t in tools}
        text = client.call_tool("echo", {"text": "http"})
        assert "echo:http" in text
    finally:
        client.shutdown()
        stop()
