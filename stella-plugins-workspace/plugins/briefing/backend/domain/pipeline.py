"""Simplified briefing run: accept pre-fetched items, persist one snapshot.

The Core pipeline fetches mail/eLearning with credentials and drafts with an LLM.
Neither belongs in this plugin, so the host passes pre-fetched ``sources`` (and,
optionally, a pre-drafted ``draft``). Without a draft a deterministic, model-free
composer keeps every candidate. Cursors advance only for fully refreshed sources
and only after a non-failed snapshot is saved.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from .instructions import DEFAULT_RULE_TEXT, rule_document
from .service import BriefingService
from .sources import source_key


def briefing_title(briefing_date: str) -> str:
    day = date.fromisoformat(briefing_date)
    return f"{day.year}年{day.month}月{day.day}日·简报"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def compose_draft(rows, rules, briefing_date: str) -> dict:
    """Deterministic fallback drafter: select every candidate as an FYI card."""
    documents = [f"来源：{rule.source}\n{rule_document(rule)}" for rule in rules if rule.enabled]
    rule_text = DEFAULT_RULE_TEXT + (
        "\n\n## 用户规则文稿（优先于默认原则）\n\n" + "\n\n---\n\n".join(documents) if documents else "")
    mail, cards, lines = [], [], []
    ordered = sorted(rows, key=lambda row: (_parse(row[0].occurred_at), row[0].id), reverse=True)
    for index, (item, email) in enumerate(ordered):
        entry = {
            "id": item.id, "source": item.source, "account_id": item.account_id,
            "source_id": item.source_id, "thread_id": item.thread_id, "sender": item.sender,
            "sender_email": email.sender_email if email else "", "list_id": email.list_id if email else "",
            "title": item.title, "snippet": item.snippet, "occurred_at": item.occurred_at, "url": item.url,
            "body": str(item.payload.get("body") or item.snippet),
            "metadata": {k: v for k, v in item.payload.items() if k != "body"},
            "body_available": "body" in item.payload,
        }
        decision = {"id": item.id, "selected": True, "reason": "未配置筛选模型，保留全部候选",
                    "section": "fyi", "score": 50, "summary": item.snippet or item.title}
        mail.append({**entry, "category": "selected", "filter_reason": decision["reason"], "decision": decision})
        cards.append({
            "source_item_id": item.id, "section": "fyi", "score": 50, "snippet": decision["summary"],
            "sort_order": index, "source": item.source, "account_id": item.account_id,
            "source_id": item.source_id, "thread_id": item.thread_id, "sender": item.sender,
            "title": item.title, "occurred_at": item.occurred_at, "url": item.url,
            "payload": {**item.payload, "_briefing_reason": decision["reason"]},
        })
        lines.append(f"- {item.title or item.source_id}（{item.sender or item.source}）")
    body = "\n".join(lines) if lines else "本时间窗口内没有新的候选信息。"
    return {"title": briefing_title(briefing_date), "body": body, "items": cards, "mail": mail,
            "rule_text": rule_text}


class BriefingPipeline:
    def __init__(self, service: BriefingService, clock=None):
        self.service = service
        self.clock = clock or (lambda: datetime.now().astimezone())

    def run(self, *, briefing_date: Optional[str] = None, operation: str = "upsert",
            trigger: str = "manual", sources: Optional[list] = None, draft: Optional[dict] = None) -> dict:
        if not sources:
            raise ValueError("no briefing sources configured")
        if operation not in {"create", "update", "upsert"}:
            raise ValueError("operation must be create or update")
        if trigger not in {"manual", "scheduled"}:
            raise ValueError("invalid briefing trigger")
        for row in sources:
            if not isinstance(row, dict) or not row.get("source"):
                raise ValueError("each source entry needs a source name")
        store = self.service.store
        if not store.run_lock.acquire(blocking=False):
            raise ValueError("简报正在生成，请等待当前运行完成后刷新")
        try:
            day = briefing_date or self.clock().date().isoformat()
            existing = self.service.briefing_for_date(day)
            if operation == "create" and existing and existing.generated_at:
                return self.service.get_briefing(existing.id)
            if operation == "update" and (not existing or not existing.generated_at):
                raise ValueError("generate this day's briefing before updating it")
            return self._run(day, trigger, sources, draft)
        finally:
            store.run_lock.release()

    def _run(self, day: str, trigger: str, sources: list, draft: Optional[dict]) -> dict:
        store = self.service.store
        local_now = self.clock()
        finish = _iso(local_now)
        existing = self.service.briefing_for_date(day)
        previous = [row for row in self.service.list_briefings() if row.id[4:14] < day and row.generated_at]
        boundary = max((row.window_end or row.generated_at for row in previous), key=_parse, default=None)
        initial = datetime.combine(date.fromisoformat(day) - timedelta(days=1), datetime.min.time()).replace(
            hour=20, tzinfo=local_now.tzinfo)
        default_start = _iso(initial)
        start = (existing.window_start if existing and existing.window_start else boundary) or default_start
        if _parse(start) > _parse(finish):
            raise ValueError("briefing end precedes the previous successful update")
        briefing = self.service.start_briefing(briefing_date=day)
        source_windows = {k: dict(v) for k, v in briefing.source_windows.items()}
        run_id = f"run-{day}-{int(local_now.timestamp())}"
        errors: list[str] = []
        cursor_updates: list[tuple] = []
        refreshed: list[dict] = []
        fully: set[str] = set()
        try:
            for source in sources:
                name, account = source["source"], source.get("account_id") or "default"
                key = source_key({"source": name, "account_id": account})
                src_start = source_windows.get(key, {}).get("start") or start
                label = source.get("name") or name
                src_errors = [str(e) for e in source.get("errors") or []]
                rows = [self.service.build_source_item({**item, "source": name, "account_id": account})
                        for item in source.get("items") or []]
                store.stage_source_items(run_id, rows)
                if src_errors:
                    errors.extend(f"{label}: {e}" for e in src_errors)
                    store.stage_source_errors(run_id, name, account, src_errors)
                else:
                    fully.add(key)
                    source_windows[key] = {"source": name, "account_id": account, "name": label,
                                           "start": src_start, "end": finish}
                    cursor_updates.extend((name, account, k, str(v)) for k, v in (source.get("cursors") or {}).items())
                refreshed.append({"name": name, "account": account, "key": key, "start": src_start})
            catalog_rows = []
            for row in refreshed:
                catalog_rows.extend(store.staged_window_candidates(run_id, row["start"], finish,
                                                                   [(row["name"], row["account"])]))
            status = "failed" if errors and not fully else "partial" if errors else "completed"
            drafted: dict[str, Any] = {}
            if status != "failed":
                drafted = draft if isinstance(draft, dict) else compose_draft(
                    catalog_rows, self.service.list_rules(enabled_only=True), day)
            mail = drafted.get("mail", [])
            filtered = sum(row["category"] == "filtered" for row in mail)
            windows = [w for w in source_windows.values() if w.get("end")]
            window_start = min((w["start"] for w in windows), key=_parse) if windows else start
            payload = {
                "status": status, "run_at": finish, "window_start": window_start, "window_end": finish,
                "trigger": trigger,
                "title": (briefing.title or briefing_title(day)) if status == "failed" else drafted.get("title") or briefing_title(day),
                "body": briefing.body if status == "failed" else drafted.get("body", ""),
                "fetched_count": briefing.fetched_count if status == "failed" else len(catalog_rows),
                "kept_count": briefing.kept_count if status == "failed" else len(mail) - filtered,
                "filtered_count": briefing.filtered_count if status == "failed" else filtered,
                "error_message": "; ".join(errors),
                "cursor_updates": [c for c in cursor_updates if f"{c[0]}:{c[1]}" in fully],
                "staged_run_id": run_id,
            }
            if status != "failed":
                payload.update(items=drafted.get("items", []), mail=mail, rule_text=drafted.get("rule_text", ""),
                               source_windows=source_windows,
                               updated_sources=[r["key"] for r in refreshed if r["key"] in fully])
            return self.service.complete_briefing(briefing.id, payload)
        except Exception as exc:
            self.service.complete_briefing(briefing.id, {
                "status": "failed", "run_at": finish, "trigger": trigger, "error_message": str(exc)})
            raise
