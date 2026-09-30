"""Deterministic sources and model responses for briefing integration tests."""

import json
from typing import Dict, List, Optional

from agent.briefing.sources.base import FetchResult, FetchedItem


class StaticSource:
    name = "email"
    account_id = "default"

    def __init__(
        self,
        items: Optional[List[FetchedItem]] = None,
        cursors: Optional[Dict[str, str]] = None,
        *,
        name: str = "email",
        account_id: str = "default",
        error: Optional[BaseException] = None,
    ):
        self.name = name
        self.account_id = account_id
        self._items = list(items or [])
        self._cursors = dict(cursors or {"imap_uid": "1"})
        self._error = error

    def fetch(self, cursors: Dict[str, str]) -> FetchResult:
        if self._error is not None:
            raise self._error
        return FetchResult(items=list(self._items), cursors=dict(self._cursors))


class DeterministicBriefingModel:
    """Exercise the production Agent loop without making provider requests."""

    model = "briefing-test-model"

    def call_stream(self, request):
        last = request.messages[-1]["content"]
        if any(block.get("type") == "tool_result" for block in last):
            yield {"choices": [{"delta": {"content": "完成"}, "finish_reason": "stop"}]}
            return
        text = next(block["text"] for block in last if block["type"] == "text")
        data = json.loads(text[text.index("{"):])
        if "candidates" in data:
            decisions = []
            for row in data["candidates"]:
                metadata = row["metadata"]
                selected = metadata.get("_test_selected", True)
                if "排除发件域名等于“spam.example”" in request.system and row["sender_email"].endswith("@spam.example"):
                    selected = False
                if "排除发件人等于“Ada”" in request.system and row["sender"] == "Ada":
                    selected = False
                decisions.append({
                    "id": row["id"], "selected": selected,
                    "reason": metadata.get("_test_reason", "测试模型筛选结果"),
                    "section": metadata.get("_test_section", "action"),
                    "score": metadata.get("_test_score", 80),
                    "summary": metadata.get("_test_summary", row["title"]),
                })
            arguments = {"decisions": decisions}
            name = "briefing_decisions_result"
        else:
            arguments = {
                "body": "## 需处理\n" + "\n".join(f"- {row['summary']}" for row in data["items"]) if data["items"] else "今日无要事。",
                "source_item_ids": [row["id"] for row in data["items"]],
            }
            name = "briefing_body_result"
        yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "briefing-test-call",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]},
            "finish_reason": "tool_calls"}]}
