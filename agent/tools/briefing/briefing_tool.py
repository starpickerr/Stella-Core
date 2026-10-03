"""Thin adapter over briefing service/pipeline for the agent."""

from __future__ import annotations

import json

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger


class BriefingTool(BaseTool):
    """Generate, update and inspect daily briefings (same store as the Briefing page)."""

    name: str = "briefing"
    description: str = (
        "每日简报工具：拉取多来源候选，由 Agent 按规则文稿筛选、撰写简报，查看历史、邮件详情和管理规则。\n\n"
        "当用户提到晨报、今日简报、邮件摘要、eLearning 课程事项、标记已处理、不看某发件人时使用。\n"
        "使用方法：\n"
        "- 生成今日简报：action='run'（可选 briefing_date='2026-09-09'）\n"
        "- 更新来源：action='sources' 查询可用 ID；run 的 sources 不填或 ['all'] 更新全部，也可 ['email']、['elearning'] 或指定来源 ID\n"
        "- 列表：action='list'（可选 kind='morning', status='completed'）\n"
        "- 详情：action='get', briefing_id='brf-2026-09-09-morning'\n"
        "- 改条目状态：action='item_status', item_id='…', status='done'/'undo'/'ignored'/'follow_up'\n"
        "- 候选信息：action='mail', briefing_id='…'，source='email'/'elearning'/'*'，可选 category='candidate'/'selected'/'filtered'；source_item_id 查看正文\n"
        "- 规则文稿（普通文本或 Markdown）：text='排除地址以 @promo.example 结尾的邮件，保留作业通知'\n"
        "- 规则：action='add_rule' / 'list_rules' / 'update_rule' / 'delete_rule'\n\n"
        "在简报设置的来源管理中配置 IMAP 邮箱或 eLearning；也可用 IMAP_HOST、IMAP_USER、IMAP_PASSWORD 提供初始邮箱。"
    )
    params: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "run",
                    "sources",
                    "list",
                    "get",
                    "mail",
                    "item_status",
                    "add_rule",
                    "list_rules",
                    "update_rule",
                    "delete_rule",
                ],
                "description": "操作类型",
            },
            "briefing_id": {"type": "string", "description": "简报 ID（get）"},
            "briefing_date": {
                "type": "string",
                "description": "YYYY-MM-DD，run 时不填则为今天",
            },
            "operation": {
                "type": "string",
                "enum": ["create", "update", "upsert"],
                "description": "create 首次生成（已有则直接返回）；update 更新当天主简报；默认 upsert 自动选择",
            },
            "sources": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                        "description": "run：来源 ID 或类型；省略/['all'] 为全部。未选来源保留原内容；sources 操作查询可选 ID"},
            "kind": {
                "type": "string",
                "enum": ["morning", "followup", "meeting"],
                "description": "简报类型，默认 morning",
            },
            "status": {
                "type": "string",
                "description": "list 过滤简报状态，或 item_status 的条目状态",
            },
            "item_id": {"type": "string", "description": "条目 ID（item_status）"},
            "rule_id": {"type": "string", "description": "规则 ID（update_rule / delete_rule）"},
            "text": {"type": "string", "description": "筛选和简报写作的规则文稿，支持自由文本或 Markdown（add_rule/update_rule）"},
            "category": {"type": "string", "enum": ["candidate", "selected", "filtered"]},
            "source_item_id": {"type": "string", "description": "mail：查看某个候选的完整内容"},
            "offset": {"type": "integer", "minimum": 0, "description": "mail：列表起点，每页 50 封"},
            "source": {
                "type": "string",
                "description": "规则来源默认 *；mail 可用 email/elearning/* 选择候选信息来源，默认 email",
            },
            "enabled": {"type": "boolean", "description": "update_rule：启用 / 停用规则"},
        },
        "required": ["action"],
    }

    def __init__(self, config: dict = None, service=None, pipeline=None):
        super().__init__()
        self.config = config or {}
        self._service = service
        self._pipeline = pipeline

    def _get_service(self):
        if self._service is not None:
            return self._service
        from application import Application, RequestContext
        return Application.port("briefing", RequestContext.ambient("agent"))

    def _get_pipeline(self, service):
        if self._pipeline is not None:
            return self._pipeline
        from agent.briefing.pipeline import BriefingPipeline
        from agent.briefing.sources.registry import configured_sources
        from agent.briefing.generator import AgentBriefingGenerator

        return BriefingPipeline(service, configured_sources(), generator=AgentBriefingGenerator(
            model=self.model, cancel_event=self.cancel_event, progress=self.report_progress),
            cancel_event=self.cancel_event)

    def execute(self, params: dict) -> ToolResult:
        if not isinstance(params, dict):
            return ToolResult.fail("参数必须是对象")
        action = params.get("action")
        if not isinstance(action, str):
            return ToolResult.fail("缺少参数: action")
        handlers = {
            "run": self._run,
            "sources": self._sources,
            "list": self._list,
            "get": self._get,
            "mail": self._mail,
            "item_status": self._item_status,
            "add_rule": self._add_rule,
            "list_rules": self._list_rules,
            "update_rule": self._update_rule,
            "delete_rule": self._delete_rule,
        }
        handler = handlers.get(action)
        if handler is None:
            return ToolResult.fail(
                f"未知操作: {action!r}，可用: {', '.join(handlers)}"
            )
        try:
            service = self._get_service()
        except Exception as e:
            logger.error(f"[BriefingTool] service unavailable: {e}")
            return ToolResult.fail(f"简报不可用: {e}")
        try:
            return handler(service, params or {})
        except (ValueError, KeyError) as e:
            msg = e.args[0] if e.args else str(e)
            return ToolResult.fail(f"操作失败: {msg}")
        except Exception as e:
            logger.error(f"[BriefingTool] {action} failed: {e}")
            return ToolResult.fail(f"操作失败: {e}")

    def _run(self, service, params: dict) -> ToolResult:
        scheduled = bool(getattr(self, "current_context", None) and self.current_context.get("is_scheduled_task"))
        pipeline = self._get_pipeline(service)
        if scheduled:
            from agent.briefing.service import briefing_id_for
            if params.get("operation", "upsert") == "create":
                day = params.get("briefing_date") or pipeline.clock().date().isoformat()
                existing = service.get_briefing(briefing_id_for(day, params.get("kind") or "morning"))
                if existing and existing["briefing"].generated_at:
                    return ToolResult.success("当日简报已生成，跳过定时生成。\n" + self._format_detail(existing, existing["briefing"]))
            if not pipeline.sources:
                return ToolResult.fail("请先在简报设置中配置来源，定时任务稍后重试")
        detail = pipeline.run(
            kind=params.get("kind") or "morning",
            briefing_date=params.get("briefing_date"),
            operation=params.get("operation", "upsert"),
            trigger="scheduled" if scheduled else "manual",
            sources=params.get("sources"),
        )
        briefing = detail["briefing"]
        output = self._format_detail(detail, briefing)
        if briefing.status == "failed":
            return ToolResult.fail(output)
        return ToolResult.success(output)

    def _sources(self, service, params):
        from agent.briefing.sources.registry import public_sources
        return ToolResult.success(json.dumps({"sources": public_sources()}, ensure_ascii=False))

    def _list(self, service, params: dict) -> ToolResult:
        rows = service.list_briefings(
            kind=params.get("kind"), status=params.get("status")
        )
        if not rows:
            return ToolResult.success("暂无简报")
        lines = [
            f"- {row.id}  {row.status}  {row.title or '(无标题)'}  kept={row.kept_count}"
            for row in rows[:30]
        ]
        return ToolResult.success("简报列表:\n" + "\n".join(lines))

    def _get(self, service, params: dict) -> ToolResult:
        briefing_id = params.get("briefing_id")
        if not briefing_id:
            return ToolResult.fail("缺少参数: briefing_id")
        detail = service.get_briefing(briefing_id)
        if detail is None:
            return ToolResult.fail(f"未找到简报: {briefing_id}")
        return ToolResult.success(self._format_detail(detail, detail["briefing"]))

    def _item_status(self, service, params: dict) -> ToolResult:
        item_id = params.get("item_id")
        status = params.get("status")
        if not item_id or not status:
            return ToolResult.fail("缺少参数: item_id, status")
        item = service.update_item_status(item_id, status)
        return ToolResult.success(
            f"已更新 {item.id} → {item.status}  {item.title}"
        )

    def _mail(self, service, params: dict) -> ToolResult:
        detail = service.get_briefing(params.get("briefing_id"))
        if detail is None:
            raise ValueError("简报不存在，请提供 briefing_id")
        if not detail["briefing"].mail_snapshot_available:
            raise ValueError("此版本没有候选详情，请先更新简报")
        rows = detail["mail"]
        if params.get("source_item_id"):
            row = next((row for row in rows if row["id"] == params["source_item_id"]), None)
            if row is None:
                raise ValueError("候选信息不存在")
            return ToolResult.success(json.dumps(row, ensure_ascii=False))
        category = params.get("category", "candidate")
        if category not in ("candidate", "selected", "filtered"):
            raise ValueError("邮件分类无效")
        source = params.get("source", "email")
        rows = [row for row in rows if (source == "*" or row["source"] == source) and (category == "candidate" or row["category"] == category)]
        offset = params.get("offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset 必须是非负整数")
        return ToolResult.success(json.dumps({"total": len(rows), "next_offset": offset + 50 if offset + 50 < len(rows) else None,
            "mail": [{key: row[key] for key in ("id", "title", "sender", "sender_email", "occurred_at", "category", "filter_reason")}
                     for row in rows[offset:offset + 50]]}, ensure_ascii=False))

    def _add_rule(self, service, params: dict) -> ToolResult:
        rule = service.create_rule({"text": params.get("text"), "source": params.get("source") or "*"})
        return ToolResult.success(f"已添加规则文稿 {rule.id}:\n{rule.text}")

    def _list_rules(self, service, params: dict) -> ToolResult:
        rows = service.list_rules()
        if not rows:
            from agent.briefing.instructions import DEFAULT_RULE_TEXT
            return ToolResult.success("未保存规则文稿，当前使用默认规则：\n" + DEFAULT_RULE_TEXT)
        lines = [f"- {row.id}  {'on' if row.enabled else 'off'}  source={row.source}\n{row.text}" for row in rows]
        return ToolResult.success("规则文稿:\n" + "\n\n".join(lines))

    def _update_rule(self, service, params: dict) -> ToolResult:
        rule_id = params.get("rule_id")
        if not rule_id:
            return ToolResult.fail("缺少参数: rule_id")
        payload = {key: params[key] for key in (
            "enabled", "source", "text"
        ) if key in params}
        rule = service.update_rule(rule_id, payload)
        return ToolResult.success(f"已更新规则 {rule.id}: {'on' if rule.enabled else 'off'}")

    def _delete_rule(self, service, params: dict) -> ToolResult:
        rule_id = params.get("rule_id")
        if not rule_id:
            return ToolResult.fail("缺少参数: rule_id")
        service.delete_rule(rule_id)
        return ToolResult.success(f"已删除规则 {rule_id}")

    def _format_detail(self, detail: dict, briefing) -> str:
        lines = [
            f"{briefing.title or briefing.id}  [{briefing.status}]",
            f"简报条目：{len(detail.get('items') or [])}；候选 {briefing.fetched_count}，精选 {briefing.kept_count}，过滤 {briefing.filtered_count}",
            briefing.body or "(无正文)",
        ]
        if briefing.error_message:
            lines.append(f"错误: {briefing.error_message}")
        items = detail.get("items") or []
        if items:
            lines.append("")
            lines.append("条目:")
            for item in items:
                lines.append(
                    f"- {item.id} [{item.section}/{item.status}] {item.sender}: {item.title}"
                )
        return "\n".join(lines)
