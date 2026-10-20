"""
Memory tools for Agent

Provides memory_search, memory_get and memory_write adapters
"""

from agent.tools.memory.memory_search import MemorySearchTool
from agent.tools.memory.memory_get import MemoryGetTool

__all__ = ['MemorySearchTool', 'MemoryGetTool', 'MemoryWriteTool']

from agent.tools.base_tool import BaseTool, ToolResult


class MemoryWriteTool(BaseTool):
    name = 'memory_write'
    description = 'Store an enduring memory or a daily record. Only memory documents may be changed.'
    params = {'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'},
        'append': {'type': 'boolean'}, 'expected_hash': {'type': 'string'}}, 'required': ['path', 'content']}

    def __init__(self, memory):
        super().__init__()
        self.memory = memory

    def is_available(self):
        from core.services.memory_facade import plugin_available
        return plugin_available('stella.memory')

    def execute(self, args):
        try:
            import json
            return ToolResult.success(json.dumps(self.memory._call('write', **args), ensure_ascii=False))
        except Exception as exc:
            return ToolResult.fail(str(exc))
