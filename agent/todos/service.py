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


TODO_STATUSES = frozenset({"todo", "in_progress", "waiting", "blocked", "completed", "cancelled"})
TERMINAL_STATUSES = frozenset({"completed", "cancelled"})


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
                CREATE TABLE IF NOT EXISTS todo_checklist_completions (
                    todo_id TEXT NOT NULL, occurrence_on TEXT NOT NULL, item_id TEXT NOT NULL,
                    PRIMARY KEY(todo_id, occurrence_on, item_id),
                    FOREIGN KEY(todo_id) REFERENCES todos(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS todo_dependencies (
                    task_id TEXT NOT NULL, prerequisite_id TEXT NOT NULL,
                    PRIMARY KEY(task_id, prerequisite_id),
                    FOREIGN KEY(task_id) REFERENCES todos(id) ON DELETE CASCADE,
                    FOREIGN KEY(prerequisite_id) REFERENCES todos(id) ON DELETE CASCADE
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
            columns = {row[1] for row in db.execute("PRAGMA table_info(todos)")}
            for name, definition in (
                ("planned_on", "TEXT"), ("list_name", "TEXT NOT NULL DEFAULT ''"),
                ("tags", "TEXT NOT NULL DEFAULT '[]'"), ("flagged", "INTEGER NOT NULL DEFAULT 0"),
                ("checklist", "TEXT NOT NULL DEFAULT '[]'"),
                ("status", "TEXT NOT NULL DEFAULT 'todo'"), ("parent_id", "TEXT"),
                ("sort_order", "INTEGER NOT NULL DEFAULT 0"), ("remind_at", "TEXT"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE todos ADD COLUMN {name} {definition}")
            db.execute("CREATE INDEX IF NOT EXISTS todos_parent_order ON todos(parent_id,sort_order,created_at)")
            if "status" not in columns:
                db.execute("UPDATE todos SET status='completed' WHERE completed_at IS NOT NULL")
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
                kind = "custom" if "T" in row["occurrence_on"] else "due"
                inserted = db.execute("""INSERT OR IGNORE INTO reminder_occurrences
                    (occurrence_id,todo_id,occurrence_on,reminder_kind,due_at,state)
                    VALUES (?,?,?,?,?,'legacy_claimed_unknown')""",
                    (occurrence_id, row["todo_id"], row["occurrence_on"], kind, row["notified_at"]))
                if inserted.rowcount:
                    db.execute("""INSERT INTO reminder_deliveries
                        (delivery_id,occurrence_id,status,error) VALUES (?,?,'legacy_claimed_unknown',?)""",
                        (str(uuid.uuid4()), occurrence_id,
                         "Claimed by the former renderer; OS delivery is unknown"))
            db.execute("INSERT INTO todo_migrations VALUES ('desktop_reminders_v1')")

    def list_uncertain_reminders(self):
        """Expose former renderer claims whose OS delivery cannot be confirmed."""
        with self._connect() as db:
            rows = db.execute("""SELECT d.delivery_id,o.todo_id,o.occurrence_on,t.title
                FROM reminder_deliveries d
                JOIN reminder_occurrences o ON o.occurrence_id=d.occurrence_id
                JOIN todos t ON t.id=o.todo_id
                WHERE d.status='legacy_claimed_unknown'
                ORDER BY o.occurrence_on,t.title""").fetchall()
            return [dict(row) for row in rows]

    def retry_uncertain_reminder(self, delivery_id):
        """Queue an explicit retry only while the original occurrence is valid."""
        if not isinstance(delivery_id, str) or not delivery_id:
            raise ValueError("delivery_id is required")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT d.status,o.occurrence_id,o.occurrence_on,o.reminder_kind,o.due_at,t.*
                FROM reminder_deliveries d
                JOIN reminder_occurrences o ON o.occurrence_id=d.occurrence_id
                JOIN todos t ON t.id=o.todo_id WHERE d.delivery_id=?""",
                (delivery_id,)).fetchone()
            if not row or row["status"] != "legacy_claimed_unknown":
                raise ValueError("uncertain reminder not found")
            # A legacy row stores the old claim time in due_at. Any edit after
            # that claim makes the old reminder payload or timing uncertain.
            changed_since_claim = datetime.fromisoformat(row["updated_at"]) > datetime.fromisoformat(row["due_at"])
            if row["reminder_kind"] == "custom":
                valid = (row["remind_at"] == row["occurrence_on"] and
                         row["status"] not in TERMINAL_STATUSES)
            else:
                day = date.fromisoformat(row["occurrence_on"])
                valid = bool(row["due_time"]) and (
                    day.isoformat() == row["due_on"] and not row["completed_at"]
                    if row["repeat_frequency"] == "none" else
                    self._todo_matches(row, day) and not db.execute(
                        "SELECT 1 FROM todo_completions WHERE todo_id=? AND occurrence_on=?",
                        (row["todo_id"], row["occurrence_on"])).fetchone())
            if not valid or changed_since_claim:
                db.execute("UPDATE reminder_occurrences SET state='cancelled' WHERE occurrence_id=?",
                           (row["occurrence_id"],))
                db.execute("""UPDATE reminder_deliveries SET status='cancelled',error='todo changed or completed'
                    WHERE delivery_id=?""", (delivery_id,))
                return False
            db.execute("UPDATE reminder_occurrences SET state='pending' WHERE occurrence_id=?",
                       (row["occurrence_id"],))
            db.execute("""UPDATE reminder_deliveries SET status='pending',claim_id=NULL,
                lease_until=NULL,error=NULL WHERE delivery_id=?""", (delivery_id,))
        return True

    @staticmethod
    def _validate_todo(payload, existing=None):
        if not isinstance(payload, dict):
            raise ValueError("todo must be an object")
        row = dict(existing or {})
        for key in ("title", "notes", "due_on", "due_time", "timezone", "priority",
                    "repeat_frequency", "repeat_days", "repeat_until", "planned_on",
                    "list_name", "tags", "flagged", "checklist", "remind_at"):
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
        planned = row.get("planned_on") or None
        if planned:
            try:
                planned = date.fromisoformat(planned).isoformat()
            except (ValueError, TypeError) as exc:
                raise ValueError("planned_on must be YYYY-MM-DD") from exc
        row["planned_on"] = planned
        reminder = row.get("remind_at") or None
        if reminder:
            try:
                instant = datetime.fromisoformat(reminder.replace("Z", "+00:00"))
                if instant.tzinfo is None:
                    raise ValueError("timezone required")
                reminder = instant.astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError("remind_at must be an ISO timestamp with timezone") from exc
        row["remind_at"] = reminder
        if frequency != "none" and reminder:
            raise ValueError("recurring tasks use their due time for reminders")
        list_name = row.get("list_name") or ""
        if not isinstance(list_name, str) or len(list_name.strip()) > 80:
            raise ValueError("list_name must be at most 80 characters")
        row["list_name"] = list_name.strip()
        flagged = row.get("flagged", False)
        if type(flagged) not in (bool, int) or flagged not in (0, 1):
            raise ValueError("flagged must be true or false")
        row["flagged"] = int(flagged)
        for field in ("tags", "checklist"):
            values = row.get(field) or []
            if isinstance(values, str):
                try:
                    values = json.loads(values)
                except ValueError as exc:
                    raise ValueError(f"invalid {field}") from exc
            if not isinstance(values, list) or len(values) > 100:
                raise ValueError(f"{field} must be an array of at most 100 items")
            if field == "tags":
                values = list(dict.fromkeys(_text(value, "tag", 40) for value in values))
            else:
                cleaned = []
                ids = set()
                for item in values:
                    if not isinstance(item, dict) or type(item.get("completed", False)) is not bool:
                        raise ValueError("checklist items need a title and boolean completed")
                    item_id = _text(item.get("id") or str(uuid.uuid4()), "checklist id", 80)
                    if item_id in ids:
                        raise ValueError("duplicate checklist id")
                    ids.add(item_id)
                    cleaned.append({"id": item_id, "title": _text(item.get("title"), "checklist title", 500),
                                    "completed": item.get("completed", False)})
                values = cleaned
                if frequency != "none":
                    values = [{**item, "completed": False} for item in values]
            row[field] = json.dumps(values, ensure_ascii=False)
        return row

    def create_todo(self, payload):
        row = self._validate_todo(payload)
        status = self._status(payload.get("status", "todo"))
        if row["repeat_frequency"] != "none" and status != "todo":
            raise ValueError("recurring task status is set per occurrence")
        parent_id = payload.get("parent_id")
        todo_id, now = str(uuid.uuid4()), _now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_parent(db, todo_id, parent_id, row["repeat_frequency"])
            order = self._next_order(db, parent_id)
            db.execute("""INSERT INTO todos
                (id,title,notes,due_on,due_time,timezone,priority,completed_at,repeat_frequency,
                 repeat_days,repeat_until,source_type,source_key,source_url,user_modified,created_at,updated_at,
                 planned_on,list_name,tags,flagged,checklist,status,parent_id,sort_order,remind_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (todo_id, row["title"], row["notes"], row["due_on"], row["due_time"], row["timezone"],
                 row["priority"], now if status == "completed" else None,
                 row["repeat_frequency"], row["repeat_days"], row["repeat_until"],
                 None, None, "", 0, now, now, row["planned_on"], row["list_name"], row["tags"],
                 row["flagged"], row["checklist"], status, parent_id, order, row["remind_at"]))
        return self.get_todo(todo_id)

    def get_todo(self, todo_id):
        if not isinstance(todo_id, str) or not todo_id:
            raise ValueError("todo id is required")
        with self._connect() as db:
            row = db.execute("SELECT * FROM todos WHERE id=?", (todo_id.split("@", 1)[0],)).fetchone()
            if row is None:
                raise KeyError("todo not found")
            return self._with_progress(db, dict(row))

    def update_todo(self, todo_id, payload):
        old = self.get_todo(todo_id)
        row = self._validate_todo(payload, old)
        with self._connect() as db:
            if row["repeat_frequency"] != "none" and old["status"] != "todo":
                raise ValueError("recurring task status is set per occurrence")
            if row["repeat_frequency"] != old["repeat_frequency"] and old["parent_id"]:
                raise ValueError("subtasks cannot repeat")
            if row["repeat_frequency"] != "none" and db.execute(
                "SELECT 1 FROM todos WHERE parent_id=?", (old["id"],)).fetchone():
                raise ValueError("tasks with subtasks cannot repeat")
            if row["repeat_frequency"] != "none" and db.execute(
                "SELECT 1 FROM todo_dependencies WHERE task_id=? OR prerequisite_id=?",
                (old["id"], old["id"])).fetchone():
                raise ValueError("tasks with dependencies cannot repeat")
            self._cancel_pending_reminders(db, old["id"])
            db.execute("""UPDATE todos SET title=?, notes=?, due_on=?, due_time=?, timezone=?,
                priority=?, repeat_frequency=?, repeat_days=?, repeat_until=?, user_modified=1, updated_at=?
                , planned_on=?, list_name=?, tags=?, flagged=?, checklist=?, remind_at=? WHERE id=?""",
                (row["title"], row["notes"], row["due_on"], row["due_time"], row["timezone"],
                row["priority"], row["repeat_frequency"], row["repeat_days"], row["repeat_until"], _now(),
                row["planned_on"], row["list_name"], row["tags"], row["flagged"], row["checklist"],
                row["remind_at"], old["id"]))
        return self.get_todo(old["id"])

    def delete_todo(self, todo_id):
        old = self.get_todo(todo_id)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            descendants = db.execute("""WITH RECURSIVE subtree(id) AS (
                SELECT id FROM todos WHERE id=? UNION
                SELECT t.id FROM todos t JOIN subtree s ON t.parent_id=s.id)
                SELECT t.id,t.source_type,t.source_key FROM todos t JOIN subtree s ON t.id=s.id""",
                (old["id"],)).fetchall()
            for item in descendants:
                if item["source_type"] == "briefing" and item["source_key"]:
                    db.execute("INSERT OR REPLACE INTO source_tombstones VALUES (?,?)",
                               (item["source_key"], _now()))
                self._cancel_pending_reminders(db, item["id"])
                db.execute("DELETE FROM todos WHERE id=?", (item["id"],))

    @staticmethod
    def _status(value):
        if value not in TODO_STATUSES:
            raise ValueError("invalid todo status")
        return value

    @staticmethod
    def _next_order(db, parent_id):
        row = db.execute("SELECT MAX(sort_order) FROM todos WHERE parent_id IS ?", (parent_id,)).fetchone()
        return (row[0] or 0) + 1

    @staticmethod
    def _with_progress(db, row):
        children = db.execute("SELECT status FROM todos WHERE parent_id=?", (row["id"],)).fetchall()
        effective = [child for child in children if child["status"] != "cancelled"]
        done = sum(child["status"] == "completed" for child in effective)
        row.update(subtask_count=len(children), progress_completed=done,
                   progress_total=len(effective), progress_percent=round(100 * done / len(effective)) if effective else 0)
        dependencies = db.execute("""SELECT d.prerequisite_id,t.status FROM todo_dependencies d
            JOIN todos t ON t.id=d.prerequisite_id WHERE d.task_id=?""", (row["id"],)).fetchall()
        row["dependency_ids"] = [item["prerequisite_id"] for item in dependencies]
        row["blocked_by"] = [item["prerequisite_id"] for item in dependencies if item["status"] != "completed"]
        return row

    @staticmethod
    def _validate_parent(db, todo_id, parent_id, frequency):
        if parent_id is None:
            return
        if not isinstance(parent_id, str) or not parent_id or "@" in parent_id or parent_id == todo_id:
            raise ValueError("invalid parent task")
        parent = db.execute("SELECT id,parent_id,repeat_frequency FROM todos WHERE id=?", (parent_id,)).fetchone()
        if not parent:
            raise ValueError("parent task not found")
        if frequency != "none" or parent["repeat_frequency"] != "none":
            raise ValueError("recurring tasks cannot have subtasks")
        ancestor = parent
        visited = set()
        while ancestor:
            if ancestor["id"] == todo_id or ancestor["id"] in visited:
                raise ValueError("task hierarchy cannot contain a cycle")
            visited.add(ancestor["id"])
            ancestor = db.execute("SELECT id,parent_id FROM todos WHERE id=?", (ancestor["parent_id"],)).fetchone() if ancestor["parent_id"] else None

    def add_subtask(self, parent_id, payload):
        if not isinstance(payload, dict):
            raise ValueError("todo must be an object")
        return self.create_todo({**payload, "parent_id": parent_id})

    def move_todo(self, todo_id, parent_id=None, position=None):
        old = self.get_todo(todo_id)
        if "@" in todo_id:
            raise ValueError("move the series, not an occurrence")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_parent(db, old["id"], parent_id, old["repeat_frequency"])
            siblings = [row[0] for row in db.execute(
                "SELECT id FROM todos WHERE parent_id IS ? AND id!=? ORDER BY sort_order,created_at,id",
                (parent_id, old["id"]))]
            if position is None:
                position = len(siblings)
            if type(position) is not int or position < 0 or position > len(siblings):
                raise ValueError("invalid sibling position")
            siblings.insert(position, old["id"])
            now = _now()
            for index, sibling in enumerate(siblings):
                db.execute("UPDATE todos SET parent_id=?,sort_order=?,updated_at=? WHERE id=?",
                           (parent_id, index + 1, now, sibling))
            db.execute("UPDATE todos SET user_modified=1 WHERE id=?", (old["id"],))
        return self.get_todo(old["id"])

    def add_dependency(self, todo_id, prerequisite_id):
        if not isinstance(todo_id, str) or not isinstance(prerequisite_id, str) or not todo_id or not prerequisite_id:
            raise ValueError("task and prerequisite ids are required")
        if todo_id == prerequisite_id or "@" in todo_id or "@" in prerequisite_id:
            raise ValueError("invalid task dependency")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            tasks = db.execute("SELECT id,repeat_frequency,status FROM todos WHERE id IN (?,?)",
                               (todo_id, prerequisite_id)).fetchall()
            if len(tasks) != 2:
                raise ValueError("task dependency target not found")
            if any(item["repeat_frequency"] != "none" for item in tasks):
                raise ValueError("recurring tasks cannot have dependencies")
            states = {item["id"]: item["status"] for item in tasks}
            if states[todo_id] in ("in_progress", "completed") and states[prerequisite_id] != "completed":
                raise ValueError("finish the prerequisite before adding it to an active task")
            cycle = db.execute("""WITH RECURSIVE chain(id) AS (
                SELECT prerequisite_id FROM todo_dependencies WHERE task_id=?
                UNION SELECT d.prerequisite_id FROM todo_dependencies d JOIN chain c ON d.task_id=c.id)
                SELECT 1 FROM chain WHERE id=?""", (prerequisite_id, todo_id)).fetchone()
            if cycle:
                raise ValueError("task dependencies cannot contain a cycle")
            db.execute("INSERT OR IGNORE INTO todo_dependencies VALUES (?,?)", (todo_id, prerequisite_id))
            db.execute("UPDATE todos SET user_modified=1,updated_at=? WHERE id=?", (_now(), todo_id))
        return self.get_todo(todo_id)

    def remove_dependency(self, todo_id, prerequisite_id):
        old = self.get_todo(todo_id)
        with self._connect() as db:
            db.execute("DELETE FROM todo_dependencies WHERE task_id=? AND prerequisite_id=?",
                       (old["id"], prerequisite_id))
            db.execute("UPDATE todos SET user_modified=1,updated_at=? WHERE id=?", (_now(), old["id"]))
        return self.get_todo(old["id"])

    def change_todo_status(self, todo_id, status, force=False):
        status = self._status(status)
        if type(force) is not bool:
            raise ValueError("force must be true or false")
        old = self.get_todo(todo_id)
        if status == "completed" and old["repeat_frequency"] != "none":
            return self.complete_todo(todo_id, True, force=force)
        if "@" in todo_id:
            raise ValueError("recurring occurrence only supports completion")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if status in ("in_progress", "completed") and not force:
                blocked = db.execute("""SELECT COUNT(*) FROM todo_dependencies d
                    JOIN todos t ON t.id=d.prerequisite_id
                    WHERE d.task_id=? AND t.status!='completed'""", (old["id"],)).fetchone()[0]
                if blocked:
                    raise ValueError(f"unfinished_dependencies:{blocked}")
            if status == "completed" and not force:
                pending = db.execute("""WITH RECURSIVE subtree(id) AS (
                    SELECT id FROM todos WHERE parent_id=? UNION ALL
                    SELECT t.id FROM todos t JOIN subtree s ON t.parent_id=s.id)
                    SELECT COUNT(*) FROM todos WHERE id IN (SELECT id FROM subtree)
                    AND status NOT IN ('completed','cancelled')""", (old["id"],)).fetchone()[0]
                if pending:
                    raise ValueError(f"unfinished_subtasks:{pending}")
            if status in TERMINAL_STATUSES:
                self._cancel_pending_reminders(db, old["id"])
            now = _now()
            db.execute("UPDATE todos SET status=?,completed_at=?,user_modified=1,updated_at=? WHERE id=?",
                       (status, now if status == "completed" else None, now, old["id"]))
        return self.get_todo(old["id"])

    def complete_todo(self, todo_id, completed, force=False):
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
        if not occurrence:
            return self.change_todo_status(todo_id, "completed" if completed else "todo", force=force)
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

    def complete_checklist_item(self, todo_id, item_id, completed):
        if type(completed) is not bool:
            raise ValueError("completed must be true or false")
        old = self.get_todo(todo_id)
        items = json.loads(old["checklist"])
        if not any(item["id"] == item_id for item in items):
            raise ValueError("checklist item not found")
        if old["repeat_frequency"] == "none":
            if "@" in todo_id:
                raise ValueError("nonrecurring todo has no occurrence id")
            return self.update_todo(todo_id, {"checklist": [
                {**item, "completed": completed} if item["id"] == item_id else item for item in items]})
        occurrence = todo_id.split("@", 1)[1] if "@" in todo_id else None
        try:
            day = date.fromisoformat(occurrence)
        except (TypeError, ValueError) as exc:
            raise ValueError("recurring checklist requires an occurrence date") from exc
        if not self._todo_matches(old, day):
            raise ValueError("date is not a todo occurrence")
        with self._connect() as db:
            if completed:
                db.execute("INSERT OR IGNORE INTO todo_checklist_completions VALUES (?,?,?)",
                           (old["id"], occurrence, item_id))
            else:
                db.execute("DELETE FROM todo_checklist_completions WHERE todo_id=? AND occurrence_on=? AND item_id=?",
                           (old["id"], occurrence, item_id))
            db.execute("UPDATE todos SET user_modified=1,updated_at=? WHERE id=?", (_now(), old["id"]))
        return self.get_todo(old["id"])

    @staticmethod
    def _project_todo(row, day, completions, checklist_completions):
        item = dict(row)
        occurrence_on = day.isoformat()
        item.update(series_id=row["id"], id=f"{row['id']}@{occurrence_on}", due_on=occurrence_on,
                    completed_at=completions.get((row["id"], occurrence_on)))
        item["status"] = "completed" if item["completed_at"] else "todo"
        if row.get("planned_on"):
            item["planned_on"] = (day + (date.fromisoformat(row["planned_on"]) -
                                         date.fromisoformat(row["due_on"]))).isoformat()
        item["checklist"] = json.dumps([{**entry, "completed":
            (row["id"], occurrence_on, entry["id"]) in checklist_completions}
            for entry in json.loads(row.get("checklist") or "[]")], ensure_ascii=False)
        return item

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
            rows = db.execute("SELECT * FROM todos WHERE due_on IS NOT NULL AND due_time IS NOT NULL AND status NOT IN ('completed','cancelled')").fetchall()
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
            for row in db.execute("SELECT * FROM todos WHERE remind_at IS NOT NULL AND status NOT IN ('completed','cancelled')"):
                remind_at = datetime.fromisoformat(row["remind_at"]).astimezone(timezone.utc)
                if oldest <= remind_at <= instant:
                    reminder_key = remind_at.isoformat()
                    occurrence_id = str(uuid.uuid4())
                    inserted = db.execute("""INSERT OR IGNORE INTO reminder_occurrences
                        (occurrence_id,todo_id,occurrence_on,reminder_kind,due_at)
                        VALUES (?,?,?,'custom',?)""",
                        (occurrence_id, row["id"], reminder_key, remind_at.isoformat()))
                    if inserted.rowcount:
                        db.execute("INSERT INTO reminder_deliveries(delivery_id,occurrence_id) VALUES (?,?)",
                                   (str(uuid.uuid4()), occurrence_id))
                    else:
                        cancelled = db.execute("""SELECT occurrence_id FROM reminder_occurrences
                            WHERE todo_id=? AND occurrence_on=? AND reminder_kind='custom'
                            AND state='cancelled'""", (row["id"], reminder_key)).fetchone()
                        if cancelled:
                            db.execute("UPDATE reminder_occurrences SET state='pending',due_at=? WHERE occurrence_id=?",
                                       (remind_at.isoformat(), cancelled[0]))
                            db.execute("""UPDATE reminder_deliveries SET status='pending',claim_id=NULL,
                                lease_until=NULL,error=NULL WHERE occurrence_id=?""", (cancelled[0],))
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
            checklist_completions = {tuple(row) for row in db.execute("SELECT * FROM todo_checklist_completions")}
        if first is None:
            return self._decorate_rows(templates, include_completed)
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
                    item = self._project_todo(row, candidate, completions, checklist_completions)
                    if include_completed or not item["completed_at"]:
                        result.append(item)
                candidate += timedelta(days=1)
        return sorted(self._decorate_rows(result, include_completed),
                      key=lambda row: (row["due_on"], row["due_time"] or "", -row["priority"], row["id"]))

    def _decorate_rows(self, rows, include_completed=True):
        with self._connect() as db:
            counts = {row["id"]: dict(total=row["total"], done=row["done"], count=row["count"])
                      for row in db.execute("""SELECT parent_id AS id, COUNT(*) AS count,
                        SUM(CASE WHEN status!='cancelled' THEN 1 ELSE 0 END) AS total,
                        SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS done
                        FROM todos WHERE parent_id IS NOT NULL GROUP BY parent_id""")}
            dependencies = {}
            for item in db.execute("""SELECT d.task_id,d.prerequisite_id,t.status FROM todo_dependencies d
                JOIN todos t ON t.id=d.prerequisite_id"""):
                dependencies.setdefault(item["task_id"], []).append((item["prerequisite_id"], item["status"]))
        result = []
        for row in rows:
            if not include_completed and row["status"] in TERMINAL_STATUSES:
                continue
            progress = counts.get(row["id"], {"count": 0, "total": 0, "done": 0})
            result.append({**row, "subtask_count": progress["count"],
                           "progress_completed": progress["done"], "progress_total": progress["total"],
                           "progress_percent": round(100 * progress["done"] / progress["total"]) if progress["total"] else 0,
                           "dependency_ids": [item[0] for item in dependencies.get(row.get("series_id", row["id"]), [])],
                           "blocked_by": [item[0] for item in dependencies.get(row.get("series_id", row["id"]), [])
                                          if item[1] != "completed"]})
        return result

    def list_todos_focus(self, today=None):
        """Show one actionable and the last completed occurrence per series."""
        try:
            anchor = date.fromisoformat(today) if today else date.today()
        except (TypeError, ValueError) as exc:
            raise ValueError("today must be YYYY-MM-DD") from exc
        with self._connect() as db:
            templates = [dict(row) for row in db.execute("SELECT * FROM todos ORDER BY created_at")]
            completions = {(row["todo_id"], row["occurrence_on"]): row["completed_at"]
                           for row in db.execute("SELECT * FROM todo_completions")}
            checklist_completions = {tuple(row) for row in db.execute("SELECT * FROM todo_checklist_completions")}

        result = []
        for row in templates:
            if row["repeat_frequency"] == "none":
                result.append(row)
                continue
            first = date.fromisoformat(row["due_on"])
            # Leap-day yearly series can have an eight-year gap around a
            # non-leap century (e.g. 2096 -> 2104).
            search_days = 3000 if row["repeat_frequency"] == "yearly" else 371
            latest = None
            for offset in range(search_days):
                candidate = anchor - timedelta(days=offset)
                if candidate < first:
                    break
                if self._todo_matches(row, candidate):
                    latest = candidate
                    break
            active = latest if latest and (row["id"], latest.isoformat()) not in completions else None
            if active is None:
                candidate = max(first, anchor + timedelta(days=1))
                for offset in range(search_days):
                    day = candidate + timedelta(days=offset)
                    if self._todo_matches(row, day) and (row["id"], day.isoformat()) not in completions:
                        active = day
                        break
            if active:
                result.append(self._project_todo(row, active, completions, checklist_completions))
            completed_days = [day for todo_id, day in completions if todo_id == row["id"] and
                              self._todo_matches(row, date.fromisoformat(day))]
            if completed_days:
                result.append(self._project_todo(row, date.fromisoformat(max(completed_days)), completions, checklist_completions))
        return self._decorate_rows(result)

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
            rows = db.execute("SELECT * FROM todos WHERE due_on IS NOT NULL AND due_time IS NOT NULL AND status NOT IN ('completed','cancelled')").fetchall()
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
            for row in db.execute("SELECT * FROM todos WHERE remind_at IS NOT NULL AND status NOT IN ('completed','cancelled')"):
                remind_at = datetime.fromisoformat(row["remind_at"]).astimezone(timezone.utc)
                if oldest <= remind_at <= instant:
                    cursor = db.execute("INSERT OR IGNORE INTO todo_notifications VALUES (?,?,?)",
                                        (row["id"], remind_at.isoformat(), instant.isoformat()))
                    if cursor.rowcount:
                        claimed.append(dict(row))
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
