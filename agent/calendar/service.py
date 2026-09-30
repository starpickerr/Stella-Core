"""User calendar with stable source links for briefing ingestion."""

from __future__ import annotations

import sqlite3
import uuid
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


def _now():
    return datetime.now(timezone.utc).isoformat()


def _instant(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _text(value, field, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{field} must be 1-{limit} characters")
    return value.strip()


class CalendarService:
    def __init__(self, db_path=None):
        if db_path is None:
            from common.state_dir import calendar_db
            db_path = calendar_db()
        self.db_path = Path(db_path)
        created_new = not self.db_path.exists()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS calendar_categories (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                    color TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS calendar_events (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                    start_at TEXT NOT NULL, end_at TEXT NOT NULL, all_day INTEGER NOT NULL DEFAULT 0,
                    location TEXT NOT NULL DEFAULT '', category_id TEXT,
                    source_type TEXT, source_key TEXT, source_url TEXT NOT NULL DEFAULT '',
                    user_modified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(category_id) REFERENCES calendar_categories(id) ON DELETE SET NULL,
                    UNIQUE(source_type, source_key)
                );
                CREATE INDEX IF NOT EXISTS calendar_events_start ON calendar_events(start_at);
                CREATE TABLE IF NOT EXISTS agenda_handoffs (
                    source_type TEXT NOT NULL, source_key TEXT NOT NULL,
                    destination TEXT NOT NULL CHECK(destination IN ('task','calendar')),
                    title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
                    briefing_id TEXT NOT NULL, briefing_item_id TEXT NOT NULL,
                    calendar_event_id TEXT, updated_at TEXT NOT NULL,
                    PRIMARY KEY(source_type, source_key, destination)
                );
            """)
            if created_new:
                for category_id, name, color in (
                    ("work", "工作", "#6B8AF7"), ("personal", "个人", "#55B89A"),
                    ("study", "学习", "#E5A755"), ("other", "其他", "#A48BCD"),
                ):
                    db.execute("INSERT OR IGNORE INTO calendar_categories VALUES (?,?,?,?)",
                               (category_id, name, color, _now()))

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def categories(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM calendar_categories ORDER BY created_at, name")]

    def create_category(self, payload):
        name = _text(payload.get("name"), "name", 40)
        color = payload.get("color", "#6B8AF7")
        if not isinstance(color, str) or len(color) != 7 or color[0] != "#" or any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
            raise ValueError("color must be #RRGGBB")
        category_id = str(uuid.uuid4())
        try:
            with self._connect() as db:
                db.execute("INSERT INTO calendar_categories VALUES (?,?,?,?)", (category_id, name, color, _now()))
        except sqlite3.IntegrityError as exc:
            raise ValueError("category name already exists") from exc
        return self.get_category(category_id)

    def get_category(self, category_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM calendar_categories WHERE id=?", (category_id,)).fetchone()
        if row is None:
            raise KeyError("category not found")
        return dict(row)

    def update_category(self, category_id, payload):
        old = self.get_category(category_id)
        name = _text(payload.get("name", old["name"]), "name", 40)
        color = payload.get("color", old["color"])
        if not isinstance(color, str) or len(color) != 7 or color[0] != "#" or any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
            raise ValueError("color must be #RRGGBB")
        try:
            with self._connect() as db:
                db.execute("UPDATE calendar_categories SET name=?, color=? WHERE id=?", (name, color, category_id))
        except sqlite3.IntegrityError as exc:
            raise ValueError("category name already exists") from exc
        return self.get_category(category_id)

    def delete_category(self, category_id):
        self.get_category(category_id)
        with self._connect() as db:
            db.execute("DELETE FROM calendar_categories WHERE id=?", (category_id,))

    def _validate_event(self, payload, existing=None):
        row = dict(existing or {})
        row.update(payload)
        row["title"] = _text(row.get("title"), "title")
        row["start_at"] = _instant(row.get("start_at"), "start_at")
        row["end_at"] = _instant(row.get("end_at"), "end_at")
        if datetime.fromisoformat(row["end_at"]) <= datetime.fromisoformat(row["start_at"]):
            raise ValueError("end_at must be after start_at")
        for field in ("description", "location"):
            value = row.get(field, "")
            if not isinstance(value, str):
                raise ValueError(f"{field} must be text")
            row[field] = value
        row["all_day"] = int(bool(row.get("all_day", False)))
        if row.get("category_id"):
            self.get_category(row["category_id"])
        return row

    def get_event(self, event_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM calendar_events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise KeyError("event not found")
        return dict(row)

    def list_events(self, start=None, end=None, category_id=None):
        clauses, args = [], []
        if start:
            clauses.append("end_at > ?")
            args.append(_instant(start, "start"))
        if end:
            clauses.append("start_at < ?")
            args.append(_instant(end, "end"))
        if category_id:
            clauses.append("category_id = ?")
            args.append(category_id)
        sql = "SELECT * FROM calendar_events" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY start_at, id"
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def create_event(self, payload):
        row = self._validate_event(payload)
        event_id, now = str(uuid.uuid4()), _now()
        with self._connect() as db:
            db.execute("""INSERT INTO calendar_events
                (id,title,description,start_at,end_at,all_day,location,category_id,source_type,source_key,source_url,user_modified,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, row["title"], row["description"], row["start_at"], row["end_at"], row["all_day"],
                 row["location"], row.get("category_id"), None, None, "", 0, now, now))
        return self.get_event(event_id)

    def update_event(self, event_id, payload):
        old = self.get_event(event_id)
        row = self._validate_event(payload, old)
        with self._connect() as db:
            db.execute("""UPDATE calendar_events SET title=?,description=?,start_at=?,end_at=?,all_day=?,location=?,
                category_id=?,user_modified=1,updated_at=? WHERE id=?""",
                (row["title"], row["description"], row["start_at"], row["end_at"], row["all_day"],
                 row["location"], row.get("category_id"), _now(), event_id))
        return self.get_event(event_id)

    def delete_event(self, event_id):
        self.get_event(event_id)
        with self._connect() as db:
            db.execute("DELETE FROM calendar_events WHERE id=?", (event_id,))

    def ingest_briefing(self, detail):
        """Record routing decisions and sync explicit dates, keyed by source identity."""
        briefing = detail["briefing"]
        decisions = {row["id"]: row.get("decision") or {} for row in detail.get("mail", [])}
        count = 0
        current_keys = set()
        items = list(detail.get("items", []))
        covered = {item.source_item_id for item in items}
        for row in detail.get("mail", []):
            if row.get("category") != "selected" or row.get("id") in covered:
                continue
            decision = row.get("decision") or {}
            card = next((item for item in items if item.thread_id and item.thread_id == row.get("thread_id")), None)
            items.append(SimpleNamespace(
                source=row["source"], account_id=row["account_id"], source_id=row["source_id"],
                source_item_id=row["id"], thread_id=row.get("thread_id", ""),
                section=decision.get("section", "fyi"), title=row["title"],
                snippet=decision.get("summary") or row.get("snippet", ""),
                payload=row.get("metadata") or {}, url=row.get("url", ""),
                id=card.id if card else row["id"],
            ))
        for item in items:
            source_key = json.dumps([item.source, item.account_id, item.source_id], ensure_ascii=False, separators=(",", ":"))
            current_keys.add(source_key)
            decision = decisions.get(item.source_item_id, {})
            calendar = decision.get("calendar") if isinstance(decision.get("calendar"), dict) else {}
            start = calendar.get("start_at") or (item.payload.get("due_at") if isinstance(item.payload, dict) else None)
            event_id = None
            if start:
                try:
                    start = _instant(start, "start_at")
                    end = _instant(calendar.get("end_at"), "end_at") if calendar.get("end_at") else None
                    if end is None:
                        from datetime import timedelta
                        end = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()
                    event = self._upsert_sourced_event(source_key, item, start, end, bool(calendar.get("all_day", False)))
                    event_id = event["id"]
                    count += 1
                except (ValueError, TypeError):
                    pass
            with self._connect() as db:
                if item.section == "action":
                    db.execute("""INSERT INTO agenda_handoffs VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(source_type,source_key,destination) DO UPDATE SET
                        title=excluded.title,summary=excluded.summary,briefing_id=excluded.briefing_id,
                        briefing_item_id=excluded.briefing_item_id,updated_at=excluded.updated_at""",
                        ("briefing", source_key, "task", item.title, item.snippet, briefing.id, item.id, None, _now()))
                else:
                    db.execute("DELETE FROM agenda_handoffs WHERE source_type='briefing' AND source_key=? AND destination='task'",
                               (source_key,))
                if event_id:
                    db.execute("""INSERT INTO agenda_handoffs VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(source_type,source_key,destination) DO UPDATE SET
                        title=excluded.title,summary=excluded.summary,briefing_id=excluded.briefing_id,
                        briefing_item_id=excluded.briefing_item_id,calendar_event_id=excluded.calendar_event_id,updated_at=excluded.updated_at""",
                        ("briefing", source_key, "calendar", item.title, item.snippet, briefing.id, item.id, event_id, _now()))
                else:
                    old = db.execute("SELECT calendar_event_id FROM agenda_handoffs WHERE source_type='briefing' AND source_key=? AND destination='calendar'",
                                     (source_key,)).fetchone()
                    if old and old["calendar_event_id"]:
                        db.execute("DELETE FROM calendar_events WHERE id=? AND user_modified=0", (old["calendar_event_id"],))
                    db.execute("DELETE FROM agenda_handoffs WHERE source_type='briefing' AND source_key=? AND destination='calendar'",
                               (source_key,))
        with self._connect() as db:
            stale = db.execute("SELECT source_key, calendar_event_id FROM agenda_handoffs WHERE briefing_id=?",
                               (briefing.id,)).fetchall()
            for row in stale:
                if row["source_key"] in current_keys:
                    continue
                if row["calendar_event_id"]:
                    db.execute("DELETE FROM calendar_events WHERE id=? AND user_modified=0",
                               (row["calendar_event_id"],))
                db.execute("DELETE FROM agenda_handoffs WHERE briefing_id=? AND source_key=?",
                           (briefing.id, row["source_key"]))
        return count

    def _upsert_sourced_event(self, source_key, item, start, end, all_day):
        preferred = "study" if item.source == "elearning" else "work"
        with self._connect() as db:
            category_id = preferred if db.execute("SELECT 1 FROM calendar_categories WHERE id=?", (preferred,)).fetchone() else None
        row = self._validate_event({"title": item.title, "description": item.snippet,
                                    "start_at": start, "end_at": end, "all_day": all_day,
                                    "location": "", "category_id": category_id})
        with self._connect() as db:
            old = db.execute("SELECT * FROM calendar_events WHERE source_type='briefing' AND source_key=?", (source_key,)).fetchone()
            if old and old["user_modified"]:
                return dict(old)
            event_id = old["id"] if old else str(uuid.uuid4())
            now = _now()
            db.execute("""INSERT INTO calendar_events
                (id,title,description,start_at,end_at,all_day,location,category_id,source_type,source_key,source_url,user_modified,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_type,source_key) DO UPDATE SET title=excluded.title,description=excluded.description,
                start_at=excluded.start_at,end_at=excluded.end_at,all_day=excluded.all_day,source_url=excluded.source_url,
                updated_at=excluded.updated_at""",
                (event_id, row["title"], row["description"], row["start_at"], row["end_at"], row["all_day"],
                 row["location"], row["category_id"], "briefing", source_key, item.url, 0, now, now))
        return self.get_event(event_id)
