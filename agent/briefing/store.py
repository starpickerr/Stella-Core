"""SQLite persistence for the briefing module.

On construct, the store checks whether the database file exists:
- missing file → create parent dirs, apply schema.sql, log a new database
- existing file → apply schema.sql with IF NOT EXISTS (no-op for current tables)

Callers pass and receive dataclasses from ``agent.briefing.models``.
This layer does not validate product rules; SQLite constraints still apply.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from agent.briefing.models import (
    Briefing,
    BriefingItem,
    EmailMessage,
    FilterRule,
    SourceItem,
    SyncCursor,
)
from common.log import logger

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_SOURCE_ITEM_SELECT = """
SELECT
    s.id, s.source, s.account_id, s.source_id, s.thread_id,
    s.sender, s.title, s.snippet, s.occurred_at, s.url, s.payload,
    s.created_at, s.updated_at,
    e.sender_email, e.list_id
FROM source_items s
LEFT JOIN email_messages e ON e.source_item_id = s.id
"""


def load_schema_sql() -> str:
    return _SCHEMA_PATH.read_text(encoding="utf-8")


def _dump_payload(payload: dict) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))


def _parse_payload(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _source_from_row(row: sqlite3.Row) -> Tuple[SourceItem, Optional[EmailMessage]]:
    item = SourceItem(
        id=row["id"],
        source=row["source"],
        account_id=row["account_id"],
        source_id=row["source_id"],
        thread_id=row["thread_id"],
        sender=row["sender"],
        title=row["title"],
        snippet=row["snippet"],
        occurred_at=row["occurred_at"],
        url=row["url"],
        payload=_parse_payload(row["payload"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
    email = None
    if row["sender_email"] is not None:
        email = EmailMessage(
            source_item_id=row["id"],
            sender_email=row["sender_email"],
            list_id=row["list_id"] or "",
        )
    return item, email


def _briefing_from_row(row: sqlite3.Row) -> Briefing:
    return Briefing(
        id=row["id"],
        kind=row["kind"],
        status=row["status"],
        title=row["title"],
        body=row["body"],
        fetched_count=row["fetched_count"],
        kept_count=row["kept_count"],
        filtered_count=row["filtered_count"],
        error_message=row["error_message"],
        generated_at=row["generated_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _item_from_row(row: sqlite3.Row) -> BriefingItem:
    return BriefingItem(
        id=row["id"],
        briefing_id=row["briefing_id"],
        source=row["source"],
        account_id=row["account_id"],
        source_id=row["source_id"],
        thread_id=row["thread_id"],
        section=row["section"],
        status=row["status"],
        score=row["score"],
        sender=row["sender"],
        title=row["title"],
        snippet=row["snippet"],
        occurred_at=row["occurred_at"],
        url=row["url"],
        sort_order=row["sort_order"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        source_item_id=row["source_item_id"],
        payload=_parse_payload(row["payload"]),
    )


def _rule_from_row(row: sqlite3.Row) -> FilterRule:
    return FilterRule(
        id=row["id"],
        enabled=bool(row["enabled"]),
        source=row["source"],
        action=row["action"],
        match_field=row["match_field"],
        match_op=row["match_op"],
        match_value=row["match_value"],
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _cursor_from_row(row: sqlite3.Row) -> SyncCursor:
    return SyncCursor(
        source=row["source"],
        account_id=row["account_id"],
        cursor_key=row["cursor_key"],
        cursor_value=row["cursor_value"],
        updated_at=row["updated_at"],
    )


class BriefingStore:
    """SQLite-backed store. Schema is applied on every open so a new file
    is created automatically, and an existing file is left intact."""

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._lock = threading.RLock()
        self.run_lock = threading.Lock()
        self.created_new = not self._db_path.exists()
        self._init_db()

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._raw_connect()
        try:
            conn.executescript(load_schema_sql())
            conn.commit()
        finally:
            conn.close()
        if self.created_new:
            logger.info(f"[BriefingStore] Created new briefing database at {self._db_path}")
        else:
            logger.info(f"[BriefingStore] Using existing briefing database at {self._db_path}")

    def table_names(self) -> set:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            return {row[0] for row in rows}

    def _raw_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._raw_connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _fetch_source(
        self, conn: sqlite3.Connection, clause: str, args: tuple
    ) -> Optional[Tuple[SourceItem, Optional[EmailMessage]]]:
        row = conn.execute(_SOURCE_ITEM_SELECT + " WHERE " + clause, args).fetchone()
        return _source_from_row(row) if row else None

    def _upsert_email(
        self, conn: sqlite3.Connection, source_item_id: str, email: EmailMessage
    ) -> None:
        conn.execute(
            """
            INSERT INTO email_messages (source_item_id, sender_email, list_id)
            VALUES (?, ?, ?)
            ON CONFLICT(source_item_id) DO UPDATE SET
                sender_email = excluded.sender_email,
                list_id = excluded.list_id
            """,
            (source_item_id, email.sender_email, email.list_id),
        )

    # ------------------------------------------------------------------
    # Source catalog
    # ------------------------------------------------------------------

    def upsert_source_item(
        self, item: SourceItem, email: Optional[EmailMessage] = None
    ) -> Tuple[SourceItem, Optional[EmailMessage]]:
        payload = _dump_payload(item.payload)
        with self._conn() as conn:
            existing = conn.execute(
                """
                SELECT id FROM source_items
                WHERE source = ? AND account_id = ? AND source_id = ?
                """,
                (item.source, item.account_id, item.source_id),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO source_items (
                        id, source, account_id, source_id, thread_id,
                        sender, title, snippet, occurred_at, url, payload,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.source,
                        item.account_id,
                        item.source_id,
                        item.thread_id,
                        item.sender,
                        item.title,
                        item.snippet,
                        item.occurred_at,
                        item.url,
                        payload,
                        item.created_at,
                        item.updated_at,
                    ),
                )
                persisted_id = item.id
            else:
                persisted_id = existing["id"]
                conn.execute(
                    """
                    UPDATE source_items SET
                        thread_id = ?, sender = ?, title = ?, snippet = ?,
                        occurred_at = ?, url = ?, payload = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        item.thread_id,
                        item.sender,
                        item.title,
                        item.snippet,
                        item.occurred_at,
                        item.url,
                        payload,
                        item.updated_at,
                        persisted_id,
                    ),
                )
            if email is not None:
                self._upsert_email(conn, persisted_id, email)
            found = self._fetch_source(conn, "s.id = ?", (persisted_id,))
        assert found is not None
        return found

    def get_source_item(
        self, item_id: str
    ) -> Optional[Tuple[SourceItem, Optional[EmailMessage]]]:
        with self._conn() as conn:
            return self._fetch_source(conn, "s.id = ?", (item_id,))

    def get_source_item_by_key(
        self, source: str, account_id: str, source_id: str
    ) -> Optional[Tuple[SourceItem, Optional[EmailMessage]]]:
        with self._conn() as conn:
            return self._fetch_source(
                conn,
                "s.source = ? AND s.account_id = ? AND s.source_id = ?",
                (source, account_id, source_id),
            )

    # ------------------------------------------------------------------
    # Briefings
    # ------------------------------------------------------------------

    def upsert_briefing(self, briefing: Briefing) -> Briefing:
        with self._conn() as conn:
            self._write_briefing(conn, briefing)
        found = self.get_briefing(briefing.id)
        assert found is not None
        return found

    def _write_briefing(self, conn: sqlite3.Connection, briefing: Briefing) -> None:
        conn.execute(
            """
            INSERT INTO briefings (
                id, kind, status, title, body,
                fetched_count, kept_count, filtered_count, error_message,
                generated_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                kind = excluded.kind,
                status = excluded.status,
                title = excluded.title,
                body = excluded.body,
                fetched_count = excluded.fetched_count,
                kept_count = excluded.kept_count,
                filtered_count = excluded.filtered_count,
                error_message = excluded.error_message,
                generated_at = excluded.generated_at,
                updated_at = excluded.updated_at
            """,
            (
                briefing.id,
                briefing.kind,
                briefing.status,
                briefing.title,
                briefing.body,
                briefing.fetched_count,
                briefing.kept_count,
                briefing.filtered_count,
                briefing.error_message,
                briefing.generated_at,
                briefing.created_at,
                briefing.updated_at,
            ),
        )

    def get_briefing(self, briefing_id: str) -> Optional[Briefing]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM briefings WHERE id = ?", (briefing_id,)
            ).fetchone()
            return _briefing_from_row(row) if row else None

    def list_briefings(
        self, kind: Optional[str] = None, status: Optional[str] = None
    ) -> List[Briefing]:
        clauses: List[str] = []
        args: list = []
        if kind is not None:
            clauses.append("kind = ?")
            args.append(kind)
        if status is not None:
            clauses.append("status = ?")
            args.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM briefings {where}
                ORDER BY substr(id, 5, 10) DESC, generated_at DESC, created_at DESC, id DESC
                """,
                args,
            ).fetchall()
            return [_briefing_from_row(row) for row in rows]

    def save_snapshot(self, briefing: Briefing, items: Optional[List[BriefingItem]]) -> None:
        """Commit the document and cards together, or leave both intact."""
        with self._conn() as conn:
            self._write_briefing(conn, briefing)
            if items is not None:
                self._replace_items(conn, briefing.id, items)

    def replace_briefing_items(self, briefing_id: str, items: List[BriefingItem]) -> None:
        with self._conn() as conn:
            self._replace_items(conn, briefing_id, items)

    def _replace_items(self, conn: sqlite3.Connection, briefing_id: str,
                       items: List[BriefingItem]) -> None:
        conn.execute(
            "DELETE FROM briefing_items WHERE briefing_id = ?", (briefing_id,)
        )
        conn.executemany(
            """
            INSERT INTO briefing_items (
                id, briefing_id, source_item_id, source, account_id, source_id,
                thread_id, section, status, score, sender, title, snippet,
                occurred_at, url, payload, sort_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.id,
                    briefing_id,
                    item.source_item_id,
                    item.source,
                    item.account_id,
                    item.source_id,
                    item.thread_id,
                    item.section,
                    item.status,
                    item.score,
                    item.sender,
                    item.title,
                    item.snippet,
                    item.occurred_at,
                    item.url,
                    _dump_payload(item.payload),
                    item.sort_order,
                    item.created_at,
                    item.updated_at,
                )
                for item in items
            ],
        )

    def add_candidates(self, briefing_id: str, item_ids: List[str]) -> None:
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO briefing_candidates (briefing_id, source_item_id) VALUES (?, ?)",
                [(briefing_id, item_id) for item_id in item_ids],
            )

    def list_candidates(self, briefing_id: str) -> List[Tuple[SourceItem, Optional[EmailMessage]]]:
        with self._conn() as conn:
            rows = conn.execute(
                _SOURCE_ITEM_SELECT + " JOIN briefing_candidates c ON c.source_item_id = s.id"
                " WHERE c.briefing_id = ? ORDER BY s.occurred_at, s.id",
                (briefing_id,),
            ).fetchall()
            return [_source_from_row(row) for row in rows]

    def list_briefing_items(self, briefing_id: str) -> List[BriefingItem]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM briefing_items
                WHERE briefing_id = ?
                ORDER BY section ASC, sort_order ASC, id ASC
                """,
                (briefing_id,),
            ).fetchall()
            return [_item_from_row(row) for row in rows]

    def update_item_status(
        self, item_id: str, status: str, updated_at: str
    ) -> Optional[BriefingItem]:
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE briefing_items
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, updated_at, item_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM briefing_items WHERE id = ?", (item_id,)
            ).fetchone()
            return _item_from_row(row) if row else None

    # ------------------------------------------------------------------
    # Filter rules
    # ------------------------------------------------------------------

    def insert_rule(self, rule: FilterRule) -> FilterRule:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO filter_rules (
                    id, enabled, source, action, match_field, match_op, match_value,
                    note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.id,
                    1 if rule.enabled else 0,
                    rule.source,
                    rule.action,
                    rule.match_field,
                    rule.match_op,
                    rule.match_value,
                    rule.note,
                    rule.created_at,
                    rule.updated_at,
                ),
            )
        found = self.get_rule(rule.id)
        assert found is not None
        return found

    def get_rule(self, rule_id: str) -> Optional[FilterRule]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM filter_rules WHERE id = ?", (rule_id,)
            ).fetchone()
            return _rule_from_row(row) if row else None

    def list_rules(
        self, enabled_only: bool = False, source: Optional[str] = None
    ) -> List[FilterRule]:
        clauses: List[str] = []
        args: list = []
        if enabled_only:
            clauses.append("enabled = 1")
        if source is not None:
            clauses.append("(source = ? OR source = '*')")
            args.append(source)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM filter_rules {where}
                ORDER BY created_at ASC, id ASC
                """,
                args,
            ).fetchall()
            return [_rule_from_row(row) for row in rows]

    def update_rule(self, rule: FilterRule) -> Optional[FilterRule]:
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE filter_rules SET
                    enabled = ?, source = ?, action = ?, match_field = ?,
                    match_op = ?, match_value = ?, note = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    1 if rule.enabled else 0,
                    rule.source,
                    rule.action,
                    rule.match_field,
                    rule.match_op,
                    rule.match_value,
                    rule.note,
                    rule.updated_at,
                    rule.id,
                ),
            )
            if cur.rowcount == 0:
                return None
        return self.get_rule(rule.id)

    def delete_rule(self, rule_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM filter_rules WHERE id = ?", (rule_id,)
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Sync cursors
    # ------------------------------------------------------------------

    def get_cursor(
        self, source: str, account_id: str, cursor_key: str
    ) -> Optional[SyncCursor]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM sync_state
                WHERE source = ? AND account_id = ? AND cursor_key = ?
                """,
                (source, account_id, cursor_key),
            ).fetchone()
            return _cursor_from_row(row) if row else None

    def set_cursor(self, cursor: SyncCursor) -> SyncCursor:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (
                    source, account_id, cursor_key, cursor_value, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source, account_id, cursor_key) DO UPDATE SET
                    cursor_value = excluded.cursor_value,
                    updated_at = excluded.updated_at
                """,
                (
                    cursor.source,
                    cursor.account_id,
                    cursor.cursor_key,
                    cursor.cursor_value,
                    cursor.updated_at,
                ),
            )
        found = self.get_cursor(cursor.source, cursor.account_id, cursor.cursor_key)
        assert found is not None
        return found


_store_instances: Dict[str, BriefingStore] = {}
_store_lock = threading.RLock()


def get_briefing_store(db_path: Optional[Path] = None) -> BriefingStore:
    """Return the briefing store for ``db_path``, creating the file if missing.

    Omitting ``db_path`` uses the current identity's briefing database under
    the user workspace (``<user>/briefing/briefing.db`` on a single-agent
    install).
    """
    if db_path is None:
        from common.state_dir import briefing_db

        db_path = briefing_db()
    key = str(Path(db_path).resolve())
    store = _store_instances.get(key)
    if store is not None:
        return store
    with _store_lock:
        store = _store_instances.get(key)
        if store is None:
            store = BriefingStore(Path(db_path))
            _store_instances[key] = store
        return store


def clear_briefing_store_cache() -> None:
    """Forget cached store objects. Intended for tests."""
    with _store_lock:
        _store_instances.clear()
