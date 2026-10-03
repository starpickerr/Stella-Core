"""Agent-facing operations for the independent to-do app."""

from __future__ import annotations

import json

from agent.todos import TodoService
from agent.tools.base_tool import BaseTool, ToolResult


class TodosTool(BaseTool):
    name = "todos"
    description = "管理事务：查看、创建、编辑、完成和删除。可设置截止日期、时间、优先级与重复规则。"
    params = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "get", "create", "update", "complete", "delete"]},
            "id": {"type": "string"}, "title": {"type": "string"}, "notes": {"type": "string"},
            "due_on": {"type": "string", "description": "YYYY-MM-DD，可留空"},
            "planned_on": {"type": "string", "description": "计划处理日 YYYY-MM-DD，与截止日分开"},
            "list_name": {"type": "string", "description": "清单名称"},
            "flagged": {"type": "boolean"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "checklist": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "title": {"type": "string"}, "completed": {"type": "boolean"}},
                "required": ["title"]}},
            "due_time": {"type": "string", "description": "HH:MM，可留空"},
            "timezone": {"type": "string", "description": "IANA 时区"},
            "priority": {"type": "integer", "minimum": 0, "maximum": 3},
            "repeat_frequency": {"type": "string", "enum": ["none", "daily", "weekly", "monthly", "yearly"]},
            "repeat_days": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 6}},
            "repeat_until": {"type": "string"}, "completed": {"type": "boolean"},
            "start": {"type": "string"}, "end": {"type": "string"}, "include_completed": {"type": "boolean"},
        },
        "required": ["action"],
    }

    def __init__(self, config=None, service=None):
        super().__init__()
        self.service = service

    def execute(self, params):
        try:
            if not isinstance(params, dict):
                raise ValueError("parameters must be an object")
            if self.service is None:
                from application import Application, RequestContext
                service = Application.port("todos", RequestContext.ambient("agent"))
            else:
                service = self.service
            action = params.get("action")
            fields = ("title", "notes", "due_on", "due_time", "timezone", "priority",
                      "repeat_frequency", "repeat_days", "repeat_until", "planned_on", "list_name",
                      "flagged", "tags", "checklist")
            payload = {key: params[key] for key in fields if key in params}
            if action == "list":
                result = {"todos": service.list_todos(params.get("start"), params.get("end"),
                                                        params.get("include_completed", True))}
            elif action == "get":
                result = {"todo": service.get_todo(params.get("id"))}
            elif action == "create":
                result = {"todo": service.create_todo(payload)}
            elif action == "update":
                result = {"todo": service.update_todo(params.get("id"), payload)}
            elif action == "complete":
                result = {"todo": service.complete_todo(params.get("id"), params.get("completed"))}
            elif action == "delete":
                service.delete_todo(params.get("id"))
                result = {"deleted": params.get("id")}
            else:
                raise ValueError("unknown todo action")
            return ToolResult.success(json.dumps(result, ensure_ascii=False))
        except (ValueError, KeyError) as exc:
            return ToolResult.fail(str(exc))
