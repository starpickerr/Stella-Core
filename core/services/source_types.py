"""Shared source envelopes for host Briefing adapters and domain facades.

These types are Core-owned so email/elearning facades do not import private
``agent.briefing`` modules. Host pipeline adapters re-export from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, runtime_checkable


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
        """Normalize a source result for the shared source_items catalog."""
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


@runtime_checkable
class Source(Protocol):
    name: str
    account_id: str

    def fetch(self, cursors: Dict[str, str]) -> FetchResult:
        """Return new items since ``cursors``. Do not persist anything."""
        ...
