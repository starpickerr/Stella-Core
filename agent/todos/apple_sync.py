"""Conservative, persistent reconciliation of Apple Reminders and Stella todos."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.calendar.apple_bridge import AppleCalendarBridge
from application import Application, RequestContext


def _instant(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(
        timespec="seconds")


def _priority(value, *, remote=False):
    if remote:
        return 3 if value in (1, 2, 3, 4) else 2 if value in (5, 6) else 1 if value in (7, 8, 9) else 0
    return {0: 0, 1: 9, 2: 5, 3: 1}.get(value, 0)


def _payload(remote):
    rule = remote.get("recurrence") or {}
    return {"title": remote["title"], "notes": remote.get("notes") or "",
            "due_on": remote.get("due_on"), "due_time": remote.get("due_time"),
            "timezone": remote.get("timezone") or "UTC", "planned_on": remote.get("planned_on"),
            "remind_at": remote.get("remind_at"), "priority": _priority(remote.get("priority"), remote=True),
            "repeat_frequency": rule.get("frequency") or "none", "repeat_days": rule.get("days") or [],
            "repeat_until": (rule.get("until") or "")[:10] or None,
            "completed": bool(remote.get("completed")), "completed_at": remote.get("completed_at")}


def _compatible(row, *, remote=False):
    data = _payload(row) if remote else row
    days = data.get("repeat_days") or []
    if isinstance(days, str):
        days = json.loads(days)
    return {"title": data.get("title") or "", "notes": data.get("notes") or "",
            "due_on": data.get("due_on") or "", "due_time": data.get("due_time") or "",
            "timezone": data.get("timezone") or "UTC", "planned_on": data.get("planned_on") or "",
            "remind_at": _instant(data.get("remind_at")) or "", "priority": data.get("priority") or 0,
            "repeat_frequency": data.get("repeat_frequency") or "none", "repeat_days": sorted(days),
            "repeat_until": data.get("repeat_until") or "",
            "completed": bool(data.get("completed")) if remote else data.get("status") == "completed",
            "completed_at": _instant(data.get("completed_at")) or ""}


def _hash(row, *, remote=False):
    return hashlib.sha256(json.dumps(_compatible(row, remote=remote), sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def _source_key(remote):
    identity = remote.get("external_id") or "\0".join((remote["list_id"], remote["reminder_id"]))
    return "eventkit:" + hashlib.sha256(identity.encode()).hexdigest()


def _supported(remote):
    rule = remote.get("recurrence") or {}
    return (remote.get("alarm_count", 0) <= 1 and rule.get("rule_count", 0) <= 1 and
            rule.get("frequency", "none") in ("none", "daily", "weekly", "monthly", "yearly") and
            rule.get("interval", 1) == 1 and not rule.get("count") and
            (rule.get("frequency") == "weekly" or not rule.get("days")) and
            not any(rule.get(key) for key in ("month_days", "months", "week_numbers",
                                              "year_days", "set_positions")))


class AppleReminderSync:
    DIRECTIONS = {"import", "export", "bidirectional"}

    def __init__(self, bridge=None, db_path=None, todo_port=None, clock=None):
        from common.state_dir import todos_db
        self.bridge = bridge or AppleCalendarBridge()
        self.db_path = Path(db_path) if db_path else todos_db().with_name("apple_reminders.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.todos = todo_port or Application.port("todos", RequestContext.ambient("apple_reminder_sync"))
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._lock = threading.RLock()
        self._auto_started = False
        with self._connect() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS baseline_local (todo_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS mappings (
                    todo_id TEXT PRIMARY KEY,source_key TEXT NOT NULL UNIQUE,
                    list_id TEXT NOT NULL,reminder_id TEXT NOT NULL,external_id TEXT NOT NULL,
                    origin TEXT NOT NULL,local_hash TEXT NOT NULL,remote_hash TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'active',conflict TEXT NOT NULL DEFAULT '',
                    missing_since TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS reminder_map_list ON mappings(list_id);""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _get(self, key, default=None):
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def _set(self, key, value):
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def _maps(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM mappings")]

    def _save_map(self, mapping):
        with self._connect() as db:
            db.execute("""INSERT INTO mappings VALUES
                (:todo_id,:source_key,:list_id,:reminder_id,:external_id,:origin,:local_hash,
                 :remote_hash,:state,:conflict,:missing_since,:updated_at)
                ON CONFLICT(todo_id) DO UPDATE SET
                source_key=excluded.source_key,list_id=excluded.list_id,reminder_id=excluded.reminder_id,
                external_id=excluded.external_id,origin=excluded.origin,local_hash=excluded.local_hash,
                remote_hash=excluded.remote_hash,state=excluded.state,conflict=excluded.conflict,
                missing_since=excluded.missing_since,updated_at=excluded.updated_at""", mapping)

    def _new_map(self, local, remote, origin, source_key=None):
        return {"todo_id": local["id"], "source_key": source_key or _source_key(remote),
                "list_id": remote["list_id"], "reminder_id": remote["reminder_id"],
                "external_id": remote.get("external_id") or "", "origin": origin,
                "local_hash": _hash(local), "remote_hash": _hash(remote, remote=True),
                "state": "active", "conflict": "", "missing_since": "", "updated_at": self.clock()}

    def _refresh_map(self, mapping, local, remote):
        self._save_map(self._new_map(local, remote, mapping["origin"], mapping["source_key"]))

    def _local(self, todo_id):
        try:
            return self.todos.get_todo(todo_id)
        except KeyError:
            return None

    def _conflict(self, mapping, reason):
        mapping.update(state="conflict", conflict=reason, updated_at=self.clock())
        self._save_map(mapping)

    def status(self):
        native = self.bridge.call("reminder_status")
        lists = []
        if native.get("authorization") == "full_access":
            try:
                lists = self.bridge.call("reminder_lists")["lists"]
            except Exception:
                pass
        maps = self._maps()
        return {**native, "connected": bool(self._get("connected", False)),
                "list_ids": self._get("list_ids", []), "direction": self._get("direction", "bidirectional"),
                "lists": lists, "last_success": self._get("last_success"), "error": self._get("error", ""),
                "conflicts": [{"todo_id": row["todo_id"], "reason": row["conflict"]}
                              for row in maps if row["state"] == "conflict"],
                "pending_deletions": sum(row["state"] == "pending_delete" for row in maps),
                "pending_local_deletions": sum(row["state"] == "pending_local_delete" for row in maps)}

    def request_access(self):
        result = self.bridge.call("reminder_request_access")
        return {**result, **self.status()}

    def _validate_selection(self, list_ids, direction):
        if direction not in self.DIRECTIONS:
            raise ValueError("invalid sync direction")
        if not isinstance(list_ids, list) or not list_ids or len(set(list_ids)) != len(list_ids):
            raise ValueError("select at least one distinct reminder list")
        if self.bridge.call("reminder_status").get("authorization") != "full_access":
            raise PermissionError("Reminders full access is required")
        available = {row["id"]: row for row in self.bridge.call("reminder_lists")["lists"]}
        if any(key not in available for key in list_ids):
            raise ValueError("selected reminder list is unavailable")
        if direction in ("export", "bidirectional") and not any(available[key]["writable"] for key in list_ids):
            raise ValueError("select a writable reminder list for export")
        return available

    def configure(self, list_ids, direction):
        self._validate_selection(list_ids, direction)
        with self._lock:
            if not self._get("ever_connected", False):
                with self._connect() as db:
                    db.executemany("INSERT OR IGNORE INTO baseline_local VALUES (?)",
                                   [(row["id"],) for row in self.todos.list_todos() if row["source_type"] is None])
                self._set("ever_connected", True)
            self._set("list_ids", list_ids)
            self._set("direction", direction)
            self._set("connected", True)
        return self.status()

    def disconnect(self):
        self._set("connected", False)
        return self.status()

    @staticmethod
    def _match(remote, maps, inventory):
        direct = [row for row in maps if row["list_id"] == remote["list_id"] and
                  row["reminder_id"] == remote["reminder_id"]]
        if len(direct) == 1:
            return direct[0]
        if remote.get("stella_id"):
            marked = [row for row in maps if row["todo_id"] == remote["stella_id"]]
            if len(marked) == 1:
                return marked[0]
        external = remote.get("external_id")
        if external and sum(item.get("external_id") == external for item in inventory) == 1:
            matches = [row for row in maps if row["external_id"] == external]
            if len(matches) == 1:
                return matches[0]
        return None

    def _write_payload(self, local, mapping=None, list_id=None):
        data = {"list_id": list_id or mapping["list_id"], "title": local["title"],
                "notes": local["notes"], "due_on": local["due_on"], "due_time": local["due_time"],
                "timezone": local["timezone"], "planned_on": local["planned_on"],
                "remind_at": local["remind_at"], "priority": _priority(local["priority"]),
                "completed": local["status"] == "completed", "completed_at": local["completed_at"],
                "repeat_frequency": local["repeat_frequency"],
                "repeat_days": json.loads(local["repeat_days"]), "repeat_until": local["repeat_until"]}
        if mapping:
            data.update(reminder_id=mapping["reminder_id"], external_id=mapping["external_id"])
        else:
            data["stella_id"] = local["id"]
        return data

    def _apply_remote(self, mapping, local, remote):
        payload = _payload(remote)
        if mapping["origin"] == "apple":
            return self.todos.upsert_external_todo(mapping["source_key"], payload,
                                                   todo_id=local["id"], reconciled=True)
        fields = {key: value for key, value in payload.items() if key not in ("completed", "completed_at")}
        updated = self.todos.update_todo(local["id"], fields)
        if updated["repeat_frequency"] == "none" and updated["status"] != "cancelled":
            wanted = "completed" if payload["completed"] else "todo" if updated["status"] == "completed" else updated["status"]
            if wanted != updated["status"]:
                updated = self.todos.change_todo_status(local["id"], wanted)
        return updated

    def _process_remote(self, remote, mapping, direction, counts):
        if not _supported(remote):
            self._conflict(mapping, "Apple reminder has unsupported alarms or recurrence")
            counts["conflicts"] += 1
            return
        local = self._local(mapping["todo_id"])
        if local is None:
            mapping.update(state="pending_delete", updated_at=self.clock())
            self._save_map(mapping)
            return
        local_changed = _hash(local) != mapping["local_hash"]
        remote_changed = _hash(remote, remote=True) != mapping["remote_hash"]
        if local_changed and remote_changed:
            self._conflict(mapping, "Both Stella and Apple changed this reminder")
            counts["conflicts"] += 1
            return
        if remote_changed:
            if direction not in ("import", "bidirectional"):
                self._conflict(mapping, "Apple changed an export-only reminder")
                counts["conflicts"] += 1
                return
            local = self._apply_remote(mapping, local, remote)
            counts["updated"] += 1
        elif local_changed:
            if direction not in ("export", "bidirectional") or not remote.get("writable", False):
                self._conflict(mapping, "Stella changed a reminder that cannot be exported")
                counts["conflicts"] += 1
                return
            remote = self.bridge.call("reminder_upsert", **self._write_payload(local, mapping))["reminder"]
            counts["exported"] += 1
        self._refresh_map(mapping, local, remote)

    def preview(self, list_ids, direction):
        self._validate_selection(list_ids, direction)
        inventory = self.bridge.call("reminders", list_ids=list_ids)
        successful = set(inventory["successful_list_ids"])
        maps = self._maps()
        external_counts = {key: sum(row.get("external_id") == key for row in inventory["reminders"])
                           for key in {row.get("external_id") for row in inventory["reminders"] if row.get("external_id")}}
        result = {"new": 0, "updated": 0, "skipped": 0, "conflicts": 0,
                  "failed_list_ids": sorted(set(list_ids) - successful)}
        for row in inventory["reminders"]:
            if row["list_id"] not in successful:
                continue
            mapping = self._match(row, maps, inventory["reminders"])
            if (not _supported(row) or row.get("external_id") and
                    external_counts[row["external_id"]] > 1):
                result["conflicts"] += 1
            elif mapping is None:
                result["new" if direction in ("import", "bidirectional") else "skipped"] += 1
            else:
                local = self._local(mapping["todo_id"])
                if local is None:
                    result["conflicts"] += 1
                    continue
                local_changed = _hash(local) != mapping["local_hash"]
                remote_changed = _hash(row, remote=True) != mapping["remote_hash"]
                if (local_changed and remote_changed or
                        remote_changed and direction == "export" or
                        local_changed and direction == "import"):
                    result["conflicts"] += 1
                elif local_changed or remote_changed:
                    result["updated"] += 1
                else:
                    result["skipped"] += 1
        if direction in ("export", "bidirectional"):
            with self._connect() as db:
                baseline = {row[0] for row in db.execute("SELECT todo_id FROM baseline_local")}
            mapped = {row["todo_id"] for row in maps}
            result["new"] += sum(local["source_type"] is None and local["id"] not in mapped and
                                 local["id"] not in baseline and local["status"] != "cancelled"
                                 for local in self.todos.list_todos())
        return result

    def sync(self, manual=False, confirm_deletions=False, confirm_local_deletions=False):
        with self._lock:
            counts = {"status": "success", "imported": 0, "updated": 0, "exported": 0,
                      "deleted_local": 0, "deleted_remote": 0, "conflicts": 0,
                      "pending_deletions": 0, "pending_local_deletions": 0, "failed_list_ids": []}
            if not self._get("connected", False):
                counts["status"] = "disconnected"
                return counts
            if self.bridge.call("reminder_status").get("authorization") != "full_access":
                counts["status"] = "permission_required"
                return counts
            selected = self._get("list_ids", [])
            direction = self._get("direction", "bidirectional")
            try:
                inventory = self.bridge.call("reminders", list_ids=selected)
                successful = set(inventory["successful_list_ids"]) & set(selected)
                counts["failed_list_ids"] = sorted(set(selected) - successful)
                maps = self._maps()
                rows = [row for row in inventory["reminders"] if row["list_id"] in successful]
                external_counts = {key: sum(row.get("external_id") == key for row in rows)
                                   for key in {row.get("external_id") for row in rows if row.get("external_id")}}
                empty_unsafe = {key for key in successful if not any(row["list_id"] == key for row in rows) and
                                any(mapping["list_id"] == key and mapping["state"] == "active" and
                                    mapping["origin"] == "apple" for mapping in maps)}
                if counts["failed_list_ids"] or empty_unsafe:
                    counts["status"] = "partial"
                seen = set()
                for remote in rows:
                    try:
                        if (not _supported(remote) or remote.get("external_id") and
                                external_counts[remote["external_id"]] > 1):
                            mapping = self._match(remote, maps, rows)
                            if mapping:
                                self._conflict(mapping, "Apple reminder identity or recurrence is ambiguous")
                                seen.add(mapping["todo_id"])
                            counts["conflicts"] += 1
                            continue
                        mapping = self._match(remote, maps, rows)
                        if mapping:
                            seen.add(mapping["todo_id"])
                            self._process_remote(remote, mapping, direction, counts)
                        elif direction in ("import", "bidirectional") and _supported(remote):
                            key = _source_key(remote)
                            local = self.todos.upsert_external_todo(key, _payload(remote))
                            mapping = self._new_map(local, remote, "apple", key)
                            self._save_map(mapping)
                            maps.append(mapping)
                            seen.add(local["id"])
                            counts["imported"] += 1
                    except Exception:
                        counts["status"] = "error"
                now = datetime.fromisoformat(self.clock().replace("Z", "+00:00"))
                for mapping in self._maps():
                    if (mapping["list_id"] not in successful or mapping["list_id"] in empty_unsafe or
                            mapping["todo_id"] in seen or mapping["state"] in
                            ("deleted", "remote_deleted", "conflict")):
                        continue
                    try:
                        found = self.bridge.call("reminder_lookup", list_id=mapping["list_id"],
                            reminder_id=mapping["reminder_id"], external_id=mapping["external_id"]).get("reminder")
                        if found:
                            self._process_remote(found, mapping, direction, counts)
                            continue
                        local = self._local(mapping["todo_id"])
                        if local is None:
                            mapping["state"] = "pending_delete"
                        elif not mapping["missing_since"]:
                            mapping["missing_since"] = self.clock()
                        elif now - datetime.fromisoformat(mapping["missing_since"].replace("Z", "+00:00")) >= timedelta(minutes=1):
                            if mapping["origin"] == "apple" and _hash(local) == mapping["local_hash"]:
                                mapping["state"] = "pending_local_delete"
                            else:
                                self._conflict(mapping, "Apple reminder is missing or moved")
                                counts["conflicts"] += 1
                                continue
                        mapping["updated_at"] = self.clock()
                        self._save_map(mapping)
                    except Exception:
                        counts["status"] = "error"
                if direction in ("export", "bidirectional") and successful:
                    available = {row["id"]: row for row in self.bridge.call("reminder_lists")["lists"]}
                    targets = [key for key in selected if key in successful and available.get(key, {}).get("writable")]
                    if targets:
                        with self._connect() as db:
                            baseline = {row[0] for row in db.execute("SELECT todo_id FROM baseline_local")}
                        mapped = {row["todo_id"] for row in self._maps()}
                        for local in self.todos.list_todos():
                            if (local["source_type"] is not None or local["id"] in mapped or
                                    local["id"] in baseline or local["status"] == "cancelled"):
                                continue
                            try:
                                remote = self.bridge.call("reminder_upsert", **self._write_payload(
                                    local, list_id=targets[0]))["reminder"]
                                self._save_map(self._new_map(local, remote, "stella"))
                                counts["exported"] += 1
                            except Exception:
                                counts["status"] = "error"
                for mapping in self._maps():
                    if mapping["state"] == "pending_local_delete":
                        counts["pending_local_deletions"] += 1
                        if manual and confirm_local_deletions:
                            try:
                                self.todos.delete_external_todo(mapping["source_key"], confirm=True)
                                mapping["state"] = "remote_deleted"
                                self._save_map(mapping)
                                counts["deleted_local"] += 1
                                counts["pending_local_deletions"] -= 1
                            except Exception:
                                counts["status"] = "error"
                    elif mapping["state"] == "pending_delete":
                        counts["pending_deletions"] += 1
                        if manual and confirm_deletions:
                            try:
                                self.bridge.call("reminder_delete", list_id=mapping["list_id"],
                                                 reminder_id=mapping["reminder_id"],
                                                 external_id=mapping["external_id"])
                                mapping["state"] = "deleted"
                                self._save_map(mapping)
                                counts["deleted_remote"] += 1
                                counts["pending_deletions"] -= 1
                            except Exception:
                                counts["status"] = "error"
                if counts["status"] == "success":
                    self._set("last_success", self.clock())
                    self._set("error", "")
                else:
                    self._set("error", "Reminders sync needs review or another attempt")
            except Exception:
                counts["status"] = "error"
                self._set("error", "Reminders sync needs another attempt")
            return counts

    def resolve_conflict(self, todo_id, choice):
        if choice not in ("keep_stella", "keep_apple"):
            raise ValueError("invalid conflict resolution")
        mapping = next((row for row in self._maps() if row["todo_id"] == todo_id), None)
        if not mapping or mapping["state"] != "conflict":
            raise KeyError("conflict not found")
        local = self._local(todo_id)
        if local is None:
            raise KeyError("Stella todo not found")
        remote = self.bridge.call("reminder_lookup", list_id=mapping["list_id"],
            reminder_id=mapping["reminder_id"], external_id=mapping["external_id"]).get("reminder")
        if remote is None:
            raise ValueError("Apple reminder is unavailable")
        if choice == "keep_stella":
            remote = self.bridge.call("reminder_upsert", **self._write_payload(local, mapping))["reminder"]
        else:
            if not _supported(remote):
                raise ValueError("Apple reminder has unsupported fields")
            local = self._apply_remote(mapping, local, remote)
        self._refresh_map(mapping, local, remote)
        return self.status()

    def start_auto(self, interval=300):
        if self._auto_started:
            return
        self._auto_started = True
        from agent.calendar.apple_runtime import EventKitAutoRunner
        self._runner = EventKitAutoRunner(self.bridge, lambda: self._get("connected", False),
                                          self.sync, kind="reminder", interval=interval)
        self._runner.start()

    def stop_auto(self):
        if self._auto_started:
            self._runner.stop()
        self._auto_started = False
