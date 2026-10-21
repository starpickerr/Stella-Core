"""A standard MCP with different tool/field names; no Stella business protocol."""

import asyncio
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, Tool, ToolAnnotations, TextContent
import json

server = Server("generic-source-test")


@server.list_tools()
async def tools():
    return [
        Tool(
            name=name,
            inputSchema={
                "type": "object",
                "properties": props,
                "additionalProperties": False,
            },
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        for name, props in [
            ("accounts", {}),
            (
                "messages",
                {
                    "account_id": {"type": "string"},
                    "page_token": {"type": "string"},
                    "since": {"type": "string"},
                    "until": {"type": "string"},
                },
            ),
        ]
    ]


@server.call_tool()
async def call(name, arguments):
    if name == "accounts":
        value = {"accounts": [{"key": "account-a", "label": "Generic mailbox"}]}
    elif name == "messages":
        if "cursors" in arguments:
            raise ValueError("cursors is not a standard parameter")
        if arguments.get("page_token") not in {None, "next-page"}:
            raise ValueError("invalid page_token")
        if arguments.get("account_id") != "account-a":
            raise PermissionError("unknown account")
        value = {
            "messages": [
                {
                    "id": "message-a",
                    "subject": "Generic subject",
                    "text": "Generic body",
                    "timestamp": "2026-09-08T22:00:00Z",
                }
            ],
            "next": "next-page",
        }
    else:
        raise ValueError("unknown tool")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(value))],
        structuredContent=value,
    )


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
