"""
Bill tool - let the agent record and query the user's personal ledger.

Thin adapter over ``agent.bills.service.BillsService``: the same layer the
Web / desktop bills page talks to, so an entry the agent records shows up in
the UI and vice versa. Amounts are exposed to the model in major units
(yuan) and stored in minor units (fen) by the service.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger

_ENTRY_TYPE_LABEL = {"income": "收入", "expense": "支出"}
_STATUS_LABEL = {"posted": "已入账", "pending": "待入账", "reversed": "已冲销"}
_PERIOD_LABEL = {"monthly": "月度", "yearly": "年度"}
_PERIOD_STATUS_LABEL = {"open": "进行中", "closed": "已结账"}

# Cap on rows echoed back to the model; a whole month of spending can be
# hundreds of lines and the statement actions exist for the aggregate view.
_MAX_ROWS = 100


def _yuan(amount_minor: int) -> str:
    return f"{int(amount_minor) / 100:.2f}"


def _to_minor(amount) -> int:
    """Major-unit amount (32.5 / "32.50") -> minor-unit integer (3250)."""
    try:
        value = Decimal(str(amount).strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError(f"amount 无法解析为金额: {amount!r}") from None
    if value.is_nan() or value.is_infinite():
        raise ValueError(f"amount 无法解析为金额: {amount!r}")
    minor = (value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(minor)


def _now_local_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _wall_time(occurred_at: str) -> str:
    from agent.bills.service import parse_occurred_at

    try:
        return parse_occurred_at(occurred_at).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(occurred_at)


class BillsTool(BaseTool):
    """Record, query and maintain ledger entries; read monthly / yearly statements."""

    name: str = "bills"
    description: str = (
        "记账与账单查询工具，读写用户的个人账本（与「账单」页面共用同一数据库）。\n\n"
        "当用户提到花了多少钱、收入、记一笔、查账、本月/今年花费、账单汇总等时使用。\n"
        "使用方法：\n"
        "- 记一笔：action='add', name='午餐', amount=32.5, entry_type='expense', "
        "category='消费'（可选）, occurred_at='2026-08-02T12:30:00+08:00'（可选，默认现在）\n"
        "- 查流水：action='list', year=2026, month=8；或 start='2026-08-01', end='2026-08-31'（含两端）\n"
        "- 查/改/删单条：action='get' / 'update' / 'delete', entry_id='流水ID'（update 只传要改的字段）\n"
        "- 账单汇总：action='statements', period_type='monthly'/'yearly'（可选）, year=2026（可选）\n"
        "- 账单明细：action='statement', statement_id='账单ID'，按类别/名称汇总的金额与笔数\n\n"
        "金额一律以元为单位（可带小数），entry_type 只能是 income（收入）或 expense（支出）。"
        "删除前先用 list/get 确认 entry_id。"
    )
    params: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "get", "update", "delete", "statements", "statement"],
                "description": (
                    "操作类型: add(记一笔), list(查流水), get(查单条), update(修改), "
                    "delete(删除), statements(月/年账单列表), statement(账单明细)"
                ),
            },
            "entry_id": {
                "type": "string",
                "description": "流水 ID（用于 get/update/delete）",
            },
            "name": {
                "type": "string",
                "description": "名称/细项，如「午餐」「地铁」「房租」「月薪」（add 必填）",
            },
            "amount": {
                "type": "number",
                "description": "金额，单位为元，可带小数，如 32.5（add 必填）",
            },
            "entry_type": {
                "type": "string",
                "enum": ["income", "expense"],
                "description": "income=收入，expense=支出（add 必填）",
            },
            "category": {
                "type": "string",
                "description": "类别，如「消费」「交通」「餐饮」「工资」「退款」；不填则为空",
            },
            "note": {
                "type": "string",
                "description": "备注",
            },
            "counterparty": {
                "type": "string",
                "description": "交易对方，如商家或付款人",
            },
            "occurred_at": {
                "type": "string",
                "description": (
                    "发生时间，ISO-8601，如 '2026-08-02T12:30:00+08:00' 或 '2026-08-02T12:30'；"
                    "add 时不填默认为当前时间"
                ),
            },
            "currency": {
                "type": "string",
                "description": "ISO 4217 货币代码，默认 CNY",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "posted", "reversed"],
                "description": "流水状态，默认 posted（已入账）；只有 posted 会计入账单汇总",
            },
            "year": {
                "type": "integer",
                "description": "年份（list 与 statements 用）",
            },
            "month": {
                "type": "integer",
                "description": "月份 1–12（list 用；与 year 一起给出）",
            },
            "start": {
                "type": "string",
                "description": "起始日期 YYYY-MM-DD（list 用，与 end 一起给出，含当天）",
            },
            "end": {
                "type": "string",
                "description": "结束日期 YYYY-MM-DD（list 用，与 start 一起给出，含当天）",
            },
            "period_type": {
                "type": "string",
                "enum": ["monthly", "yearly"],
                "description": "账单类型（statements 用）：monthly=月度，yearly=年度",
            },
            "statement_id": {
                "type": "string",
                "description": "账单 ID（statement 用），可从 statements 结果中获得",
            },
        },
        "required": ["action"],
    }

    def __init__(self, config: dict = None, service=None):
        super().__init__()
        self.config = config or {}
        # Injected in tests; in production resolved per call so the store
        # follows the identity of the message being handled.
        self._service = service

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _get_service(self):
        if self._service is not None:
            return self._service
        from application import Application, RequestContext
        return Application.port("bills", RequestContext.ambient("agent"))

    def execute(self, params: dict) -> ToolResult:
        action = (params or {}).get("action")
        handlers = {
            "add": self._add,
            "list": self._list,
            "get": self._get,
            "update": self._update,
            "delete": self._delete,
            "statements": self._statements,
            "statement": self._statement,
        }
        handler = handlers.get(action)
        if handler is None:
            return ToolResult.fail(
                f"未知操作: {action!r}，可用: {', '.join(handlers)}"
            )
        try:
            service = self._get_service()
        except Exception as e:
            logger.error(f"[BillsTool] service unavailable: {e}")
            return ToolResult.fail(f"账本不可用: {e}")
        try:
            return handler(service, params)
        except (ValueError, KeyError) as e:
            # Validation and not-found errors from the service layer; the
            # message is written for a caller and safe to hand back as-is.
            msg = e.args[0] if e.args else str(e)
            return ToolResult.fail(f"操作失败: {msg}")
        except Exception as e:
            logger.error(f"[BillsTool] {action} failed: {e}")
            return ToolResult.fail(f"操作失败: {e}")

    # ------------------------------------------------------------------
    # Ledger
    # ------------------------------------------------------------------

    def _add(self, service, params: dict) -> ToolResult:
        missing = [k for k in ("name", "amount", "entry_type") if params.get(k) in (None, "")]
        if missing:
            return ToolResult.fail(f"缺少参数: {', '.join(missing)}")
        payload = self._ledger_payload(params, for_update=False)
        entry = service.create_ledger(payload)
        return ToolResult.success("已记账:\n" + self._format_entry(entry))

    def _update(self, service, params: dict) -> ToolResult:
        entry_id = params.get("entry_id")
        if not entry_id:
            return ToolResult.fail("缺少参数: entry_id")
        payload = self._ledger_payload(params, for_update=True)
        if not payload:
            return ToolResult.fail("update 至少需要一个要修改的字段")
        entry = service.update_ledger(entry_id, payload)
        return ToolResult.success("已更新:\n" + self._format_entry(entry))

    def _delete(self, service, params: dict) -> ToolResult:
        entry_id = params.get("entry_id")
        if not entry_id:
            return ToolResult.fail("缺少参数: entry_id")
        existing = service.get_ledger(entry_id)
        if existing is None:
            return ToolResult.fail(f"未找到流水: {entry_id}")
        service.delete_ledger(entry_id)
        return ToolResult.success("已删除:\n" + self._format_entry(existing))

    def _get(self, service, params: dict) -> ToolResult:
        entry_id = params.get("entry_id")
        if not entry_id:
            return ToolResult.fail("缺少参数: entry_id")
        entry = service.get_ledger(entry_id)
        if entry is None:
            return ToolResult.fail(f"未找到流水: {entry_id}")
        return ToolResult.success(self._format_entry(entry))

    def _list(self, service, params: dict) -> ToolResult:
        start, end = params.get("start"), params.get("end")
        year, month = params.get("year"), params.get("month")
        if start or end:
            if not (start and end):
                return ToolResult.fail("按日期范围查询需同时提供 start 和 end")
            rows = service.list_ledger_between(str(start), str(end))
            title = f"{start} ~ {end}"
        else:
            now = datetime.now()
            year = int(year) if year is not None else now.year
            month = int(month) if month is not None else now.month
            rows = service.list_ledger(year, month)
            title = f"{year}-{month:02d}"

        if not rows:
            return ToolResult.success(f"{title} 没有流水记录。")

        income = sum(r["amount_minor"] for r in rows if r["entry_type"] == "income" and r["status"] == "posted")
        expense = sum(r["amount_minor"] for r in rows if r["entry_type"] == "expense" and r["status"] == "posted")
        lines = [
            f"{title} 共 {len(rows)} 笔流水（已入账口径）："
            f"收入 {_yuan(income)}，支出 {_yuan(expense)}，结余 {_yuan(income - expense)}",
            "",
        ]
        for row in rows[:_MAX_ROWS]:
            lines.append(self._format_row(row))
        if len(rows) > _MAX_ROWS:
            lines.append(f"... 还有 {len(rows) - _MAX_ROWS} 笔未显示，可缩小日期范围或改用 statements 看汇总")
        return ToolResult.success("\n".join(lines))

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------

    def _statements(self, service, params: dict) -> ToolResult:
        period_type = params.get("period_type") or None
        year = params.get("year")
        year = int(year) if year is not None else None
        rows = service.list_statements(period_type, year)
        if not rows:
            scope = " ".join(
                s for s in (str(year) if year else "", _PERIOD_LABEL.get(period_type, ""))
                if s
            )
            return ToolResult.success(f"暂无{scope}账单（只有已入账流水会生成账单）。")
        lines = [f"共 {len(rows)} 份账单："]
        for st in rows:
            lines.append(self._format_statement_head(st))
        return ToolResult.success("\n".join(lines))

    def _statement(self, service, params: dict) -> ToolResult:
        statement_id = params.get("statement_id")
        if not statement_id:
            return ToolResult.fail("缺少参数: statement_id")
        st = service.get_statement(statement_id)
        if st is None:
            return ToolResult.fail(f"未找到账单: {statement_id}")
        lines = [self._format_statement_head(st), ""]
        items = st.get("items") or []
        if not items:
            lines.append("（无明细）")
        for item in items:
            label = _ENTRY_TYPE_LABEL.get(item["entry_type"], item["entry_type"])
            cat = f"{item['category']}/" if item.get("category") else ""
            lines.append(
                f"- [{label}] {cat}{item['name']}: {_yuan(item['amount_minor'])} ({item['entry_count']} 笔)"
            )
        return ToolResult.success("\n".join(lines))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ledger_payload(params: dict, for_update: bool) -> dict:
        """Map tool arguments onto the service's ledger payload.

        On add, defaults are filled in (time = now); on update only the
        fields the caller actually passed are forwarded, so the service
        keeps everything else from the existing row.
        """
        payload = {}
        for key in ("name", "entry_type", "category", "note", "counterparty", "currency", "status"):
            value = params.get(key)
            if value is not None:
                payload[key] = value
        if params.get("amount") is not None:
            payload["amount_minor"] = _to_minor(params["amount"])
        if params.get("occurred_at"):
            payload["occurred_at"] = str(params["occurred_at"]).strip()
        elif not for_update:
            payload["occurred_at"] = _now_local_iso()
        return payload

    @staticmethod
    def _format_row(row: dict) -> str:
        label = _ENTRY_TYPE_LABEL.get(row["entry_type"], row["entry_type"])
        sign = "+" if row["entry_type"] == "income" else "-"
        cat = f"{row['category']}/" if row.get("category") else ""
        extras = []
        if row.get("note"):
            extras.append(f"备注: {row['note']}")
        if row.get("status") and row["status"] != "posted":
            extras.append(_STATUS_LABEL.get(row["status"], row["status"]))
        tail = f"  ({'; '.join(extras)})" if extras else ""
        return (
            f"- {_wall_time(row['occurred_at'])}  [{label}] {cat}{row['name']}  "
            f"{sign}{_yuan(row['amount_minor'])} {row.get('currency') or 'CNY'}  id={row['id']}{tail}"
        )

    @staticmethod
    def _format_entry(entry: dict) -> str:
        label = _ENTRY_TYPE_LABEL.get(entry["entry_type"], entry["entry_type"])
        lines = [
            f"id: {entry['id']}",
            f"名称: {entry['name']}",
            f"类型: {label}",
            f"金额: {_yuan(entry['amount_minor'])} {entry.get('currency') or 'CNY'}",
            f"类别: {entry.get('category') or '-'}",
            f"时间: {_wall_time(entry['occurred_at'])}",
            f"状态: {_STATUS_LABEL.get(entry['status'], entry['status'])}",
        ]
        if entry.get("counterparty"):
            lines.append(f"对方: {entry['counterparty']}")
        if entry.get("note"):
            lines.append(f"备注: {entry['note']}")
        return "\n".join(lines)

    @staticmethod
    def _format_statement_head(st: dict) -> str:
        period = _PERIOD_LABEL.get(st["period_type"], st["period_type"])
        when = f"{st['year']}-{st['month']:02d}" if st.get("month") else str(st["year"])
        status = _PERIOD_STATUS_LABEL.get(st.get("status"), st.get("status") or "")
        return (
            f"[{period}] {when} ({st.get('currency') or 'CNY'}, {status})  "
            f"收入 {_yuan(st['income_minor'])}  支出 {_yuan(st['expense_minor'])}  "
            f"结余 {_yuan(st['net_minor'])}  id={st['id']}"
        )
