"""User calendar with stable source links for briefing ingestion (stella.calendar plugin)."""

from __future__ import annotations

import sqlite3
import uuid
import json
import hashlib
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .imports import HOLIDAY_SCHEDULES, parse_special_dates

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def load_schema_sql() -> str:
    return _SCHEMA_PATH.read_text(encoding="utf-8")


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
    def __init__(self, db_path):
        if db_path is None:
            raise ValueError("db_path is required (host data handle)")
        self.db_path = Path(db_path)
        created_new = not self.db_path.exists()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(load_schema_sql())
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

    def find_briefing_sources(self, source_keys):
        if (not isinstance(source_keys, list) or len(source_keys) > 1000 or
                any(not isinstance(key, str) or not key for key in source_keys)):
            raise ValueError('source_keys must be stable source references')
        if not source_keys:
            return []
        placeholders = ','.join('?' for _ in source_keys)
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM calendar_events WHERE source_type='briefing' AND source_key IN (" + placeholders + ")",
                source_keys)]

    def has_source_tombstone(self, source_keys):
        """Public collaboration API: whether any source_key is tombstoned."""
        candidates = [key for key in source_keys if key]
        if not candidates:
            return False
        with self._connect() as db:
            for candidate in candidates:
                if db.execute(
                    "SELECT 1 FROM source_tombstones WHERE source_key=?",
                    (candidate,),
                ).fetchone():
                    return True
        return False

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

    def set_event_category(self, event_id, category_id):
        """Move an event between categories without treating that as a content edit."""
        self.get_event(event_id)
        if category_id is not None:
            self.get_category(category_id)
        with self._connect() as db:
            db.execute("UPDATE calendar_events SET category_id=? WHERE id=?", (category_id, event_id))
        return self.get_event(event_id)

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
            exclusions = {(row["series_id"], row["occurrence_on"]) for row in db.execute(
                "SELECT series_id,occurrence_on FROM calendar_occurrence_exclusions")}
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
                results.extend(instance for instance in self._occurrences(row, start_at, end_at)
                               if (row["id"], instance["id"].rsplit("@", 1)[-1]) not in exclusions)
        return sorted(results, key=lambda row: (row["start_at"], row["id"]))

    def exclude_occurrence(self, series_id, occurrence_on):
        try:
            day = date.fromisoformat(occurrence_on).isoformat()
        except (ValueError, TypeError) as exc:
            raise ValueError("occurrence_on must be YYYY-MM-DD") from exc
        series = self.get_event(series_id)
        if series["repeat_frequency"] == "none":
            raise ValueError("event is not a recurring series")
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO calendar_occurrence_exclusions VALUES (?,?)", (series_id, day))

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

    def create_event(self, payload, *, _briefing_key=None):
        row = self._validate_event(payload)
        event_id, now = str(uuid.uuid4()), _now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if _briefing_key:
                existing = db.execute("SELECT id FROM calendar_events WHERE source_type='briefing' AND source_key=?", (_briefing_key,)).fetchone()
                if existing:
                    return self.get_event(existing[0])
                if db.execute("SELECT 1 FROM source_tombstones WHERE source_key=?", (_briefing_key,)).fetchone():
                    raise ValueError("source event was deleted")
            db.execute("""INSERT INTO calendar_events
                (id,title,description,start_at,end_at,all_day,location,category_id,source_type,source_key,source_url,user_modified,repeat_frequency,repeat_days,repeat_until,repeat_timezone,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, row["title"], row["description"], row["start_at"], row["end_at"], row["all_day"],
                 row["location"], row.get("category_id"), "briefing" if _briefing_key else None, _briefing_key, "", 0, row["repeat_frequency"], row["repeat_days"], row["repeat_until"], row["repeat_timezone"], now, now))
        return self.get_event(event_id)

    def upsert_external_event(self, provider, source_key, payload, event_id=None, reconciled=False):
        """Create or refresh a sourced event without overwriting a local edit."""
        if provider != "apple_calendar":
            raise ValueError("unsupported calendar provider")
        source_key = _text(source_key, "source_key", 1000)
        row = self._validate_event(payload)
        now = _now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM calendar_events WHERE source_type=? AND source_key=?",
                             (provider, source_key)).fetchone()
            if old:
                if event_id and old["id"] != event_id:
                    raise ValueError("source event mapping changed")
                if old["user_modified"] and not reconciled:
                    raise ValueError("source event was locally modified")
                db.execute("""UPDATE calendar_events SET title=?,description=?,start_at=?,end_at=?,all_day=?,
                    location=?,repeat_frequency=?,repeat_days=?,repeat_until=?,repeat_timezone=?,user_modified=0,updated_at=?
                    WHERE id=?""", (row["title"], row["description"], row["start_at"], row["end_at"],
                    row["all_day"], row["location"], row["repeat_frequency"], row["repeat_days"],
                    row["repeat_until"], row["repeat_timezone"], now, old["id"]))
                return_id = old["id"]
            else:
                if event_id:
                    raise KeyError("source event not found")
                return_id = str(uuid.uuid4())
                db.execute("""INSERT INTO calendar_events
                    (id,title,description,start_at,end_at,all_day,location,category_id,source_type,source_key,
                     source_url,user_modified,repeat_frequency,repeat_days,repeat_until,repeat_timezone,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (return_id, row["title"], row["description"], row["start_at"], row["end_at"],
                     row["all_day"], row["location"], row.get("category_id"), provider, source_key,
                     "", 0, row["repeat_frequency"], row["repeat_days"], row["repeat_until"],
                     row["repeat_timezone"], now, now))
        return self.get_event(return_id)

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
        old = self.get_event(event_id)
        with self._connect() as db:
            if old["source_type"] == "briefing" and old["source_key"]:
                db.execute("INSERT OR REPLACE INTO source_tombstones VALUES (?,?)",
                           (old["source_key"], _now()))
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

    def ingest_briefing_revision(self, detail, revision):
        briefing = detail["briefing"]
        briefing_id = briefing["id"] if isinstance(briefing, dict) else briefing.id
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT last_revision FROM briefing_applied WHERE briefing_id=?",
                             (briefing_id,)).fetchone()
            if row and row[0] >= revision:
                return 0
            count = self.ingest_briefing(detail, db=db)
            db.execute("""INSERT INTO briefing_applied VALUES (?,?)
                ON CONFLICT(briefing_id) DO UPDATE SET last_revision=excluded.last_revision""",
                (briefing_id, revision))
            return count

    def ingest_briefing(self, detail, db=None):
        """Legacy entry point is read-only; decisions execute via BriefingActions.

        Reclassification is never permission to delete user business records.
        Existing source links are adopted by the durable decision service.
        """
        return 0

    def _upsert_sourced_event(self, source_key, item, start, end, all_day, db=None):
        if db is None:
            with self._connect() as connection:
                return self._upsert_sourced_event(source_key, item, start, end, all_day, connection)
        preferred = "study" if item.source == "elearning" else "work"
        category_id = preferred if db.execute("SELECT 1 FROM calendar_categories WHERE id=?", (preferred,)).fetchone() else None
        row = self._validate_event({"title": item.title, "description": item.snippet,
                                    "start_at": start, "end_at": end, "all_day": all_day,
                                    "location": "", "category_id": category_id})
        if db.execute("SELECT 1 FROM source_tombstones WHERE source_key=?", (source_key,)).fetchone():
            return None
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
        return dict(db.execute("SELECT * FROM calendar_events WHERE id=?", (event_id,)).fetchone())


    def sync_briefing_facts(self, event_id, changes, baseline, force=False):
        """Update actual source times atomically without replacing user fields."""
        changes = {key:value for key,value in changes.items() if key in {"start_at","end_at"}}
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM calendar_events WHERE id=?",(event_id,)).fetchone()
            if current is None:
                raise KeyError("event not found")
            current = dict(current)
            normalized = self._validate_event(changes,current)
            conflicts = {key:{"current":current[key],"source":normalized[key]} for key in changes
                         if current[key] != normalized[key] and current[key] != baseline.get(key)}
            if conflicts and not force:
                return current, conflicts
            if changes:
                db.execute("UPDATE calendar_events SET start_at=?,end_at=?,updated_at=? WHERE id=?",
                           (normalized["start_at"],normalized["end_at"],_now(),event_id))
            return dict(db.execute("SELECT * FROM calendar_events WHERE id=?",(event_id,)).fetchone()), {}
