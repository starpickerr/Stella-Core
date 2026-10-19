"""SQLite persistence for the briefing module.

On construct, the store checks whether the database file exists:
- missing file → create parent dirs, apply schema.sql, log a new database
- existing file → apply schema.sql with IF NOT EXISTS (no-op for current tables)

Callers pass and receive dataclasses from ``models``.
This layer does not validate product rules; SQLite constraints still apply.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .models import (
    Briefing,
    BriefingItem,
    EmailMessage,
    FilterRule,
    SourceItem,
    SyncCursor,
)
logger = logging.getLogger(__name__)

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
        window_start=row["window_start"],
        window_end=row["window_end"],
        mail_snapshot_available=bool(row["mail_snapshot_available"]),
        rule_text=row["rule_text"],
        source_windows=_parse_payload(row["source_windows"]),
        updated_sources=json.loads(row["updated_sources"]),
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
    rule = FilterRule(
        id=row["id"],
        enabled=bool(row["enabled"]),
        source=row["source"],
        action=row["action"],
        match_field=row["match_field"],
        match_op=row["match_op"],
        match_value=row["match_value"],
        note=row["note"],
        text=row["text"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
    from .instructions import rule_document
    rule.text = rule_document(rule)
    return rule


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
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS briefing_source_staging (
                    run_id TEXT NOT NULL, source TEXT NOT NULL, account_id TEXT NOT NULL,
                    source_id TEXT NOT NULL, snapshot TEXT NOT NULL, staged_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,source,account_id,source_id)
                );
                CREATE INDEX IF NOT EXISTS briefing_source_staging_age
                    ON briefing_source_staging(staged_at);
                CREATE TABLE IF NOT EXISTS briefing_source_errors (
                    run_id TEXT NOT NULL, source TEXT NOT NULL, account_id TEXT NOT NULL,
                    errors TEXT NOT NULL, staged_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,source,account_id)
                );
                CREATE INDEX IF NOT EXISTS briefing_source_errors_age
                    ON briefing_source_errors(staged_at);
                CREATE TABLE IF NOT EXISTS briefing_outbox (
                    briefing_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    snapshot TEXT NOT NULL, calendar_ack_at TEXT, todo_ack_at TEXT,
                    calendar_error TEXT, todo_error TEXT,
                    PRIMARY KEY(briefing_id,revision)
                );
                CREATE INDEX IF NOT EXISTS briefing_outbox_pending
                    ON briefing_outbox(calendar_ack_at,todo_ack_at);
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(briefings)")}
            for column in ("window_start", "window_end"):
                if column not in columns:
                    conn.execute(f"ALTER TABLE briefings ADD COLUMN {column} TEXT")
            if "mail_snapshot_available" not in columns:
                conn.execute("ALTER TABLE briefings ADD COLUMN mail_snapshot_available INTEGER NOT NULL DEFAULT 0")
            if "rule_text" not in columns:
                conn.execute("ALTER TABLE briefings ADD COLUMN rule_text TEXT NOT NULL DEFAULT ''")
            if "source_windows" not in columns:
                conn.execute("ALTER TABLE briefings ADD COLUMN source_windows TEXT NOT NULL DEFAULT '{}'")
            if "updated_sources" not in columns:
                conn.execute("ALTER TABLE briefings ADD COLUMN updated_sources TEXT NOT NULL DEFAULT '[]'")
            rule_columns = {row[1] for row in conn.execute("PRAGMA table_info(filter_rules)")}
            if "text" not in rule_columns:
                conn.execute("ALTER TABLE filter_rules ADD COLUMN text TEXT NOT NULL DEFAULT ''")
            # Retire the legacy type without rewriting IDs, foreign keys or
            # immutable snapshots. SQLite rolls back this migration on failure.
            if "kind" in columns:
                conn.execute("BEGIN")
                conn.execute("DROP INDEX IF EXISTS idx_briefings_kind_generated")
                conn.execute("ALTER TABLE briefings DROP COLUMN kind")
            # Preserve the surviving pre-upgrade snapshot; older overwritten runs
            # cannot be reconstructed. Normalize titles without changing ids.
            for row in conn.execute("SELECT * FROM briefings ORDER BY generated_at").fetchall():
                if row["id"].endswith("-morning"):
                    day = datetime.strptime(row["id"][4:14], "%Y-%m-%d")
                    conn.execute("UPDATE briefings SET title=? WHERE id=?",
                                 (f"{day.year}年{day.month}月{day.day}日·简报", row["id"]))
                if not row["generated_at"]:
                    continue
                if not row["window_end"]:
                    prior = conn.execute("SELECT window_end FROM briefings WHERE substr(id,5,10) < ? AND window_end IS NOT NULL ORDER BY julianday(window_end) DESC LIMIT 1",
                                         (row["id"][4:14],)).fetchone()
                    start = prior[0] if prior else (datetime.fromisoformat(row["generated_at"].replace("Z", "+00:00")) - timedelta(days=2)).isoformat()
                    conn.execute("UPDATE briefings SET window_start=?,window_end=? WHERE id=?", (start,row["generated_at"],row["id"]))
                if not conn.execute("SELECT 1 FROM briefing_revisions WHERE briefing_id=?", (row["id"],)).fetchone():
                    current = _briefing_from_row(conn.execute("SELECT * FROM briefings WHERE id=?", (row["id"],)).fetchone())
                    self._archive(conn, current, "legacy")
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
        with self._conn() as conn:
            persisted_id = self._upsert_source_item(conn, item, email)
            found = self._fetch_source(conn, "s.id = ?", (persisted_id,))
        assert found is not None
        return found

    def _upsert_source_item(self, conn, item, email):
        payload = _dump_payload(item.payload)
        existing = conn.execute(
            """SELECT id FROM source_items
               WHERE source = ? AND account_id = ? AND source_id = ?""",
            (item.source, item.account_id, item.source_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO source_items (
                    id, source, account_id, source_id, thread_id,
                    sender, title, snippet, occurred_at, url, payload,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item.id, item.source, item.account_id, item.source_id,
                 item.thread_id, item.sender, item.title, item.snippet,
                 item.occurred_at, item.url, payload, item.created_at, item.updated_at),
            )
            persisted_id = item.id
        else:
            persisted_id = existing["id"]
            conn.execute(
                """UPDATE source_items SET
                    thread_id = ?, sender = ?, title = ?, snippet = ?,
                    occurred_at = ?, url = ?, payload = ?, updated_at = ?
                WHERE id = ?""",
                (item.thread_id, item.sender, item.title, item.snippet,
                 item.occurred_at, item.url, payload, item.updated_at, persisted_id),
            )
        if email is not None:
            self._upsert_email(conn, persisted_id, email)
        return persisted_id

    def stage_source_items(self, run_id, rows):
        """Durably stage fetched candidates without changing the live catalog."""
        stamp = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute("DELETE FROM briefing_source_staging WHERE staged_at<?",
                         ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),))
            conn.execute("DELETE FROM briefing_source_errors WHERE staged_at<?",
                         ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),))
            for item, email in rows:
                snapshot = {"item": asdict(item), "email": asdict(email) if email else None}
                conn.execute("""INSERT INTO briefing_source_staging
                    (run_id,source,account_id,source_id,snapshot,staged_at) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(run_id,source,account_id,source_id) DO UPDATE SET
                    snapshot=excluded.snapshot,staged_at=excluded.staged_at""",
                    (run_id, item.source, item.account_id, item.source_id,
                     _dump_payload(snapshot), stamp))

    def stage_source_errors(self, run_id, source, account_id, errors):
        with self._conn() as conn:
            conn.execute("""INSERT INTO briefing_source_errors
                (run_id,source,account_id,errors,staged_at) VALUES (?,?,?,?,?)
                ON CONFLICT(run_id,source,account_id) DO UPDATE SET
                errors=excluded.errors,staged_at=excluded.staged_at""",
                (run_id, source, account_id, json.dumps(errors, ensure_ascii=False),
                 datetime.now(timezone.utc).isoformat()))

    def staged_source_map(self, run_id):
        with self._conn() as conn:
            rows = conn.execute("SELECT snapshot FROM briefing_source_staging WHERE run_id=?",
                                (run_id,)).fetchall()
        result = {}
        for row in rows:
            snapshot = json.loads(row[0])
            item = SourceItem(**snapshot["item"])
            result[item.id] = item
        return result

    def staged_window_candidates(self, run_id, start, end, accounts):
        result = {(item.source, item.account_id, item.source_id): (item, email)
                  for item, email in self.window_candidates(start, end, accounts)}
        allowed = set(accounts)
        start_at = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_at = datetime.fromisoformat(end.replace("Z", "+00:00"))
        with self._conn() as conn:
            rows = conn.execute("SELECT snapshot FROM briefing_source_staging WHERE run_id=?",
                                (run_id,)).fetchall()
        for row in rows:
            snapshot = json.loads(row[0])
            item = SourceItem(**snapshot["item"])
            key = (item.source, item.account_id, item.source_id)
            if (item.source, item.account_id) not in allowed:
                continue
            result.pop(key, None)
            occurred = datetime.fromisoformat(item.occurred_at.replace("Z", "+00:00"))
            if occurred > end_at:
                continue
            if occurred <= start_at:
                previous = self.get_source_item_by_key(item.source, item.account_id, item.source_id)
                if previous:
                    prior, _ = previous
                    keys = ("due_at", "start_at", "end_at", "submission_status", "score", "grade", "workflow_state")
                    if prior.title == item.title and all(prior.payload.get(key)==item.payload.get(key) for key in keys):
                        continue

            email = EmailMessage(**snapshot["email"]) if snapshot["email"] else None
            result[key] = item, email
        return sorted(result.values(), key=lambda row: (
            datetime.fromisoformat(row[0].occurred_at.replace("Z", "+00:00")), row[0].id))

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
                id, status, title, body,
                fetched_count, kept_count, filtered_count, error_message,
                generated_at, created_at, updated_at, window_start, window_end, mail_snapshot_available, rule_text, source_windows, updated_sources
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                title = excluded.title,
                body = excluded.body,
                fetched_count = excluded.fetched_count,
                kept_count = excluded.kept_count,
                filtered_count = excluded.filtered_count,
                error_message = excluded.error_message,
                generated_at = excluded.generated_at,
                updated_at = excluded.updated_at,
                window_start = excluded.window_start,
                window_end = excluded.window_end,
                mail_snapshot_available = excluded.mail_snapshot_available,
                rule_text = excluded.rule_text,
                source_windows = excluded.source_windows,
                updated_sources = excluded.updated_sources
            """,
            (
                briefing.id,
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
                briefing.window_start,
                briefing.window_end,
                int(briefing.mail_snapshot_available),
                briefing.rule_text,
                _dump_payload(briefing.source_windows),
                json.dumps(briefing.updated_sources),
            ),
        )

    def get_briefing(self, briefing_id: str) -> Optional[Briefing]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM briefings WHERE id = ?", (briefing_id,)
            ).fetchone()
            return _briefing_from_row(row) if row else None

    def list_briefings(
        self, status: Optional[str] = None
    ) -> List[Briefing]:
        clauses: List[str] = []
        args: list = []
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

    def save_snapshot(self, briefing: Briefing, items: Optional[List[BriefingItem]], trigger: str = "manual", mail: Optional[List[dict]] = None, cursor_updates=None, staged_run_id=None) -> None:
        """Commit candidates, cursors, document, history and Outbox atomically."""
        with self._conn() as conn:
            if staged_run_id and briefing.status in ("completed", "partial"):
                staged = conn.execute("SELECT snapshot FROM briefing_source_staging WHERE run_id=?",
                                      (staged_run_id,)).fetchall()
                for row in staged:
                    snapshot = json.loads(row[0])
                    item = SourceItem(**snapshot["item"])
                    email = EmailMessage(**snapshot["email"]) if snapshot["email"] else None
                    self._upsert_source_item(conn, item, email)
                conn.execute("DELETE FROM briefing_source_staging WHERE run_id=?", (staged_run_id,))
                conn.execute("DELETE FROM briefing_source_errors WHERE run_id=?", (staged_run_id,))
            self._write_briefing(conn, briefing)
            if items is not None:
                self._replace_items(conn, briefing.id, items)
            if mail is not None:
                conn.execute("DELETE FROM briefing_mail WHERE briefing_id=?", (briefing.id,))
                conn.executemany("INSERT INTO briefing_mail VALUES (?,?,?)", [
                    (briefing.id, row["id"], _dump_payload(row)) for row in mail])
                conn.execute("DELETE FROM briefing_candidates WHERE briefing_id=?", (briefing.id,))
                conn.executemany("INSERT INTO briefing_candidates VALUES (?,?)", [
                    (briefing.id, row["id"]) for row in mail])
            for source, account_id, key, value in cursor_updates or []:
                conn.execute("""INSERT INTO sync_state
                    (source,account_id,cursor_key,cursor_value,updated_at) VALUES (?,?,?,?,?)
                    ON CONFLICT(source,account_id,cursor_key) DO UPDATE SET
                    cursor_value=excluded.cursor_value,updated_at=excluded.updated_at""",
                    (source, account_id, key, value, briefing.updated_at))
            self._archive(conn, briefing, trigger)

    def _archive(self, conn, briefing, trigger):
        cards = [_item_from_row(row) for row in conn.execute(
            "SELECT * FROM briefing_items WHERE briefing_id=? ORDER BY sort_order", (briefing.id,))]
        number = conn.execute("SELECT COALESCE(MAX(number),0)+1 FROM briefing_revisions WHERE briefing_id=?", (briefing.id,)).fetchone()[0]
        mail = [json.loads(row[0]) for row in conn.execute("SELECT snapshot FROM briefing_mail WHERE briefing_id=? ORDER BY source_item_id", (briefing.id,))]
        snapshot = {"briefing": asdict(briefing), "items": [asdict(item) for item in cards], "mail": mail}
        payload = _dump_payload(snapshot)
        conn.execute("INSERT INTO briefing_revisions VALUES (?,?,?,?,?)", (briefing.id, number, trigger, briefing.updated_at, payload))
        if trigger != "legacy" and briefing.status in ("completed", "partial"):
            conn.execute("""INSERT INTO briefing_outbox(briefing_id,revision,snapshot)
                VALUES (?,?,?)""", (briefing.id, number, payload))

    def pending_projection_events(self, limit=20):
        with self._conn() as conn:
            rows = conn.execute("""SELECT * FROM briefing_outbox
                WHERE calendar_ack_at IS NULL OR todo_ack_at IS NULL
                ORDER BY briefing_id,revision LIMIT ?""", (limit,)).fetchall()
            return [dict(row) for row in rows]

    def ack_projection(self, briefing_id, revision, consumer, error=None):
        if consumer not in ("calendar", "todo"):
            raise ValueError("unknown briefing projection consumer")
        with self._conn() as conn:
            if error:
                conn.execute(f"""UPDATE briefing_outbox SET {consumer}_error=?
                    WHERE briefing_id=? AND revision=?""", (str(error), briefing_id, revision))
            else:
                conn.execute(f"""UPDATE briefing_outbox SET {consumer}_ack_at=?,{consumer}_error=NULL
                    WHERE briefing_id=? AND revision=?""",
                    (datetime.now(timezone.utc).isoformat(), briefing_id, revision))

    def list_mail(self, briefing_id):
        with self._conn() as conn:
            rows = conn.execute("SELECT snapshot FROM briefing_mail WHERE briefing_id=? ORDER BY source_item_id", (briefing_id,)).fetchall()
            return [json.loads(row[0]) for row in rows]

    def latest_tracked_items(self):
        with self._conn() as conn:
            rows = conn.execute('''SELECT b.*,i.entity_key FROM briefing_items b
                JOIN briefing_entity_items i ON i.item_id=b.id
                ORDER BY julianday(b.occurred_at) DESC,b.updated_at DESC,b.id''')
            seen = set()
            result = []
            for row in rows:
                if row['entity_key'] not in seen:
                    seen.add(row['entity_key'])
                    result.append(_item_from_row(row))
            return result

    def list_revisions(self, briefing_id):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM briefing_revisions WHERE briefing_id=? ORDER BY number DESC", (briefing_id,)).fetchall()
            return [{"number": row["number"], "trigger": row["trigger"], "created_at": row["created_at"],
                     "status": json.loads(row["snapshot"])["briefing"]["status"]} for row in rows]

    def get_revision(self, briefing_id, number):
        with self._conn() as conn:
            row = conn.execute("SELECT snapshot FROM briefing_revisions WHERE briefing_id=? AND number=?", (briefing_id, number)).fetchone()
            return json.loads(row[0]) if row else None

    def window_candidates(self, start, end, accounts):
        if not accounts:
            return []
        with self._conn() as conn:
            clauses = " OR ".join("(s.source=? AND s.account_id=?)" for _ in accounts)
            args = [value for pair in accounts for value in pair]
            rows = conn.execute(_SOURCE_ITEM_SELECT + " WHERE (" + clauses + ") AND julianday(s.occurred_at)>julianday(?) AND julianday(s.occurred_at)<=julianday(?) ORDER BY s.occurred_at,s.id", (*args,start,end)).fetchall()
            return [_source_from_row(row) for row in rows]

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
                    note, created_at, updated_at, text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    rule.text,
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
                    match_op = ?, match_value = ?, note = ?, updated_at = ?, text = ?
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
                    rule.text,
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


def get_briefing_store(db_path: Path) -> BriefingStore:
    """Return the cached store for ``db_path`` (host supplies the path)."""
    if db_path is None:
        raise ValueError("db_path is required")
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
