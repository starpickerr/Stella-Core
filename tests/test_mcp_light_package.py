"""P2 light package: MCP contribution without Stella runtime/UI/data."""

from __future__ import annotations

import sys
from pathlib import Path

from core.plugins.manifest import load_manifest
from core.plugins.mcp.adapter import McpAdapter


def test_mcp_echo_package_has_no_runtime_and_connects():
    root = Path("stella-plugins-workspace/plugins/mcp-echo")
    manifest = load_manifest(root)
    assert "runtime" not in manifest
    assert "data" not in manifest
    assert manifest["contributes"]["mcp"] == ["echo-stdio"]
    adapter = McpAdapter(
        {
            "name": "echo-stdio",
            "type": "stdio",
            "command": sys.executable,
            "args": [str(Path("tests/fixtures/mcp_echo_server.py").resolve())],
        }
    )
    try:
        assert adapter.connect() is True
        assert "echo" in {t["name"] for t in adapter.list_tools()}
    finally:
        adapter.close()
