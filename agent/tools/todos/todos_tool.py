"""Agent-facing operations for the independent to-do app."""

from __future__ import annotations

import json

from agent.todos import TodoService
from agent.tools.base_tool import BaseTool, ToolResult


class TodosTool(BaseTool):
    name = "todos"
    description = "管理事务：创建、拆解、移动、排序、改变状态和完成。status 表示进度，parent_id 表示层级；依赖关系与层级不同。"
    params = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "get", "create", "update", "complete", "status", "add_subtask", "move", "add_dependency", "remove_dependency", "delete"]},
            "id": {"type": "string"}, "title": {"type": "string"}, "notes": {"type": "string"},
            "prerequisite_id": {"type": "string", "description": "必须先完成的事务 ID，与 parent_id 不同"},
            "parent_id": {"type": ["string", "null"]},
            "position": {"type": "integer", "minimum": 0},
            "status": {"type": "string", "enum": ["todo", "in_progress", "waiting", "blocked", "completed", "cancelled"]},
            "force": {"type": "boolean", "description": "仅在用户明确要求忽略未完成子事务或前置事务时使用"},
            "remind_at": {"type": ["string", "null"], "description": "带时区的 ISO 提醒时间"},
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
                      "flagged", "tags", "checklist", "remind_at")
            payload = {key: params[key] for key in fields if key in params}
            if action == "create" and "parent_id" in params:
                payload["parent_id"] = params["parent_id"]
            if action == "create" and "status" in params:
                payload["status"] = params["status"]
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
                result = {"todo": service.complete_todo(params.get("id"), params.get("completed"),
                                                         params.get("force", False))}
            elif action == "status":
                result = {"todo": service.change_todo_status(params.get("id"), params.get("status"),
                                                               params.get("force", False))}
            elif action == "add_subtask":
                result = {"todo": service.add_subtask(params.get("parent_id"), payload)}
            elif action == "move":
                result = {"todo": service.move_todo(params.get("id"), params.get("parent_id"),
                                                     params.get("position"))}
            elif action == "add_dependency":
                result = {"todo": service.add_dependency(params.get("id"), params.get("prerequisite_id"))}
            elif action == "remove_dependency":
                result = {"todo": service.remove_dependency(params.get("id"), params.get("prerequisite_id"))}
            elif action == "delete":
                service.delete_todo(params.get("id"))
                result = {"deleted": params.get("id")}
            else:
                raise ValueError("unknown todo action")
            return ToolResult.success(json.dumps(result, ensure_ascii=False))
        except (ValueError, KeyError) as exc:
            return ToolResult.fail(str(exc))
