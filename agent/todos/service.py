"""Independent user to-dos and due reminders."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value, field, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{field} must be 1-{limit} characters")
    return value.strip()


class TodoService:
    def __init__(self, db_path=None, legacy_calendar_db_path=None):
        from common.state_dir import calendar_db, todos_db
        self.db_path = Path(db_path) if db_path else todos_db()
        self.legacy_calendar_db_path = (Path(legacy_calendar_db_path) if legacy_calendar_db_path else
                                        self.db_path.parent / "calendar.db" if db_path else calendar_db(ensure=False))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS todos (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
                    due_on TEXT, due_time TEXT, timezone TEXT NOT NULL DEFAULT 'UTC',
                    priority INTEGER NOT NULL DEFAULT 0, completed_at TEXT,
                    repeat_frequency TEXT NOT NULL DEFAULT 'none', repeat_days TEXT NOT NULL DEFAULT '[]',
                    repeat_until TEXT, source_type TEXT, source_key TEXT, source_url TEXT NOT NULL DEFAULT '',
                    user_modified INTEGER NOT NULL DEFAULT 0, briefing_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(source_type, source_key)
                );
                CREATE INDEX IF NOT EXISTS todos_due ON todos(due_on);
                CREATE TABLE IF NOT EXISTS todo_completions (
                    todo_id TEXT NOT NULL, occurrence_on TEXT NOT NULL, completed_at TEXT NOT NULL,
                    PRIMARY KEY(todo_id, occurrence_on),
                    FOREIGN KEY(todo_id) REFERENCES todos(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS todo_notifications (
                    todo_id TEXT NOT NULL, occurrence_on TEXT NOT NULL, notified_at TEXT NOT NULL,
                    PRIMARY KEY(todo_id, occurrence_on),
                    FOREIGN KEY(todo_id) REFERENCES todos(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS reminder_occurrences (
                    occurrence_id TEXT PRIMARY KEY, todo_id TEXT NOT NULL,
                    occurrence_on TEXT NOT NULL, reminder_kind TEXT NOT NULL,
                    due_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    UNIQUE(todo_id,occurrence_on,reminder_kind),
                    FOREIGN KEY(todo_id) REFERENCES todos(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS reminder_deliveries (
                    delivery_id TEXT PRIMARY KEY, occurrence_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending', claim_id TEXT,
                    lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                    shown_at TEXT, error TEXT,
                    FOREIGN KEY(occurrence_id) REFERENCES reminder_occurrences(occurrence_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS todo_migrations (name TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS briefing_applied (
                    briefing_id TEXT PRIMARY KEY, last_revision INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_tombstones (
                    source_key TEXT PRIMARY KEY, deleted_at TEXT NOT NULL
                );
            """)
        self._migrate_calendar_records()
        if os.environ.get("STELLA_DESKTOP") == "1":
            self._record_legacy_claims()

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

    def _migrate_calendar_records(self):
        """Copy records from the short-lived calendar implementation once."""
        if not self.legacy_calendar_db_path.exists():
            return
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM todo_migrations WHERE name='calendar_affairs_v1'").fetchone():
                return
            with sqlite3.connect(str(self.legacy_calendar_db_path)) as legacy:
                legacy.row_factory = sqlite3.Row
                tables = {row[0] for row in legacy.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "calendar_affairs" in tables:
                    handoff_ids = {}
                    if "agenda_handoffs" in tables:
                        handoff_ids = {row["source_key"]: row["briefing_id"] for row in legacy.execute(
                            "SELECT source_key,briefing_id FROM agenda_handoffs WHERE destination='task'")}
                    for row in legacy.execute("SELECT * FROM calendar_affairs"):
                        db.execute("""INSERT OR IGNORE INTO todos
                            (id,title,notes,due_on,due_time,timezone,priority,completed_at,repeat_frequency,
                             repeat_days,repeat_until,source_type,source_key,source_url,user_modified,briefing_id,
                             created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (row["id"], row["title"], row["notes"], row["due_on"], row["due_time"],
                             row["timezone"], row["priority"], row["completed_at"], row["repeat_frequency"],
                             row["repeat_days"], row["repeat_until"], row["source_type"], row["source_key"],
                             row["source_url"], row["user_modified"], handoff_ids.get(row["source_key"]),
                             row["created_at"], row["updated_at"]))
                    for old_table, new_table in (("calendar_affair_completions", "todo_completions"),
                                                 ("calendar_affair_notifications", "todo_notifications")):
                        if old_table in tables:
                            for row in legacy.execute(f"SELECT * FROM {old_table}"):
                                db.execute(f"INSERT OR IGNORE INTO {new_table} VALUES (?,?,?)", tuple(row))
                if "agenda_handoffs" in tables:
                    for row in legacy.execute("""SELECT h.*,e.start_at FROM agenda_handoffs h
                        LEFT JOIN calendar_events e ON e.id=(
                            SELECT c.calendar_event_id FROM agenda_handoffs c
                            WHERE c.source_type=h.source_type AND c.source_key=h.source_key
                              AND c.destination='calendar')
                        WHERE h.destination='task'"""):
                        now = _now()
                        due = (datetime.fromisoformat(row["start_at"]).astimezone(ZoneInfo("Asia/Shanghai"))
                               if row["start_at"] else None)
                        db.execute("""INSERT OR IGNORE INTO todos
                            (id,title,notes,due_on,due_time,timezone,priority,completed_at,repeat_frequency,
                             repeat_days,repeat_until,source_type,source_key,source_url,user_modified,briefing_id,
                             created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (str(uuid.uuid4()), row["title"], row["summary"],
                             due.date().isoformat() if due else None,
                             due.strftime("%H:%M") if due else None, "Asia/Shanghai",
                             0, None, "none", "[]", None, "briefing", row["source_key"], "", 0,
                             row["briefing_id"], now, now))
            db.execute("INSERT INTO todo_migrations VALUES ('calendar_affairs_v1')")

    def _record_legacy_claims(self):
        """Keep old destructive claims visible without assuming they were shown."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM todo_migrations WHERE name='desktop_reminders_v1'").fetchone():
                return
            for row in db.execute("SELECT todo_id,occurrence_on,notified_at FROM todo_notifications"):
                occurrence_id = str(uuid.uuid4())
                inserted = db.execute("""INSERT OR IGNORE INTO reminder_occurrences
                    (occurrence_id,todo_id,occurrence_on,reminder_kind,due_at,state)
                    VALUES (?,?,?,'due',?,'legacy_claimed_unknown')""",
                    (occurrence_id, row["todo_id"], row["occurrence_on"], row["notified_at"]))
                if inserted.rowcount:
                    db.execute("""INSERT INTO reminder_deliveries
                        (delivery_id,occurrence_id,status,error) VALUES (?,?,'legacy_claimed_unknown',?)""",
                        (str(uuid.uuid4()), occurrence_id,
                         "Claimed by the former renderer; OS delivery is unknown"))
            db.execute("INSERT INTO todo_migrations VALUES ('desktop_reminders_v1')")

    @staticmethod
    def _validate_todo(payload, existing=None):
        if not isinstance(payload, dict):
            raise ValueError("todo must be an object")
        row = dict(existing or {})
        for key in ("title", "notes", "due_on", "due_time", "timezone", "priority",
                    "repeat_frequency", "repeat_days", "repeat_until"):
            if key in payload:
                row[key] = payload[key]
        row["title"] = _text(row.get("title"), "title")
        notes = row.get("notes") or ""
        if not isinstance(notes, str) or len(notes) > 4000:
            raise ValueError("notes must be at most 4000 characters")
        row["notes"] = notes
        due_on = row.get("due_on") or None
        if due_on:
            try:
                due_on = date.fromisoformat(due_on).isoformat()
            except (ValueError, TypeError) as exc:
                raise ValueError("due_on must be YYYY-MM-DD") from exc
        row["due_on"] = due_on
        due_time = row.get("due_time") or None
        if due_time:
            try:
                due_time = time.fromisoformat(due_time)
            except (ValueError, TypeError) as exc:
                raise ValueError("due_time must be HH:MM") from exc
            if due_time.second or due_time.microsecond or due_on is None:
                raise ValueError("due_time requires a date and minute precision")
            due_time = due_time.strftime("%H:%M")
        row["due_time"] = due_time
        zone = row.get("timezone") or "UTC"
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
            raise ValueError("invalid timezone") from exc
        row["timezone"] = zone
        priority = row.get("priority", 0)
        if type(priority) is not int or priority < 0 or priority > 3:
            raise ValueError("priority must be 0-3")
        row["priority"] = priority
        frequency = row.get("repeat_frequency") or "none"
        if frequency not in ("none", "daily", "weekly", "monthly", "yearly") or (frequency != "none" and not due_on):
            raise ValueError("repeat_frequency requires a due date")
        row["repeat_frequency"] = frequency
        days = row.get("repeat_days") or []
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
                until = date.fromisoformat(until).isoformat()
            except (ValueError, TypeError) as exc:
                raise ValueError("repeat_until must be YYYY-MM-DD") from exc
            if not due_on or until < due_on:
                raise ValueError("repeat_until must follow due_on")
        row["repeat_until"] = until if frequency != "none" else None
        return row

    def create_todo(self, payload):
        row = self._validate_todo(payload)
        todo_id, now = str(uuid.uuid4()), _now()
        with self._connect() as db:
            db.execute("""INSERT INTO todos
                (id,title,notes,due_on,due_time,timezone,priority,completed_at,repeat_frequency,
                 repeat_days,repeat_until,source_type,source_key,source_url,user_modified,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (todo_id, row["title"], row["notes"], row["due_on"], row["due_time"], row["timezone"],
                 row["priority"], None, row["repeat_frequency"], row["repeat_days"], row["repeat_until"],
                 None, None, "", 0, now, now))
        return self.get_todo(todo_id)

    def get_todo(self, todo_id):
        if not isinstance(todo_id, str) or not todo_id:
            raise ValueError("todo id is required")
        with self._connect() as db:
            row = db.execute("SELECT * FROM todos WHERE id=?", (todo_id.split("@", 1)[0],)).fetchone()
        if row is None:
            raise KeyError("todo not found")
        return dict(row)

    def update_todo(self, todo_id, payload):
        old = self.get_todo(todo_id)
        row = self._validate_todo(payload, old)
        with self._connect() as db:
            self._cancel_pending_reminders(db, old["id"])
            db.execute("""UPDATE todos SET title=?, notes=?, due_on=?, due_time=?, timezone=?,
                priority=?, repeat_frequency=?, repeat_days=?, repeat_until=?, user_modified=1, updated_at=?
                WHERE id=?""", (row["title"], row["notes"], row["due_on"], row["due_time"], row["timezone"],
                row["priority"], row["repeat_frequency"], row["repeat_days"], row["repeat_until"], _now(), old["id"]))
        return self.get_todo(old["id"])

    def delete_todo(self, todo_id):
        old = self.get_todo(todo_id)
        with self._connect() as db:
            if old["source_type"] == "briefing" and old["source_key"]:
                db.execute("INSERT OR REPLACE INTO source_tombstones VALUES (?,?)",
                           (old["source_key"], _now()))
            self._cancel_pending_reminders(db, old["id"])
            db.execute("DELETE FROM todos WHERE id=?", (old["id"],))

    def complete_todo(self, todo_id, completed):
        if type(completed) is not bool:
            raise ValueError("completed must be true or false")
        old = self.get_todo(todo_id)
        occurrence = todo_id.split("@", 1)[1] if "@" in todo_id else None
        if old["repeat_frequency"] != "none":
            if not occurrence:
                raise ValueError("recurring todo requires an occurrence date")
            try:
                occurrence = date.fromisoformat(occurrence).isoformat()
            except ValueError as exc:
                raise ValueError("invalid occurrence date") from exc
            if not self._todo_matches(old, date.fromisoformat(occurrence)):
                raise ValueError("date is not a todo occurrence")
        elif occurrence:
            raise ValueError("nonrecurring todo has no occurrence id")
        now = _now()
        with self._connect() as db:
            if completed:
                self._cancel_pending_reminders(db, old["id"], occurrence)
            if occurrence:
                if completed:
                    db.execute("INSERT OR IGNORE INTO todo_completions VALUES (?,?,?)",
                               (old["id"], occurrence, now))
                else:
                    db.execute("DELETE FROM todo_completions WHERE todo_id=? AND occurrence_on=?",
                               (old["id"], occurrence))
            else:
                db.execute("UPDATE todos SET completed_at=? WHERE id=?", (now if completed else None, old["id"]))
            db.execute("UPDATE todos SET user_modified=1, updated_at=? WHERE id=?", (now, old["id"]))
        return self.get_todo(old["id"])

    @staticmethod
    def _cancel_pending_reminders(db, todo_id, occurrence_on=None):
        condition = "AND occurrence_on=?" if occurrence_on else ""
        params = (todo_id, occurrence_on) if occurrence_on else (todo_id,)
        ids = [row[0] for row in db.execute(
            "SELECT occurrence_id FROM reminder_occurrences WHERE todo_id=? " + condition +
            " AND state='pending'", params)]
        for occurrence_id in ids:
            db.execute("UPDATE reminder_occurrences SET state='cancelled' WHERE occurrence_id=?", (occurrence_id,))
            db.execute("""UPDATE reminder_deliveries SET status='cancelled',claim_id=NULL,lease_until=NULL
                WHERE occurrence_id=? AND status!='shown'""", (occurrence_id,))

    def claim_desktop_reminders(self, now=None, limit=20):
        """Lease due reminders; repeated claims after a crash may show twice."""
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None:
            raise ValueError("now must include a timezone")
        instant = instant.astimezone(timezone.utc)
        oldest = instant - timedelta(days=1)
        leased = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM todos WHERE due_on IS NOT NULL AND due_time IS NOT NULL").fetchall()
            for stored in rows:
                row = dict(stored)
                zone = ZoneInfo(row["timezone"])
                candidate = oldest.astimezone(zone).date()
                last = instant.astimezone(zone).date()
                while candidate <= last:
                    day = candidate.isoformat()
                    matches = (day == row["due_on"] and not row["completed_at"]
                               if row["repeat_frequency"] == "none" else
                               self._todo_matches(row, candidate) and not db.execute(
                                   "SELECT 1 FROM todo_completions WHERE todo_id=? AND occurrence_on=?",
                                   (row["id"], day)).fetchone())
                    if matches:
                        due_at = datetime.combine(candidate, time.fromisoformat(row["due_time"]), zone).astimezone(timezone.utc)
                        if oldest <= due_at <= instant:
                            # Legacy destructive claims have unknown delivery state.
                            legacy = db.execute("SELECT 1 FROM todo_notifications WHERE todo_id=? AND occurrence_on=?",
                                                (row["id"], day)).fetchone()
                            if not legacy:
                                occurrence_id = str(uuid.uuid4())
                                inserted = db.execute("""INSERT OR IGNORE INTO reminder_occurrences
                                    (occurrence_id,todo_id,occurrence_on,reminder_kind,due_at)
                                    VALUES (?,?,?,'due',?)""",
                                    (occurrence_id, row["id"], day, due_at.isoformat()))
                                if inserted.rowcount:
                                    db.execute("INSERT INTO reminder_deliveries(delivery_id,occurrence_id) VALUES (?,?)",
                                               (str(uuid.uuid4()), occurrence_id))
                                else:
                                    cancelled = db.execute("""SELECT occurrence_id FROM reminder_occurrences
                                        WHERE todo_id=? AND occurrence_on=? AND reminder_kind='due'
                                        AND state='cancelled'""", (row["id"], day)).fetchone()
                                    if cancelled:
                                        db.execute("""UPDATE reminder_occurrences SET state='pending',due_at=?
                                            WHERE occurrence_id=?""", (due_at.isoformat(), cancelled[0]))
                                        db.execute("""UPDATE reminder_deliveries SET status='pending',claim_id=NULL,
                                            lease_until=NULL,error=NULL WHERE occurrence_id=?""", (cancelled[0],))
                    candidate += timedelta(days=1)
            candidates = db.execute("""SELECT d.delivery_id,o.occurrence_id,o.todo_id,o.occurrence_on,
                t.title FROM reminder_deliveries d JOIN reminder_occurrences o ON o.occurrence_id=d.occurrence_id
                JOIN todos t ON t.id=o.todo_id
                WHERE o.state='pending' AND (d.status IN ('pending','retry') OR
                    (d.status='leased' AND d.lease_until<=?))
                ORDER BY o.due_at LIMIT ?""", (instant.isoformat(), limit)).fetchall()
            lease_until = (instant + timedelta(minutes=2)).isoformat()
            for row in candidates:
                claim_id = str(uuid.uuid4())
                db.execute("""UPDATE reminder_deliveries SET status='leased',claim_id=?,lease_until=?,
                    attempts=attempts+1 WHERE delivery_id=?""",
                    (claim_id, lease_until, row["delivery_id"]))
                leased.append({"delivery_id": row["delivery_id"], "claim_id": claim_id,
                               "todo_id": row["todo_id"], "occurrence_on": row["occurrence_on"],
                               "title": row["title"], "lease_until": lease_until})
        return leased

    def acknowledge_desktop_reminder(self, delivery_id, claim_id, shown, error=None):
        if not delivery_id or not claim_id or type(shown) is not bool:
            raise ValueError("delivery_id, claim_id and shown are required")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM reminder_deliveries WHERE delivery_id=?",
                             (delivery_id,)).fetchone()
            if not row or row["claim_id"] != claim_id:
                return False
            if row["status"] == "shown":
                return True
            if row["status"] != "leased":
                return False
            status = "shown" if shown else "retry"
            db.execute("""UPDATE reminder_deliveries SET status=?,lease_until=NULL,
                shown_at=?,error=? WHERE delivery_id=?""",
                (status, _now() if shown else None, None if shown else str(error or "notification failed"), delivery_id))
            if shown:
                db.execute("UPDATE reminder_occurrences SET state='shown' WHERE occurrence_id=?",
                           (row["occurrence_id"],))
            return True

    @staticmethod
    def _todo_matches(row, candidate):
        first = date.fromisoformat(row["due_on"])
        until = date.fromisoformat(row["repeat_until"]) if row["repeat_until"] else None
        if candidate < first or (until and candidate > until):
            return False
        frequency = row["repeat_frequency"]
        weekdays = json.loads(row["repeat_days"] or "[]") or [first.weekday()]
        return (frequency == "daily" or
                frequency == "weekly" and candidate.weekday() in weekdays or
                frequency == "monthly" and candidate.day == first.day or
                frequency == "yearly" and (candidate.month, candidate.day) == (first.month, first.day))

    def list_todos(self, start=None, end=None, include_completed=True):
        try:
            first = date.fromisoformat(start) if start else None
            last = date.fromisoformat(end) if end else None
        except (ValueError, TypeError) as exc:
            raise ValueError("todo range must use YYYY-MM-DD") from exc
        if (first is None) != (last is None) or (first and (last <= first or (last - first).days > 370)):
            raise ValueError("invalid todo range")
        with self._connect() as db:
            templates = [dict(row) for row in db.execute("SELECT * FROM todos ORDER BY due_on, priority DESC, created_at")]
            completions = {(row["todo_id"], row["occurrence_on"]): row["completed_at"]
                           for row in db.execute("SELECT * FROM todo_completions")}
        if first is None:
            return [row for row in templates if include_completed or not row["completed_at"]]
        result = []
        for row in templates:
            if not row["due_on"]:
                continue
            if row["repeat_frequency"] == "none":
                if first <= date.fromisoformat(row["due_on"]) < last and (include_completed or not row["completed_at"]):
                    result.append(row)
                continue
            candidate = max(first, date.fromisoformat(row["due_on"]))
            while candidate < last:
                if self._todo_matches(row, candidate):
                    item = dict(row)
                    item["series_id"] = row["id"]
                    item["id"] = f"{row['id']}@{candidate.isoformat()}"
                    item["due_on"] = candidate.isoformat()
                    item["completed_at"] = completions.get((row["id"], item["due_on"]))
                    if include_completed or not item["completed_at"]:
                        result.append(item)
                candidate += timedelta(days=1)
        return sorted(result, key=lambda row: (row["due_on"], row["due_time"] or "", -row["priority"], row["id"]))

    def claim_due_todo_notifications(self, now=None):
        """Claim timed reminders due in the past day, once per occurrence."""
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None:
            raise ValueError("now must include a timezone")
        instant = instant.astimezone(timezone.utc)
        oldest = instant - timedelta(days=1)
        claimed = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM todos WHERE due_on IS NOT NULL AND due_time IS NOT NULL").fetchall()
            for stored in rows:
                row = dict(stored)
                zone = ZoneInfo(row["timezone"])
                candidate = oldest.astimezone(zone).date()
                last = instant.astimezone(zone).date()
                while candidate <= last:
                    day = candidate.isoformat()
                    if row["repeat_frequency"] == "none":
                        matches = day == row["due_on"] and not row["completed_at"]
                    else:
                        matches = self._todo_matches(row, candidate) and not db.execute(
                            "SELECT 1 FROM todo_completions WHERE todo_id=? AND occurrence_on=?",
                            (row["id"], day)).fetchone()
                    if matches:
                        due_at = datetime.combine(candidate, time.fromisoformat(row["due_time"]), zone).astimezone(timezone.utc)
                        if oldest <= due_at <= instant:
                            cursor = db.execute("INSERT OR IGNORE INTO todo_notifications VALUES (?,?,?)",
                                                (row["id"], day, instant.isoformat()))
                            if cursor.rowcount:
                                item = dict(row)
                                item["id"] = f"{row['id']}@{day}" if row["repeat_frequency"] != "none" else row["id"]
                                item["due_on"] = day
                                claimed.append(item)
                    candidate += timedelta(days=1)
        return claimed

    def _upsert_sourced_todo(self, source_key, item, due_value, briefing_id, db=None):
        if db is None:
            with self._connect() as connection:
                return self._upsert_sourced_todo(source_key, item, due_value, briefing_id, connection)
        try:
            due = datetime.fromisoformat(due_value.replace("Z", "+00:00")) if due_value else None
            if due and due.tzinfo is None:
                due = None
        except (ValueError, TypeError, AttributeError):
            due = None
        zone = ZoneInfo("Asia/Shanghai")
        local_due = due.astimezone(zone) if due else None
        now = _now()
        if db.execute("SELECT 1 FROM source_tombstones WHERE source_key=?", (source_key,)).fetchone():
            return
        old = db.execute("SELECT * FROM todos WHERE source_type='briefing' AND source_key=?",
                             (source_key,)).fetchone()
        if old and old["user_modified"]:
            return
        db.execute("""INSERT INTO todos
                (id,title,notes,due_on,due_time,timezone,priority,completed_at,repeat_frequency,
                 repeat_days,repeat_until,source_type,source_key,source_url,user_modified,briefing_id,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_type,source_key) DO UPDATE SET title=excluded.title,notes=excluded.notes,
                due_on=excluded.due_on,due_time=excluded.due_time,source_url=excluded.source_url,
                briefing_id=excluded.briefing_id,updated_at=excluded.updated_at""",
                (old["id"] if old else str(uuid.uuid4()), item.title, getattr(item, "snippet", "") or "",
                 local_due.date().isoformat() if local_due else None,
                 local_due.strftime("%H:%M") if local_due else None, "Asia/Shanghai", 0, None,
                 "none", "[]", None, "briefing", source_key, getattr(item, "url", "") or "", 0,
                 briefing_id, now, now))

    def ingest_briefing_revision(self, detail, revision):
        briefing_id = detail["briefing"].id
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT last_revision FROM briefing_applied WHERE briefing_id=?",
                             (briefing_id,)).fetchone()
            if row and row[0] >= revision:
                return
            self.ingest_briefing(detail, db=db)
            db.execute("""INSERT INTO briefing_applied VALUES (?,?)
                ON CONFLICT(briefing_id) DO UPDATE SET last_revision=excluded.last_revision""",
                (briefing_id, revision))

    def ingest_briefing(self, detail, db=None):
        """Sync action items from a briefing without creating calendar events."""
        if db is None:
            with self._connect() as connection:
                return self.ingest_briefing(detail, db=connection)
        briefing = detail["briefing"]
        decisions = {row["id"]: row.get("decision") or {} for row in detail.get("mail", [])}
        items = list(detail.get("items", []))
        covered = {item.source_item_id for item in items}
        for row in detail.get("mail", []):
            if row.get("category") != "selected" or row.get("id") in covered:
                continue
            decision = row.get("decision") or {}
            card = next((item for item in items if getattr(item, "thread_id", "") and item.thread_id == row.get("thread_id")), None)
            items.append(SimpleNamespace(
                source=row["source"], account_id=row["account_id"], source_id=row["source_id"],
                source_item_id=row["id"], section=decision.get("section", "fyi"),
                title=row["title"], snippet=decision.get("summary") or row.get("snippet", ""),
                payload=row.get("metadata") or {}, url=row.get("url", ""),
                id=card.id if card else row["id"],
            ))
        current_keys = set()
        for item in items:
            source_key = json.dumps([item.source, item.account_id, item.source_id], ensure_ascii=False, separators=(",", ":"))
            current_keys.add(source_key)
            decision = decisions.get(item.source_item_id, {})
            calendar = decision.get("calendar") if isinstance(decision.get("calendar"), dict) else {}
            due_at = item.payload.get("due_at") if isinstance(item.payload, dict) else None
            if item.section == "action":
                self._upsert_sourced_todo(source_key, item, due_at or calendar.get("start_at"), briefing.id, db=db)
            else:
                db.execute("DELETE FROM todos WHERE source_type='briefing' AND source_key=? AND user_modified=0",
                           (source_key,))
        for row in db.execute("SELECT id,source_key FROM todos WHERE source_type='briefing' AND briefing_id=?",
                                  (briefing.id,)).fetchall():
            if row["source_key"] not in current_keys:
                db.execute("DELETE FROM todos WHERE id=? AND user_modified=0", (row["id"],))
