from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger
import hashlib
import re


class McpTool(BaseTool):
    """
    将单个 MCP 工具包装为 BaseTool。
    一个 MCP Server 可以提供多个工具，每个工具对应一个 McpTool 实例。
    """

    def __init__(self, client, tool_schema: dict, server_name: str):
        """
        :param client: 该工具所属的 McpClient 实例
        :param tool_schema: MCP 返回的工具描述，格式：
            {"name": str, "description": str, "inputSchema": dict}
        :param server_name: Server 名称，用于日志
        """
        self.client = client
        self.server_name = server_name
        self.remote_name = tool_schema["name"]
        slug = re.sub(r"[^A-Za-z0-9_-]", "_", self.remote_name)[:55].strip("_") or "tool"
        digest = hashlib.sha256(server_name.encode()).hexdigest()[:10]
        tool_digest = hashlib.sha256(self.remote_name.encode()).hexdigest()[:8]
        self.name = f"mcp_{digest}_{slug}_{tool_digest}"
        self.read_only = (tool_schema.get("annotations") or {}).get("readOnlyHint") is True
        self.description = tool_schema.get("description", "")
        self.params = tool_schema.get("inputSchema", {})

    def is_available(self):
        from agent.tools.capability_settings import tool_enabled
        check = getattr(self, '_admission_check', None)
        return tool_enabled(self.name, tool=self) and (check is None or check())

    def execute(self, params: dict) -> ToolResult:
        try:
            if not self.is_available():
                return ToolResult.fail('MCP server is disabled or this connection was replaced.')
        except Exception:
            return ToolResult.fail('Cannot resolve MCP enablement; the tool did not run.')
        if self.is_cancelled():
            return ToolResult.fail("MCP call cancelled")
        logger.info(f"[McpTool] server={self.server_name} tool={self.name} started")
        try:
            managed = getattr(self, '_managed_invoke', None)
            if managed is not None:
                import json
                result = json.dumps({'value':managed(self.remote_name,params,self.cancel_event)},ensure_ascii=False)
            elif self.cancel_event is None:
                result = self.client.call_tool(self.remote_name, params)
            else:
                result = self.client.call_tool(self.remote_name, params, cancel_event=self.cancel_event)
            if self.is_cancelled():
                return ToolResult.fail("MCP call cancelled")
            return ToolResult.success(result)
        except Exception as e:
            logger.error(f"[McpTool] server={self.server_name} tool={self.name} error: {e}")
            return ToolResult.fail(str(e))
