"""Agent interface to the same Apple sync managers used by desktop."""

from __future__ import annotations

import json

from agent.tools.base_tool import BaseTool, ToolResult
from application import Application


class AppleTool(BaseTool):
    name = "apple"
    description = (
        "查询并管理 Apple 日历和提醒事项连接。一次性导入/写入必须先选择具体来源、条目 ID，"
        "预览后明确确认；不会开启持续同步。不要猜测日历、列表或条目 ID。"
    )
    params = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["calendar", "reminders"]},
            "action": {"type": "string", "enum": ["status", "access", "sources", "items", "lookup",
                "preview", "preview_scope", "one_time", "configure", "sync", "resolve", "disconnect"]},
            "source_id": {"type": "string", "description": "已查询到的 Apple 日历或提醒事项列表 ID"},
            "source_ids": {"type": "array", "items": {"type": "string"}},
            "item_id": {"type": "string", "description": "已查询到的 Apple 条目 ID"},
            "start": {"type": "string", "description": "查询日历时段起点，带时区 ISO 8601"},
            "end": {"type": "string", "description": "查询日历时段终点，带时区 ISO 8601"},
            "item_ids": {"type": "array", "items": {"type": "string"},
                         "description": "一次性导入时为 Apple 条目 ID；写入时为 Stella 条目 ID"},
            "direction": {"type": "string", "enum": ["import", "export", "bidirectional"]},
            "confirm": {"type": "boolean"},
            "preview_token": {"type": "string"},
            "confirm_deletions": {"type": "boolean"},
            "confirm_local_deletions": {"type": "boolean"},
            "target_id": {"type": "string", "description": "待解决冲突的 Stella 条目 ID"},
            "choice": {"type": "string", "enum": ["keep_stella", "keep_apple"]},
        },
        "required": ["kind", "action"],
    }

    def execute(self, params):
        try:
            if not isinstance(params, dict):
                raise ValueError("parameters must be an object")
            kind, action = params.get("kind"), params.get("action")
            if kind not in ("calendar", "reminders"):
                raise ValueError("unknown Apple integration")
            manager = Application.apple_calendar() if kind == "calendar" else Application.apple_reminders()
            source_key = "calendars" if kind == "calendar" else "lists"
            if action == "status":
                result = {"connection": manager.status()}
            elif action == "access":
                result = {"connection": manager.request_access()}
            elif action == "sources":
                status = manager.status()
                if status.get("authorization") != "full_access":
                    raise PermissionError("Apple full access is required")
                result = {"sources": status[source_key]}
            elif action == "items":
                source_id = params.get("source_id")
                if not source_id:
                    raise ValueError("source_id is required")
                rows = manager.items(source_id, params.get("start"), params.get("end")) if kind == "calendar" else manager.items(source_id)
                result = {"items": rows}
            elif action == "lookup":
                source_id, item_id = params.get("source_id"), params.get("item_id")
                if not source_id or not item_id:
                    raise ValueError("source_id and item_id are required")
                result = {"item": manager.lookup_item(source_id, item_id)}
            elif action == "preview":
                from agent.calendar.apple_preview import prepare_items
                result = prepare_items(manager, params.get("direction"),
                    params.get("source_id"), params.get("item_ids"))
            elif action == "preview_scope":
                from agent.calendar.apple_preview import prepare_scope
                result = prepare_scope(manager, params.get("source_ids"), params.get("direction"))
            elif action == "one_time":
                if params.get("confirm") is not True:
                    raise ValueError("explicit confirmation is required")
                from agent.calendar.apple_preview import confirm_items
                confirm_items(manager, params.get("direction"), params.get("source_id"),
                              params.get("item_ids"), params.get("preview_token"))
                value = manager.one_time(params.get("direction"), params.get("source_id"),
                                         params.get("item_ids"), confirm=True)
                result = {"connection": manager.status(), "result": value}
            elif action == "configure":
                if params.get("confirm") is not True:
                    raise ValueError("explicit confirmation is required")
                ids = params.get("source_ids")
                from agent.calendar.apple_preview import confirm_scope
                confirm_scope(manager, ids, params.get("direction"), params.get("preview_token"))
                manager.configure(ids, params.get("direction"))
                manager.start_auto()
                result = {"connection": manager.status()}
            elif action == "sync":
                value = manager.sync(manual=True,
                    confirm_deletions=params.get("confirm_deletions") is True,
                    confirm_local_deletions=params.get("confirm_local_deletions") is True)
                if value["status"] == "disconnected":
                    raise ValueError("Apple integration is disconnected")
                result = {"connection": manager.status(), "result": value}
            elif action == "resolve":
                target_id = params.get("target_id")
                if not target_id:
                    raise ValueError("target_id is required")
                result = {"connection": manager.resolve_conflict(target_id, params.get("choice"))}
            elif action == "disconnect":
                manager.stop_auto()
                result = {"connection": manager.disconnect()}
            else:
                raise ValueError("unknown Apple action")
            return ToolResult.success(json.dumps(result, ensure_ascii=False))
        except (ValueError, KeyError, PermissionError, RuntimeError) as exc:
            return ToolResult.fail(str(exc))
