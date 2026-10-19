"""Thin adapter over existing McpClient for unified connection records."""

from __future__ import annotations

from typing import Any

from agent.tools.mcp.mcp_client import McpClient


class McpAdapter:
    """Owns MCP protocol sessions; lifecycle/authorization stay with Plugin Runtime / Gateway."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)
        self.connection_id = str(config.get("name") or config.get("id") or "mcp")
        self._client = McpClient(self.config)

    def connect(self) -> bool:
        return self._client.initialize()

    def list_tools(self) -> list[dict[str, Any]]:
        return self._client.list_tools()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        return self._client.call_tool(name, arguments)

    def close(self) -> None:
        self._client.shutdown()
