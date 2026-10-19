"""Resource document shape reused from elearning_crawler."""
from dataclasses import dataclass, field


@dataclass
class Resource:
    course: dict
    id: str
    title: str
    summary: str
    text: str
    url: str
    timestamp: str = ""


@dataclass
class FetchedItem:
    """Normalized source item (shape of the briefing ``source_items`` envelope)."""

    source: str
    source_id: str
    account_id: str = "default"
    thread_id: str = ""
    sender: str = ""
    title: str = ""
    snippet: str = ""
    occurred_at: str = ""
    url: str = ""
    payload: dict = field(default_factory=dict)
    sender_email: str = ""
    list_id: str = ""

    def to_catalog_payload(self) -> dict:
        return {
            "source": self.source, "account_id": self.account_id or "default",
            "source_id": self.source_id, "thread_id": self.thread_id, "sender": self.sender,
            "title": self.title, "snippet": self.snippet, "occurred_at": self.occurred_at,
            "url": self.url, "payload": dict(self.payload), "sender_email": self.sender_email,
            "list_id": self.list_id,
        }


@dataclass
class FetchResult:
    items: list
    cursors: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
