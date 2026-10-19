"""Domain shapes for the briefing module.

These are in-memory records, not ORM. SQLite schema lives in schema.sql.
source_items is the catalog envelope; BriefingItem is a snapshot copied onto
a briefing. Email-private fields live on EmailMessage, not on the envelope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

BriefingStatus = Literal["running", "completed", "failed", "partial"]
ItemSection = Literal["action", "fyi"]
ItemStatus = Literal["undo", "done", "ignored", "follow_up"]
RuleAction = Literal["include", "exclude"]
RuleMatchField = Literal[
    "sender",
    "sender_email",
    "sender_domain",
    "title",
    "list_id",
]
RuleMatchOp = Literal["eq", "contains"]


@dataclass
class SourceItem:
    """Catalog envelope: one row per (source, account_id, source_id)."""

    id: str
    source: str
    account_id: str
    source_id: str
    thread_id: str
    sender: str
    title: str
    snippet: str
    occurred_at: str
    url: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class EmailMessage:
    """Email extension, 1:1 with SourceItem (source='email')."""

    source_item_id: str
    sender_email: str = ""
    list_id: str = ""


@dataclass
class Briefing:
    id: str
    status: BriefingStatus
    title: str
    body: str
    fetched_count: int
    kept_count: int
    filtered_count: int
    error_message: str
    generated_at: Optional[str]
    created_at: str
    updated_at: str
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    mail_snapshot_available: bool = False
    rule_text: str = ""
    source_windows: dict = field(default_factory=dict)
    updated_sources: list = field(default_factory=list)


@dataclass
class BriefingItem:
    """Snapshot card on a briefing; envelope fields are copied at compose time."""

    id: str
    briefing_id: str
    source: str
    account_id: str
    source_id: str
    thread_id: str
    section: ItemSection
    status: ItemStatus
    score: int
    sender: str
    title: str
    snippet: str
    occurred_at: str
    url: str
    sort_order: int
    created_at: str
    updated_at: str
    source_item_id: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class FilterRule:
    id: str
    enabled: bool
    source: str
    action: RuleAction
    match_field: RuleMatchField
    match_op: RuleMatchOp
    match_value: str
    note: str
    created_at: str
    updated_at: str
    text: str = ""


@dataclass
class SyncCursor:
    source: str
    account_id: str
    cursor_key: str
    cursor_value: str
    updated_at: str
