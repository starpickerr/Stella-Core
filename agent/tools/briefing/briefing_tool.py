"""Thin adapter over briefing service/pipeline for the agent."""

from __future__ import annotations

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger


class BriefingTool(BaseTool):
    """Generate and inspect morning briefings (same store as the Briefing page)."""

    name: str = "briefing"
    description: str = (
        "晨间简报工具：拉取邮件候选、生成今日简报、查看历史、标记条目、管理过滤规则。\n\n"
        "当用户提到晨报、今日简报、邮件摘要、标记已处理、不看某发件人时使用。\n"
        "使用方法：\n"
        "- 生成今日简报：action='run'（可选 briefing_date='2026-09-09'）\n"
        "- 列表：action='list'（可选 kind='morning', status='completed'）\n"
        "- 详情：action='get', briefing_id='brf-2026-09-09-morning'\n"
        "- 改条目状态：action='item_status', item_id='…', status='done'/'undo'/'ignored'/'follow_up'\n"
        "- 规则：action='add_rule' / 'list_rules' / 'update_rule' / 'delete_rule'\n\n"
        "生成简报需要已配置 IMAP_HOST、IMAP_USER、IMAP_PASSWORD。"
    )
    params: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "run",
                    "list",
                    "get",
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
            "rule_action": {
                "type": "string",
                "enum": ["include", "exclude"],
                "description": "add_rule：include 白名单 / exclude 黑名单",
            },
            "match_field": {
                "type": "string",
                "enum": [
                    "sender",
                    "sender_email",
                    "sender_domain",
                    "title",
                    "list_id",
                ],
            },
            "match_op": {
                "type": "string",
                "enum": ["eq", "contains"],
            },
            "match_value": {"type": "string"},
            "source": {
                "type": "string",
                "description": "规则来源，默认 email；'*' 表示全部",
            },
            "note": {"type": "string"},
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
        from agent.briefing.service import BriefingService

        return BriefingService()

    def _get_pipeline(self, service):
        if self._pipeline is not None:
            return self._pipeline
        from agent.briefing.pipeline import BriefingPipeline
        from agent.briefing.sources.email import EmailSource

        return BriefingPipeline(service, [EmailSource()])

    def execute(self, params: dict) -> ToolResult:
        if not isinstance(params, dict):
            return ToolResult.fail("参数必须是对象")
        action = params.get("action")
        if not isinstance(action, str):
            return ToolResult.fail("缺少参数: action")
        handlers = {
            "run": self._run,
            "list": self._list,
            "get": self._get,
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
        pipeline = self._get_pipeline(service)
        detail = pipeline.run(
            kind=params.get("kind") or "morning",
            briefing_date=params.get("briefing_date"),
        )
        briefing = detail["briefing"]
        output = self._format_detail(detail, briefing)
        if briefing.status == "failed":
            return ToolResult.fail(output)
        return ToolResult.success(output)

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

    def _add_rule(self, service, params: dict) -> ToolResult:
        missing = [k for k in ("rule_action", "match_field", "match_value") if not params.get(k)]
        if missing:
            return ToolResult.fail(f"缺少参数: {', '.join(missing)}")
        rule = service.create_rule(
            {
                "action": params["rule_action"],
                "match_field": params["match_field"],
                "match_op": params.get("match_op") or "eq",
                "match_value": params["match_value"],
                "source": params.get("source") or "email",
                "note": params.get("note") or "",
            }
        )
        return ToolResult.success(
            f"已添加规则 {rule.id}: {rule.action} {rule.match_field} "
            f"{rule.match_op} {rule.match_value}"
        )

    def _list_rules(self, service, params: dict) -> ToolResult:
        rows = service.list_rules()
        if not rows:
            return ToolResult.success("暂无过滤规则")
        lines = [
            f"- {row.id}  {'on' if row.enabled else 'off'}  {row.action} "
            f"{row.match_field} {row.match_op} {row.match_value}"
            for row in rows
        ]
        return ToolResult.success("过滤规则:\n" + "\n".join(lines))

    def _update_rule(self, service, params: dict) -> ToolResult:
        rule_id = params.get("rule_id")
        if not rule_id:
            return ToolResult.fail("缺少参数: rule_id")
        payload = {key: params[key] for key in (
            "enabled", "source", "match_field", "match_op", "match_value", "note"
        ) if key in params}
        if "rule_action" in params:
            payload["action"] = params["rule_action"]
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
