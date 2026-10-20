"""Knowledge tool adapters; service implementation lives in the plugin."""
from agent.tools.base_tool import BaseTool, ToolResult
from core.services.knowledge_facade import call


class KnowledgeTool(BaseTool):
    def is_available(self):
        from core.services.memory_facade import plugin_available
        return plugin_available('stella.knowledge')


class KnowledgeSearchTool(KnowledgeTool):
    name = 'knowledge_search'
    description = 'Search the knowledge base. Long-term memories are searched separately with memory_search.'
    params = {'type': 'object', 'properties': {'query': {'type': 'string'}, 'max_results': {'type': 'integer'}}, 'required': ['query']}

    def execute(self, args):
        try:
            import json
            return ToolResult.success(json.dumps(call('search', **args), ensure_ascii=False))
        except Exception as exc:
            return ToolResult.fail(str(exc))


class KnowledgeGetTool(KnowledgeTool):
    name = 'knowledge_get'
    description = 'Read a document from the knowledge base.'
    params = {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}

    def execute(self, args):
        try:
            return ToolResult.success(call('read_file', path=args['path'])['content'])
        except Exception as exc:
            return ToolResult.fail(str(exc))


class KnowledgeWriteTool(KnowledgeTool):
    name = 'knowledge_write'
    description = 'Manage knowledge documents and categories through the knowledge service.'
    params = {'type': 'object', 'properties': {'action': {'type': 'string'}, 'payload': {'type': 'object'}}, 'required': ['action', 'payload']}

    def execute(self, args):
        try:
            import json
            return ToolResult.success(json.dumps(call('dispatch', **args), ensure_ascii=False))
        except Exception as exc:
            return ToolResult.fail(str(exc))
