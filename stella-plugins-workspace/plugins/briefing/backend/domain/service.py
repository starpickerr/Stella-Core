"""Business logic for the briefing module.

The store talks to SQLite. This layer validates input, assigns ids and
timestamps, and exposes the operations the UI / agent tool / pipeline call:
look up a briefing, change item status, manage rules, upsert the source
catalog, and persist a finished run.

Fetching sources and generating Markdown live in pipeline.py / generator.py.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime, timezone
from typing import Any, List, Optional, Tuple

from .models import (
    Briefing,
    BriefingItem,
    EmailMessage,
    FilterRule,
    SourceItem,
    SyncCursor,
)
from .store import BriefingStore

_BRIEFING_STATUSES = {"running", "completed", "failed", "partial"}
_ITEM_SECTIONS = {"action", "fyi"}
_ITEM_STATUSES = {"undo", "done", "ignored", "follow_up"}
_RULE_ACTIONS = {"include", "exclude"}
_RULE_FIELDS = {"sender", "sender_email", "sender_domain", "title", "list_id"}
_RULE_OPS = {"eq", "contains"}
_FINISH_STATUSES = {"completed", "failed", "partial"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_occurred_at(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("occurred_at is required")
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid occurred_at: {value}") from exc


def parse_date(value: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("date is required")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"invalid date: {value}") from exc


def briefing_id_for(briefing_date: str) -> str:
    day = parse_date(briefing_date)
    return f"brf-{day.isoformat()}"


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _nonneg_int(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer") from None
    if number < 0:
        raise ValueError(f"{name} must be >= 0")
    return number


def _score(value: Any) -> int:
    number = _nonneg_int(value, "score")
    if number > 100:
        raise ValueError("score must be between 0 and 100")
    return number


def _payload_dict(value: Any) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("payload must be an object")
    return value


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if value in (0, 1, "0", "1"):
        return bool(int(value))
    raise ValueError("enabled must be true or false")


class BriefingService:
    def __init__(self, store: BriefingStore, todos=None, calendar=None):
        self.store = store
        self._todos = todos
        self._calendar = calendar

    # ------------------------------------------------------------------
    # Briefings
    # ------------------------------------------------------------------

    def list_briefings(
        self, status: Optional[str] = None
    ) -> List[Briefing]:
        if status is not None and status not in _BRIEFING_STATUSES:
            raise ValueError("status must be running, completed, failed, or partial")
        return self.store.list_briefings(status=status)

    def get_briefing(self, briefing_id: str) -> Optional[dict]:
        briefing = self.store.get_briefing(briefing_id)
        if briefing is None:
            return None
        detail = {
            "briefing": briefing,
            "items": self.store.list_briefing_items(briefing_id),
            "revisions": self.store.list_revisions(briefing_id),
            "mail": self.store.list_mail(briefing_id),
        }
        detail["actions"] = self.actions.view(detail["items"])
        detail["preferences"] = self.actions.preferences()
        return detail

    def get_revision(self, briefing_id: str, number: int) -> dict:
        snapshot = self.store.get_revision(briefing_id, number)
        if snapshot is None:
            raise KeyError("briefing revision not found")
        snapshot.setdefault("mail", [])
        snapshot["briefing"].setdefault("mail_snapshot_available", False)
        snapshot["briefing"].setdefault("rule_text", "")
        snapshot["briefing"].setdefault("source_windows", {})
        snapshot["briefing"].setdefault("updated_sources", [])
        snapshot["revisions"] = self.store.list_revisions(briefing_id)
        snapshot["actions"] = self.actions.view(snapshot["items"])
        snapshot["preferences"] = self.actions.preferences()
        return snapshot

    def briefing_for_date(self, briefing_date: str) -> Optional[Briefing]:
        briefing_id = briefing_id_for(briefing_date)
        return (self.store.get_briefing(briefing_id)
                or self.store.get_briefing(briefing_id + "-morning"))

    def start_briefing(
        self,
        briefing_date: Optional[str] = None,
        title: str = "",
    ) -> Briefing:
        day = parse_date(briefing_date) if briefing_date else date.today()
        briefing_id = briefing_id_for(day.isoformat())
        now = _now_iso()
        existing = self.briefing_for_date(day.isoformat())
        if existing is None:
            return self.store.upsert_briefing(
                Briefing(
                    id=briefing_id,
                    status="running",
                    title=title.strip(),
                    body="",
                    fetched_count=0,
                    kept_count=0,
                    filtered_count=0,
                    error_message="",
                    generated_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.store.upsert_briefing(
            Briefing(
                id=existing.id,
                status="running",
                title=title.strip() or existing.title,
                body=existing.body,
                fetched_count=existing.fetched_count,
                kept_count=existing.kept_count,
                filtered_count=existing.filtered_count,
                error_message=existing.error_message,
                generated_at=existing.generated_at,
                created_at=existing.created_at,
                updated_at=now,
                window_start=existing.window_start,
                window_end=existing.window_end,
                mail_snapshot_available=existing.mail_snapshot_available,
                rule_text=existing.rule_text,
                source_windows=existing.source_windows,
                updated_sources=existing.updated_sources,
            )
        )

    def complete_briefing(self, briefing_id: str, payload: dict) -> dict:
        existing = self.store.get_briefing(briefing_id)
        if existing is None:
            raise KeyError(f"briefing not found: {briefing_id}")
        if not isinstance(payload, dict):
            raise ValueError("briefing payload must be an object")

        status = payload.get("status", "completed")
        if status not in _FINISH_STATUSES:
            raise ValueError("status must be completed, failed, or partial")

        now = payload.get("run_at") or _now_iso()
        finished = Briefing(
            id=existing.id,
            status=status,
            title=_as_str(payload.get("title", existing.title)),
            body=_as_str(payload.get("body", existing.body)),
            fetched_count=_nonneg_int(
                payload.get("fetched_count", existing.fetched_count),
                "fetched_count",
            ),
            kept_count=_nonneg_int(
                payload.get("kept_count", existing.kept_count), "kept_count"
            ),
            filtered_count=_nonneg_int(
                payload.get("filtered_count", existing.filtered_count),
                "filtered_count",
            ),
            error_message=_as_str(
                payload.get("error_message", existing.error_message)
            ),
            generated_at=now if status != "failed" else existing.generated_at,
            created_at=existing.created_at,
            updated_at=now,
            window_start=payload.get("window_start", existing.window_start) if status != "failed" else existing.window_start,
            window_end=payload.get("window_end", existing.window_end) if status != "failed" else existing.window_end,
            mail_snapshot_available=True if "mail" in payload else existing.mail_snapshot_available,
            rule_text=_as_str(payload.get("rule_text", existing.rule_text)) if status != "failed" else existing.rule_text,
            source_windows=payload.get("source_windows", existing.source_windows) if status != "failed" else existing.source_windows,
            updated_sources=payload.get("updated_sources", existing.updated_sources) if status != "failed" else existing.updated_sources,
        )
        snapshots = None
        staged_run_id = payload.get("staged_run_id") if status != "failed" else None
        staged_sources = self.store.staged_source_map(staged_run_id) if staged_run_id else {}
        if "items" in payload:
            raw_items = payload.get("items")
            if not isinstance(raw_items, list):
                raise ValueError("items must be a list")
            snapshots = [
                self._build_snapshot_item(briefing_id, raw, index, now, staged_sources)
                for index, raw in enumerate(raw_items)
            ]
            previous = {
                (item.source, item.account_id, item.source_id): item
                for item in self.store.list_briefing_items(briefing_id)
            }
            for index, item in enumerate(snapshots):
                old = previous.get((item.source, item.account_id, item.source_id))
                if old is not None:
                    item.id = old.id
                    item.created_at = old.created_at
                    if "status" not in raw_items[index]:
                        item.status = old.status
        mail = payload.get("mail")
        if "mail" in payload:
            if not isinstance(mail, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]
                or row.get("category") not in {"selected", "filtered"} for row in mail
            ):
                raise ValueError("mail must be a list of classified candidate snapshots")
        self.store.save_snapshot(finished, snapshots, payload.get("trigger", "manual"), mail,
                                 payload.get("cursor_updates"), staged_run_id)
        detail = self.get_briefing(briefing_id)
        assert detail is not None
        if status != "failed":
            self.actions.prepare(detail)
            detail["actions"] = self.actions.view(detail["items"])
        return detail

    def update_item_status(self, item_id: str, status: str) -> BriefingItem:
        if status not in _ITEM_STATUSES:
            raise ValueError("status must be undo, done, ignored, or follow_up")
        updated = self.store.update_item_status(item_id, status, _now_iso())
        if updated is None:
            raise KeyError(f"briefing item not found: {item_id}")
        return updated

    # ------------------------------------------------------------------
    # Source catalog
    # ------------------------------------------------------------------

    def upsert_source_item(
        self, payload: dict
    ) -> Tuple[SourceItem, Optional[EmailMessage]]:
        item, email = self._build_source_item(payload)
        return self.store.upsert_source_item(item, email)

    def build_source_item(self, payload: dict) -> Tuple[SourceItem, Optional[EmailMessage]]:
        return self._build_source_item(payload)

    # ------------------------------------------------------------------
    # Filter rules
    # ------------------------------------------------------------------

    def list_rules(
        self, enabled_only: bool = False, source: Optional[str] = None
    ) -> List[FilterRule]:
        return self.store.list_rules(enabled_only=enabled_only, source=source)

    def get_rule(self, rule_id: str) -> Optional[FilterRule]:
        return self.store.get_rule(rule_id)

    def create_rule(self, payload: dict) -> FilterRule:
        rule = self._build_rule(payload, existing=None)
        try:
            return self.store.insert_rule(rule)
        except sqlite3.IntegrityError as exc:
            raise ValueError("a rule with the same match already exists") from exc

    def update_rule(self, rule_id: str, payload: dict) -> FilterRule:
        existing = self.store.get_rule(rule_id)
        if existing is None:
            raise KeyError(f"filter rule not found: {rule_id}")
        rule = self._build_rule(payload, existing=existing)
        try:
            saved = self.store.update_rule(rule)
        except sqlite3.IntegrityError as exc:
            raise ValueError("a rule with the same match already exists") from exc
        if saved is None:
            raise KeyError(f"filter rule not found: {rule_id}")
        return saved

    def delete_rule(self, rule_id: str) -> None:
        if not self.store.delete_rule(rule_id):
            raise KeyError(f"filter rule not found: {rule_id}")

    # ------------------------------------------------------------------
    # Sync cursors
    # ------------------------------------------------------------------

    def get_cursor(
        self, source: str, account_id: str, cursor_key: str
    ) -> Optional[SyncCursor]:
        if not source or not cursor_key:
            raise ValueError("source and cursor_key are required")
        return self.store.get_cursor(source, account_id or "default", cursor_key)

    def set_cursor(
        self,
        source: str,
        cursor_key: str,
        cursor_value: str,
        account_id: str = "default",
    ) -> SyncCursor:
        if not source or not cursor_key:
            raise ValueError("source and cursor_key are required")
        return self.store.set_cursor(
            SyncCursor(
                source=source,
                account_id=account_id or "default",
                cursor_key=cursor_key,
                cursor_value=_as_str(cursor_value),
                updated_at=_now_iso(),
            )
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_source_item(
        self, payload: dict
    ) -> Tuple[SourceItem, Optional[EmailMessage]]:
        if not isinstance(payload, dict):
            raise ValueError("source payload must be an object")
        source = _as_str(payload.get("source")).strip()
        source_id = _as_str(payload.get("source_id")).strip()
        if not source or not source_id:
            raise ValueError("source and source_id are required")
        account_id = _as_str(payload.get("account_id"), "default").strip() or "default"
        occurred_at = payload.get("occurred_at")
        parse_occurred_at(occurred_at)

        existing = self.store.get_source_item_by_key(source, account_id, source_id)
        now = _now_iso()
        item_id = existing[0].id if existing else _as_str(payload.get("id")).strip()
        if not item_id:
            item_id = f"src-{uuid.uuid4()}"
        created_at = existing[0].created_at if existing else now
        item = SourceItem(
            id=item_id,
            source=source,
            account_id=account_id,
            source_id=source_id,
            thread_id=_as_str(payload.get("thread_id")),
            sender=_as_str(payload.get("sender")),
            title=_as_str(payload.get("title")),
            snippet=_as_str(payload.get("snippet")),
            occurred_at=occurred_at,
            url=_as_str(payload.get("url")),
            payload=_payload_dict(payload.get("payload")),
            created_at=created_at,
            updated_at=now,
        )
        email = None
        if source == "email" or "sender_email" in payload or "list_id" in payload:
            email = EmailMessage(
                source_item_id=item_id,
                sender_email=_as_str(payload.get("sender_email")),
                list_id=_as_str(payload.get("list_id")),
            )
            if source != "email":
                email = None
        return item, email

    def _build_snapshot_item(
        self, briefing_id: str, payload: Any, index: int, now: str,
        staged_sources=None,
    ) -> BriefingItem:
        if not isinstance(payload, dict):
            raise ValueError("each briefing item must be an object")
        catalog: Optional[SourceItem] = None
        source_item_id = payload.get("source_item_id")
        if source_item_id:
            catalog = (staged_sources or {}).get(str(source_item_id))
            found = None if catalog else self.store.get_source_item(str(source_item_id))
            if catalog is None and found is None:
                raise ValueError(f"source item not found: {source_item_id}")
            catalog = catalog or found[0]
            source_item_id = catalog.id
        else:
            source_item_id = None

        source = _as_str(payload.get("source"), catalog.source if catalog else "").strip()
        source_id = _as_str(
            payload.get("source_id"), catalog.source_id if catalog else ""
        ).strip()
        if not source or not source_id:
            raise ValueError("item source and source_id are required")
        occurred_at = payload.get(
            "occurred_at", catalog.occurred_at if catalog else None
        )
        parse_occurred_at(occurred_at)

        section = payload.get("section", "fyi")
        if section not in _ITEM_SECTIONS:
            raise ValueError("section must be action or fyi")
        status = payload.get("status", "undo")
        if status not in _ITEM_STATUSES:
            raise ValueError("status must be undo, done, ignored, or follow_up")

        item_id = _as_str(payload.get("id")).strip() or f"bit-{uuid.uuid4()}"
        return BriefingItem(
            id=item_id,
            briefing_id=briefing_id,
            source=source,
            account_id=_as_str(
                payload.get("account_id"),
                catalog.account_id if catalog else "default",
            )
            or "default",
            source_id=source_id,
            thread_id=_as_str(
                payload.get("thread_id"), catalog.thread_id if catalog else ""
            ),
            section=section,
            status=status,
            score=_score(payload.get("score", 0)),
            sender=_as_str(payload.get("sender"), catalog.sender if catalog else ""),
            title=_as_str(payload.get("title"), catalog.title if catalog else ""),
            snippet=_as_str(payload.get("snippet"), catalog.snippet if catalog else ""),
            occurred_at=occurred_at,
            url=_as_str(payload.get("url"), catalog.url if catalog else ""),
            sort_order=_nonneg_int(payload.get("sort_order", index), "sort_order"),
            created_at=now,
            updated_at=now,
            source_item_id=source_item_id,
            payload=_payload_dict(
                payload.get("payload", catalog.payload if catalog else None)
            ),
        )

    def _build_rule(self, payload: dict, existing: Optional[FilterRule]) -> FilterRule:
        if not isinstance(payload, dict):
            raise ValueError("rule payload must be an object")
        legacy_fields = {"action", "match_field", "match_op", "match_value", "note"}
        if "text" in payload or (existing and existing.text and not legacy_fields.intersection(payload)):
            text = payload.get("text", existing.text if existing else "")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("请填写规则文稿")
            now = _now_iso()
            rule_id = existing.id if existing else f"rul-{uuid.uuid4()}"
            return FilterRule(
                id=rule_id, text=text.strip(),
                enabled=_as_bool(payload.get("enabled"), existing.enabled if existing else True),
                source=_as_str(payload.get("source", existing.source if existing else "*")).strip() or "*",
                # Keep legacy schema columns for compatible database upgrades.
                action=existing.action if existing else "exclude",
                match_field=existing.match_field if existing else "title",
                match_op=existing.match_op if existing else "contains",
                match_value=existing.match_value if existing else rule_id,
                note=existing.note if existing else "",
                created_at=existing.created_at if existing else now, updated_at=now,
            )
        action = payload.get("action", existing.action if existing else None)
        if action not in _RULE_ACTIONS:
            raise ValueError("action must be include or exclude")
        match_field = payload.get(
            "match_field", existing.match_field if existing else None
        )
        if match_field not in _RULE_FIELDS:
            raise ValueError(
                "match_field must be sender, sender_email, sender_domain, title, or list_id"
            )
        match_op = payload.get("match_op", existing.match_op if existing else "eq")
        if match_op not in _RULE_OPS:
            raise ValueError("match_op must be eq or contains")
        match_value = _as_str(
            payload.get("match_value", existing.match_value if existing else "")
        ).strip()
        if not match_value:
            raise ValueError("match_value is required")
        now = _now_iso()
        return FilterRule(
            id=(
                existing.id
                if existing
                else (_as_str(payload.get("id")).strip() or f"rul-{uuid.uuid4()}")
            ),
            enabled=_as_bool(
                payload.get("enabled"), existing.enabled if existing else True
            ),
            source=_as_str(
                payload.get("source", existing.source if existing else "*")
            ).strip()
            or "*",
            action=action,
            match_field=match_field,
            match_op=match_op,
            match_value=match_value,
            note=_as_str(payload.get("note", existing.note if existing else "")),
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )


    @property
    def actions(self):
        if not hasattr(self, "_actions"):
            from .actions import BriefingActions
            self._actions = BriefingActions(self.store, self._todos, self._calendar)
        return self._actions

    def update_action(self, item_id, payload):
        return self.actions.decide(item_id, payload)

    def get_overview(self):
        actions = self.actions
        items = self.store.latest_tracked_items()
        return {'items': items, 'actions': actions.view(items), 'preferences': actions.preferences()}

    def list_action_rules(self):
        return self.actions.list_rules()

    def create_action_rule(self, payload):
        return self.actions.save_rule(payload)

    def delete_action_rule(self, rule_id):
        return self.actions.delete_rule(rule_id)

    def get_preferences(self):
        return self.actions.preferences()

    def update_preferences(self, payload):
        return self.actions.preferences(payload)

    def get_action_targets(self, kind, query=""):
        if kind not in {"todo", "calendar"}:
            raise ValueError("invalid target type")
        if not isinstance(query, str) or len(query) > 300:
            raise ValueError("invalid search query")
        self.actions.require_adapters("get_action_targets")
        if kind == "todo":
            rows = self.actions.todos.list_todos(include_completed=True)
        else:
            rows = self.actions.calendar.list_events()
        return [row for row in rows if query.casefold() in row["title"].casefold()][:50]
