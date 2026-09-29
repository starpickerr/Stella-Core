"""Source protocol: fetch incremental items, return a normalized envelope.

Adapters (email, later sms) implement ``Source.fetch``. IMAP / vendor APIs
stay inside the adapter; the pipeline only sees ``FetchedItem``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


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


@dataclass
class FetchResult:
    items: List[FetchedItem]
    cursors: Dict[str, str] = field(default_factory=dict)


@runtime_checkable
class Source(Protocol):
    name: str
    account_id: str

    def fetch(self, cursors: Dict[str, str]) -> FetchResult:
        """Return new items since ``cursors``. Do not persist anything."""
        ...
