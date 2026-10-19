"""Source selection and fetched-item envelope for the briefing plugin.

The plugin never holds mailbox or eLearning credentials. Candidate sources are
described by the host's Core SourceDirectory (``sourceId``/``pluginId``/``kind``/
``label``/``status``) and passed through the data handle as ``sourceDirectory``;
fetching is done by the owning plugins/host, which hand pre-fetched items to
``run_pipeline``. ``StubSourceAdapter`` keeps the fetch seam testable until the
email/elearning packages land.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class FetchedItem:
    """Envelope from a source, before it is upserted into source_items."""

    source: str
    source_id: str
    account_id: str = "default"
    thread_id: str = ""
    sender: str = ""
    title: str = ""
    snippet: str = ""
    occurred_at: str = ""
    url: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    sender_email: str = ""
    list_id: str = ""

    def to_catalog_payload(self) -> dict:
        return {
            "source": self.source,
            "account_id": self.account_id or "default",
            "source_id": self.source_id,
            "thread_id": self.thread_id,
            "sender": self.sender,
            "title": self.title,
            "snippet": self.snippet,
            "occurred_at": self.occurred_at,
            "url": self.url,
            "payload": dict(self.payload),
            "sender_email": self.sender_email,
            "list_id": self.list_id,
        }


@dataclass
class FetchResult:
    items: List[FetchedItem]
    cursors: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


class StubSourceAdapter:
    """Returns a fixed (default empty) item list; stands in for email/elearning fetchers."""

    def __init__(self, name: str, account_id: str = "default", items: Optional[Iterable[FetchedItem]] = None,
                 display_name: str = ""):
        self.name = name
        self.account_id = account_id
        self.display_name = display_name or name
        self._items = list(items or [])

    def fetch(self, cursors: Dict[str, str]) -> FetchResult:
        return FetchResult(items=list(self._items), cursors={})


def source_key(source: Any) -> str:
    if isinstance(source, dict):
        return f"{source['source']}:{source.get('account_id') or 'default'}"
    return f"{source.name}:{source.account_id}"


def available_sources(source_directory: Optional[list]) -> list[dict]:
    """Normalize Core SourceDirectory rows into selectable briefing sources."""
    rows = []
    for entry in source_directory or []:
        if not isinstance(entry, dict) or entry.get("status", "available") != "available":
            continue
        source_id = str(entry.get("sourceId") or "").strip()
        kind = str(entry.get("kind") or "").strip()
        if not source_id or not kind:
            continue
        account = source_id.split(":", 1)[1] if ":" in source_id else "default"
        rows.append({
            "id": f"{kind}:{account}",
            "sourceId": source_id,
            "source": kind,
            "account_id": account or "default",
            "name": str(entry.get("label") or kind),
            "pluginId": str(entry.get("pluginId") or ""),
        })
    return rows


def select_sources(available: list[dict], selectors=None) -> list[dict]:
    """Same contract as the Core registry: None/['all'] means every source."""
    if selectors is None or selectors == ["all"]:
        return list(available)
    if not isinstance(selectors, list) or not selectors or any(not isinstance(v, str) for v in selectors):
        raise ValueError("sources 必须是非空来源列表；省略或 ['all'] 表示全部")
    valid = {row["id"] for row in available} | {row["source"] for row in available}
    if any(value not in valid for value in selectors):
        raise ValueError("来源不存在或未配置，请先查询可用来源")
    return [row for row in available if row["id"] in selectors or row["source"] in selectors]
