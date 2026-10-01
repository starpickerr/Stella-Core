"""User calendar with stable source links for briefing ingestion."""

from __future__ import annotations

import sqlite3
import uuid
import json
import hashlib
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .imports import HOLIDAY_SCHEDULES, parse_special_dates


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
                    repeat_frequency TEXT NOT NULL DEFAULT 'none',
                    repeat_days TEXT NOT NULL DEFAULT '[]',
                    repeat_until TEXT,
                    repeat_timezone TEXT,
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
            # Serialize the schema check and ALTERs across simultaneous HTTP requests.
            # executescript commits any earlier transaction, so acquire the write lock here.
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(calendar_events)")}
            for name, declaration in (
                ("repeat_frequency", "TEXT NOT NULL DEFAULT 'none'"),
                ("repeat_days", "TEXT NOT NULL DEFAULT '[]'"),
                ("repeat_until", "TEXT"),
                ("repeat_timezone", "TEXT"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE calendar_events ADD COLUMN {name} {declaration}")
            defaults = (
                ("personal", "个人", "#55B89A"), ("work", "工作", "#6B8AF7"),
                ("study", "学习", "#E5A755"),
                ("china_holidays", "中国大陆节假日", "#B35BD6"),
            )
            for category_id, name, color in (defaults if created_new else defaults[-1:]):
                db.execute("INSERT OR IGNORE INTO calendar_categories VALUES (?,?,?,?)",
                           (category_id, name, color, _now()))
            db.execute("""UPDATE OR IGNORE calendar_categories SET name='中国大陆节假日'
                WHERE id='china_holidays' AND name='中国节假日'""")
            if not created_new:
                db.execute("""DELETE FROM calendar_categories WHERE id='tasks' AND name='事务'
                    AND NOT EXISTS (SELECT 1 FROM calendar_events WHERE category_id='tasks')""")
                db.execute("""DELETE FROM calendar_categories WHERE id='other' AND name='其他'
                    AND NOT EXISTS (SELECT 1 FROM calendar_events WHERE category_id='other')""")
                # Earlier date imports created a sixth default category. Fold only that
                # unchanged category into Personal, preserving user-customized categories.
                db.execute("""UPDATE calendar_events SET category_id='personal'
                    WHERE category_id='special_dates' AND EXISTS
                    (SELECT 1 FROM calendar_categories WHERE id='special_dates' AND name='特殊日期')
                    AND EXISTS (SELECT 1 FROM calendar_categories WHERE id='personal')""")
                db.execute("""DELETE FROM calendar_categories WHERE id='special_dates' AND name='特殊日期'
                    AND NOT EXISTS (SELECT 1 FROM calendar_events WHERE category_id='special_dates')""")

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
            return [dict(row) for row in db.execute("""SELECT * FROM calendar_categories ORDER BY
                CASE id WHEN 'personal' THEN 0 WHEN 'work' THEN 1 WHEN 'study' THEN 2
                WHEN 'china_holidays' THEN 3 ELSE 4 END, created_at, name""")]

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
        if category_id == "china_holidays" and name != old["name"]:
            raise ValueError("reserved category cannot be renamed")
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
        if category_id == "china_holidays":
            raise ValueError("reserved category cannot be deleted")
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
        frequency = row.get("repeat_frequency") or "none"
        if frequency not in ("none", "daily", "weekly", "monthly", "yearly"):
            raise ValueError("invalid repeat_frequency")
        row["repeat_frequency"] = frequency
        days = row.get("repeat_days", [])
        if isinstance(days, str):
            try:
                days = json.loads(days)
            except ValueError as exc:
                raise ValueError("invalid repeat_days") from exc
        if not isinstance(days, list) or any(type(day) is not int or day < 0 or day > 6 for day in days):
            raise ValueError("repeat_days must contain weekdays 0-6")
        row["repeat_days"] = json.dumps(sorted(set(days)))
        until = row.get("repeat_until") or None
        if until:
            try:
                until = datetime.strptime(until, "%Y-%m-%d").date().isoformat()
            except (ValueError, TypeError) as exc:
                raise ValueError("repeat_until must be YYYY-MM-DD") from exc
        row["repeat_until"] = until
        zone = row.get("repeat_timezone") or "UTC"
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
            raise ValueError("invalid repeat_timezone") from exc
        row["repeat_timezone"] = zone
        if frequency != "none" and until and until < datetime.fromisoformat(row["start_at"]).astimezone(ZoneInfo(zone)).date().isoformat():
            raise ValueError("repeat_until must be on or after start_at")
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
        start_at = datetime.fromisoformat(_instant(start, "start")) if start else None
        end_at = datetime.fromisoformat(_instant(end, "end")) if end else None
        if start_at and end_at and end_at <= start_at:
            raise ValueError("end must be after start")
        clauses, args = [], []
        if start_at and end_at:
            clauses.append("(repeat_frequency != 'none' OR (end_at > ? AND start_at < ?))")
            args.extend((start_at.isoformat(), end_at.isoformat()))
        elif start_at:
            clauses.append("end_at > ?")
            args.append(start_at.isoformat())
        elif end_at:
            clauses.append("start_at < ?")
            args.append(end_at.isoformat())
        if category_id:
            clauses.append("category_id = ?")
            args.append(category_id)
        sql = "SELECT * FROM calendar_events" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY start_at, id"
        with self._connect() as db:
            templates = [dict(row) for row in db.execute(sql, args)]
        if not start_at or not end_at:
            return templates
        if end_at - start_at > timedelta(days=370):
            raise ValueError("calendar range cannot exceed 370 days")
        results = []
        for row in templates:
            if row["repeat_frequency"] == "none":
                if datetime.fromisoformat(row["end_at"]) > start_at and datetime.fromisoformat(row["start_at"]) < end_at:
                    results.append(row)
            else:
                results.extend(self._occurrences(row, start_at, end_at))
        return sorted(results, key=lambda row: (row["start_at"], row["id"]))

    @staticmethod
    def _occurrences(row, start, end):
        zone = ZoneInfo(row["repeat_timezone"] or "UTC")
        original = datetime.fromisoformat(row["start_at"]).astimezone(zone)
        original_end = datetime.fromisoformat(row["end_at"]).astimezone(zone)
        wall_duration = original_end.replace(tzinfo=None) - original.replace(tzinfo=None)
        duration = datetime.fromisoformat(row["end_at"]) - datetime.fromisoformat(row["start_at"])
        first_day = original.date()
        until = datetime.fromisoformat(row["repeat_until"]).date() if row["repeat_until"] else None
        candidate = max(first_day, (start.astimezone(zone) - duration).date())
        last = end.astimezone(zone).date()
        weekdays = json.loads(row["repeat_days"] or "[]") or [first_day.weekday()]
        results = []
        while candidate <= last and (until is None or candidate <= until):
            elapsed = (candidate - first_day).days
            frequency = row["repeat_frequency"]
            matches = (frequency == "daily" or
                       frequency == "weekly" and candidate.weekday() in weekdays or
                       frequency == "monthly" and candidate.day == first_day.day or
                       frequency == "yearly" and (candidate.month, candidate.day) == (first_day.month, first_day.day))
            if elapsed >= 0 and matches:
                occurrence_start = datetime.combine(candidate, original.timetz().replace(tzinfo=None), zone).astimezone(timezone.utc)
                occurrence_end = (datetime.combine(candidate, original.timetz().replace(tzinfo=None)) + wall_duration).replace(tzinfo=zone).astimezone(timezone.utc)
                if occurrence_end > start and occurrence_start < end:
                    instance = dict(row)
                    instance["series_id"] = row["id"]
                    instance["id"] = f"{row['id']}@{candidate.isoformat()}"
                    instance["start_at"] = occurrence_start.isoformat()
                    instance["end_at"] = occurrence_end.isoformat()
                    results.append(instance)
            candidate += timedelta(days=1)
        return results

    def create_event(self, payload):
        row = self._validate_event(payload)
        event_id, now = str(uuid.uuid4()), _now()
        with self._connect() as db:
            db.execute("""INSERT INTO calendar_events
                (id,title,description,start_at,end_at,all_day,location,category_id,source_type,source_key,source_url,user_modified,repeat_frequency,repeat_days,repeat_until,repeat_timezone,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, row["title"], row["description"], row["start_at"], row["end_at"], row["all_day"],
                 row["location"], row.get("category_id"), None, None, "", 0, row["repeat_frequency"], row["repeat_days"], row["repeat_until"], row["repeat_timezone"], now, now))
        return self.get_event(event_id)

    def update_event(self, event_id, payload):
        old = self.get_event(event_id)
        if old["source_type"] == "china_holiday":
            raise ValueError("official holidays cannot be edited")
        row = self._validate_event(payload, old)
        with self._connect() as db:
            db.execute("""UPDATE calendar_events SET title=?,description=?,start_at=?,end_at=?,all_day=?,location=?,
                category_id=?,repeat_frequency=?,repeat_days=?,repeat_until=?,repeat_timezone=?,user_modified=1,updated_at=? WHERE id=?""",
                (row["title"], row["description"], row["start_at"], row["end_at"], row["all_day"],
                 row["location"], row.get("category_id"), row["repeat_frequency"], row["repeat_days"], row["repeat_until"], row["repeat_timezone"], _now(), event_id))
        return self.get_event(event_id)

    def delete_event(self, event_id):
        self.get_event(event_id)
        with self._connect() as db:
            db.execute("DELETE FROM calendar_events WHERE id=?", (event_id,))

    @staticmethod
    def _import_category(db, category_id, name, color):
        db.execute("INSERT OR IGNORE INTO calendar_categories VALUES (?,?,?,?)",
                   (category_id, name, color, _now()))
        row = db.execute("SELECT id FROM calendar_categories WHERE id=?", (category_id,)).fetchone()
        if row is None:
            row = db.execute("SELECT id FROM calendar_categories WHERE name=?", (name,)).fetchone()
        return row["id"] if row else None

    def _all_day_import(self, title, start_day, end_day, annual, zone, description=""):
        try:
            start_date = date.fromisoformat(start_day)
            end_date = date.fromisoformat(end_day)
            timezone_info = ZoneInfo(zone)
        except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
            raise ValueError("invalid special date or timezone") from exc
        if end_date < start_date:
            raise ValueError("special date end must follow start")
        start = datetime.combine(start_date, time.min, timezone_info)
        end = datetime.combine(end_date + timedelta(days=1), time.min, timezone_info)
        return self._validate_event({"title": title, "description": description, "start_at": start.isoformat(),
                                     "end_at": end.isoformat(), "all_day": True, "location": "",
                                     "repeat_frequency": "yearly" if annual else "none", "repeat_timezone": zone})

    @staticmethod
    def _insert_import_event(db, row, category_id, source_type, source_key, source_url=""):
        now = _now()
        cursor = db.execute("""INSERT OR IGNORE INTO calendar_events
            (id,title,description,start_at,end_at,all_day,location,category_id,source_type,source_key,source_url,
             user_modified,repeat_frequency,repeat_days,repeat_until,repeat_timezone,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), row["title"], row["description"], row["start_at"], row["end_at"], row["all_day"],
             row["location"], category_id, source_type, source_key, source_url, 0,
             row["repeat_frequency"], row["repeat_days"], row["repeat_until"], row["repeat_timezone"], now, now))
        return cursor.rowcount

    def import_china_holidays(self, year):
        if type(year) is not int or year not in HOLIDAY_SCHEDULES:
            raise ValueError("official holiday schedule is available for 2025 and 2026")
        schedule = HOLIDAY_SCHEDULES[year]
        prepared = []
        for name, first, last in schedule["off"]:
            prepared.append((self._all_day_import(f"{name}（休）", first, last, False, "Asia/Shanghai"),
                             f"{year}:off:{name}"))
        for day in schedule["work"]:
            prepared.append((self._all_day_import("调休上班（班）", day, day, False, "Asia/Shanghai"),
                             f"{year}:work:{day}"))
        with self._connect() as db:
            category_id = self._import_category(db, "china_holidays", "中国大陆节假日", "#B35BD6")
            added = sum(self._insert_import_event(db, row, category_id, "china_holiday", key, schedule["source"])
                        for row, key in prepared)
        return {"year": year, "added": added, "total": len(prepared)}

    def create_special_date(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("special date must be an object")
        if type(payload.get("annual", False)) is not bool:
            raise ValueError("annual must be true or false")
        row = self._all_day_import(payload.get("title"), payload.get("date"), payload.get("date"),
                                   payload.get("annual", False), payload.get("timezone") or "UTC",
                                   payload.get("description") or "")
        with self._connect() as db:
            category = db.execute("SELECT id FROM calendar_categories WHERE id='personal'").fetchone()
            category_id = category["id"] if category else None
            key = "manual:" + str(uuid.uuid4())
            self._insert_import_event(db, row, category_id, "special_date", key)
            event = db.execute("SELECT * FROM calendar_events WHERE source_type='special_date' AND source_key=?", (key,)).fetchone()
        return dict(event)

    def import_special_dates(self, content, format_name, zone):
        parsed = parse_special_dates(content, format_name)
        prepared = []
        for item in parsed:
            row = self._all_day_import(item["title"], item["date"], item["date"], item["annual"], zone,
                                       item["description"])
            identity = item["uid"] or f"{item['title']}\x00{item['date']}\x00{item['annual']}"
            key = ("uid:" if item["uid"] else "date:") + hashlib.sha256(identity.encode("utf-8")).hexdigest()
            prepared.append((row, key))
        with self._connect() as db:
            category = db.execute("SELECT id FROM calendar_categories WHERE id='personal'").fetchone()
            category_id = category["id"] if category else None
            added = sum(self._insert_import_event(db, row, category_id, "special_date", key)
                        for row, key in prepared)
        return {"added": added, "total": len(prepared)}

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
            due_at = item.payload.get("due_at") if isinstance(item.payload, dict) else None
            start = calendar.get("start_at") or (due_at if item.section != "action" else None)
            event_id = None
            if start:
                try:
                    start = _instant(start, "start_at")
                    end = _instant(calendar.get("end_at"), "end_at") if calendar.get("end_at") else None
                    if end is None:
                        from datetime import timedelta
                        end = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()
                    event = self._upsert_sourced_event(source_key, item, start, end,
                                                        bool(calendar.get("all_day", False)))
                    event_id = event["id"]
                    count += 1
                except (ValueError, TypeError):
                    pass
            with self._connect() as db:
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
