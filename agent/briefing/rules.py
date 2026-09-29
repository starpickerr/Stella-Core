"""Built-in and user filter rules for briefing candidates.

User rules live in filter_rules. Built-ins (noreply, list-unsubscribe) stay
in this module. Semantic "looks like promo" judgments are not applied here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from agent.briefing.models import EmailMessage, FilterRule, SourceItem
from agent.briefing.sources.base import FetchedItem

_NOREPLY_MARKERS = (
    "noreply@",
    "no-reply@",
    "no_reply@",
    "donotreply@",
    "do-not-reply@",
    "mailer-daemon@",
    "notifications@",
    "@noreply.",
)
_ACTION_HINTS = (
    "请回复",
    "请确认",
    "请审批",
    "评审",
    "确认",
    "deadline",
    "review",
    "approve",
    "action required",
    "需要你",
    "asap",
)


@dataclass
class ScoredCandidate:
    item: SourceItem
    email: Optional[EmailMessage]
    section: str
    score: int
    included: bool


def sender_domain(sender_email: str) -> str:
    text = (sender_email or "").strip().casefold()
    if "@" not in text:
        return ""
    return text.rsplit("@", 1)[-1]


def field_value(
    item: SourceItem, email: Optional[EmailMessage], match_field: str
) -> str:
    if match_field == "sender":
        return item.sender
    if match_field == "title":
        return item.title
    if match_field == "sender_email":
        if email is not None:
            return email.sender_email
        return str(item.payload.get("sender_email") or "")
    if match_field == "sender_domain":
        address = email.sender_email if email is not None else str(
            item.payload.get("sender_email") or ""
        )
        return sender_domain(address)
    if match_field == "list_id":
        if email is not None and email.list_id:
            return email.list_id
        return str(item.payload.get("list_id") or "")
    return ""


def _matches(value: str, op: str, expected: str) -> bool:
    left = (value or "").casefold()
    right = (expected or "").casefold()
    if op == "eq":
        return left == right
    if op == "contains":
        return bool(right) and right in left
    return False


def _rule_applies(rule: FilterRule, source: str) -> bool:
    if not rule.enabled:
        return False
    return rule.source in ("*", source)


def builtin_drop_reason(item: SourceItem, email: Optional[EmailMessage]) -> str:
    address = ""
    if email is not None:
        address = email.sender_email
    address = (address or str(item.payload.get("sender_email") or "")).casefold()
    for marker in _NOREPLY_MARKERS:
        if marker in address:
            return "noreply"
    if item.payload.get("list_unsubscribe"):
        return "list_unsubscribe"
    return ""


def decide(
    item: SourceItem,
    email: Optional[EmailMessage],
    rules: Sequence[FilterRule],
) -> Tuple[bool, bool, str]:
    """Return (keep, included_by_whitelist, drop_reason)."""
    applicable = [rule for rule in rules if _rule_applies(rule, item.source)]
    for rule in applicable:
        if rule.action != "include":
            continue
        if _matches(field_value(item, email, rule.match_field), rule.match_op, rule.match_value):
            return True, True, "include"
    for rule in applicable:
        if rule.action != "exclude":
            continue
        if _matches(field_value(item, email, rule.match_field), rule.match_op, rule.match_value):
            return False, False, "exclude"
    reason = builtin_drop_reason(item, email)
    if reason:
        return False, False, reason
    return True, False, ""


def assign_section_and_score(item: SourceItem, included: bool) -> Tuple[str, int]:
    blob = f"{item.title} {item.snippet}".casefold()
    action = any(hint.casefold() in blob for hint in _ACTION_HINTS)
    section = "action" if action else "fyi"
    score = 80 if action else 40
    if included:
        score = min(100, score + 15)
    return section, score


def filter_candidates(
    rows: Iterable[Tuple[SourceItem, Optional[EmailMessage]]],
    rules: Sequence[FilterRule],
) -> Tuple[List[ScoredCandidate], int]:
    """Split upserted catalog rows into kept candidates vs filtered count."""
    kept: List[ScoredCandidate] = []
    filtered = 0
    for item, email in rows:
        keep, included, _reason = decide(item, email, rules)
        if not keep:
            filtered += 1
            continue
        section, score = assign_section_and_score(item, included)
        kept.append(
            ScoredCandidate(
                item=item, email=email, section=section, score=score, included=included
            )
        )
    return kept, filtered


def fetched_to_payload(fetched: FetchedItem) -> dict:
    payload = dict(fetched.payload)
    return {
        "source": fetched.source,
        "account_id": fetched.account_id or "default",
        "source_id": fetched.source_id,
        "thread_id": fetched.thread_id,
        "sender": fetched.sender,
        "title": fetched.title,
        "snippet": fetched.snippet,
        "occurred_at": fetched.occurred_at,
        "url": fetched.url,
        "payload": payload,
        "sender_email": fetched.sender_email,
        "list_id": fetched.list_id,
    }
