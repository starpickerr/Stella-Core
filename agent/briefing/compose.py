"""Turn kept candidates into a briefing title, Markdown body, and item payloads."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import List, Sequence

from agent.briefing.rules import ScoredCandidate

MAX_ITEMS = 10


def _sort_key(candidate: ScoredCandidate) -> tuple:
    section_rank = 0 if candidate.section == "action" else 1
    occurred = datetime.fromisoformat(candidate.item.occurred_at.replace("Z", "+00:00"))
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    return (section_rank, -candidate.score, -occurred.timestamp(), candidate.item.source_id)


def merge_threads(candidates: Sequence[ScoredCandidate]) -> List[ScoredCandidate]:
    """Keep one card per non-empty thread; bare source_id rows stay distinct."""
    best: dict[tuple, ScoredCandidate] = {}
    order: list[tuple] = []
    for candidate in candidates:
        item = candidate.item
        key = (item.source, item.account_id, item.thread_id or item.source_id)
        current = best.get(key)
        if current is None:
            best[key] = candidate
            order.append(key)
            continue
        if _sort_key(candidate) < _sort_key(current):
            best[key] = candidate
    return [best[key] for key in order]


def _date_title(briefing_date: str, kind: str) -> str:
    day = date.fromisoformat(briefing_date)
    if kind == "morning":
        return f"{day.year}年{day.month}月{day.day}日·简报"
    if kind == "followup":
        return f"{day.month} 月 {day.day} 日跟进"
    if kind == "meeting":
        return f"{day.month} 月 {day.day} 日会前准备"
    return f"{day.isoformat()} {kind}"


def _text(value: str) -> str:
    # Mail metadata is literal text, never Markdown authored by the sender.
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|~\-])", r"\\\1", " ".join(value.split()))


def compose(
    candidates: Sequence[ScoredCandidate],
    *,
    briefing_date: str,
    kind: str = "morning",
) -> dict:
    ranked = merge_threads(candidates)
    ranked.sort(key=_sort_key)
    selected = ranked[:MAX_ITEMS]
    action = [row for row in selected if row.section == "action"]
    fyi = [row for row in selected if row.section == "fyi"]

    lines: list[str] = []
    if not selected:
        body = "今日无要事。"
    else:
        lines.append(
            f"今日 {len(action)} 件需处理，{len(fyi)} 件知会。"
        )
        if action:
            lines.append("")
            lines.append("## 需回复")
            for row in action:
                snippet = _text(row.item.snippet)
                extra = f"：{snippet}" if snippet else ""
                lines.append(f"- **{_text(row.item.sender or row.item.source)}**：{_text(row.item.title)}{extra}")
        if fyi:
            lines.append("")
            lines.append("## 知会")
            for row in fyi:
                lines.append(f"- **{_text(row.item.sender or row.item.source)}**：{_text(row.item.title)}")
        body = "\n".join(lines)

    items = []
    for index, row in enumerate(selected):
        items.append(
            {
                "source_item_id": row.item.id,
                "section": row.section,
                "score": row.score,
                "sort_order": index,
            }
        )
    return {
        "title": _date_title(briefing_date, kind),
        "body": body,
        "items": items,
        "kept_count": len(selected),
    }
