"""Agent-facing calendar operations backed by the desktop SQLite store."""

from __future__ import annotations

import json

from agent.tools.base_tool import BaseTool, ToolResult
from agent.calendar import CalendarService


class CalendarTool(BaseTool):
    name = "calendar"
    description = ("查看、创建、编辑和删除个人日程及分类。时间使用带时区的 ISO 8601 格式；"
                   "list 可按时间范围和分类筛选，get 查看详情。简报中有明确时间的事项会自动进入日程。")
    params = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "get", "create", "update", "delete",
                                                   "categories", "create_category", "update_category", "delete_category"]},
            "id": {"type": "string", "description": "日程或分类 ID"},
            "title": {"type": "string"}, "description": {"type": "string"},
            "start_at": {"type": "string", "description": "ISO 8601，须含时区"},
            "end_at": {"type": "string", "description": "ISO 8601，须含时区"},
            "all_day": {"type": "boolean"}, "location": {"type": "string"},
            "category_id": {"type": "string"}, "name": {"type": "string"},
            "color": {"type": "string", "description": "#RRGGBB"},
            "start": {"type": "string"}, "end": {"type": "string"},
        }, "required": ["action"],
    }

    def __init__(self, config=None, service=None):
        super().__init__()
        self.service = service

    def execute(self, params):
        try:
            if not isinstance(params, dict):
                raise ValueError("parameters must be an object")
            action = params.get("action")
            service = self.service or CalendarService()
            event_fields = ("title", "description", "start_at", "end_at", "all_day", "location", "category_id")
            category_fields = ("name", "color")
            data = {key: params[key] for key in event_fields if key in params}
            category = {key: params[key] for key in category_fields if key in params}
            if action == "list":
                result = {"events": service.list_events(params.get("start"), params.get("end"), params.get("category_id"))}
            elif action == "get":
                result = {"event": service.get_event(params.get("id"))}
            elif action == "create":
                result = {"event": service.create_event(data)}
            elif action == "update":
                result = {"event": service.update_event(params.get("id"), data)}
            elif action == "delete":
                service.delete_event(params.get("id"))
                result = {"deleted": params.get("id")}
            elif action == "categories":
                result = {"categories": service.categories()}
            elif action == "create_category":
                result = {"category": service.create_category(category)}
            elif action == "update_category":
                result = {"category": service.update_category(params.get("id"), category)}
            elif action == "delete_category":
                service.delete_category(params.get("id"))
                result = {"deleted": params.get("id")}
            else:
                raise ValueError("unknown calendar action")
            return ToolResult.success(json.dumps(result, ensure_ascii=False))
        except (ValueError, KeyError) as exc:
            return ToolResult.fail(str(exc))
