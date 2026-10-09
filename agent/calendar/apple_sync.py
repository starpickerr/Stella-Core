"""Persistent, conservative reconciliation between EventKit and Stella schedules."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from application import Application, RequestContext
from .apple_bridge import AppleCalendarBridge


def _instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")


def _content(row):
    return {key: (_instant(row[key]) if key in ("start_at", "end_at") else bool(row[key]) if key == "all_day" else row.get(key) or "")
            for key in ("title", "description", "start_at", "end_at", "all_day", "location")}


def _fingerprint(row, *, series=False, remote=False):
    data = _content(row)
    if series:
        if remote:
            rule = row.get("recurrence") or {}
            data["repeat_frequency"] = rule.get("frequency") or "none"
            data["repeat_days"] = sorted(rule.get("days") or [])
            data["repeat_until"] = (rule.get("until") or "")[:10]
            data["repeat_interval"] = rule.get("interval", 1)
            data["repeat_count"] = rule.get("count", 0)
            data["rule_count"] = rule.get("rule_count", 0 if data["repeat_frequency"] == "none" else 1)
            for key in ("month_days", "months", "week_numbers", "year_days", "set_positions"):
                data[key] = sorted(rule.get(key) or [])
        else:
            data["repeat_frequency"] = row.get("repeat_frequency") or "none"
            days = row.get("repeat_days") or []
            data["repeat_days"] = sorted(json.loads(days) if isinstance(days, str) else days)
            data["repeat_until"] = row.get("repeat_until") or ""
            data["repeat_interval"] = 1
            data["repeat_count"] = 0
            data["rule_count"] = 0 if data["repeat_frequency"] == "none" else 1
            for key in ("month_days", "months", "week_numbers", "year_days", "set_positions"):
                data[key] = []
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _source_key(remote):
    key = "\0".join((remote["calendar_id"], remote.get("external_id") or remote["event_id"],
                      remote.get("occurrence_date") or remote["start_at"], remote["event_id"]))
    return "eventkit:" + hashlib.sha256(key.encode()).hexdigest()


def _payload(remote):
    data = _content(remote)
    data["repeat_frequency"] = "none"
    data["repeat_timezone"] = remote.get("timezone") or "UTC"
    return data


class AppleCalendarSync:
    DIRECTIONS = {"import", "export", "bidirectional"}

    def __init__(self, bridge=None, db_path=None, calendar_port=None, clock=None):
        from common.state_dir import calendar_db
        self.bridge = bridge or AppleCalendarBridge()
        self.db_path = Path(db_path) if db_path else calendar_db().with_name("apple_sync.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.calendar = calendar_port or Application.port("calendar", RequestContext.ambient("calendar_sync"))
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._lock = threading.RLock()
        self._auto_started = False
        self._stop = threading.Event()
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS baseline_local (stella_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS mappings (
                    id INTEGER PRIMARY KEY, stella_id TEXT NOT NULL UNIQUE,
                    source_key TEXT NOT NULL UNIQUE, calendar_id TEXT NOT NULL,
                    event_id TEXT NOT NULL, external_id TEXT NOT NULL,
                    occurrence_date TEXT NOT NULL, origin TEXT NOT NULL,
                    local_hash TEXT NOT NULL, remote_hash TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'active', conflict TEXT NOT NULL DEFAULT '',
                    missing_since TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS apple_map_calendar ON mappings(calendar_id);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(mappings)")}
            if "missing_since" not in columns:
                db.execute("ALTER TABLE mappings ADD COLUMN missing_since TEXT NOT NULL DEFAULT ''")

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
            return [dict(row) for row in db.execute("SELECT * FROM mappings ORDER BY id")]

    def _save_map(self, mapping):
        with self._connect() as db:
            if mapping.get("id"):
                db.execute("""UPDATE mappings SET stella_id=:stella_id,source_key=:source_key,
                    calendar_id=:calendar_id,event_id=:event_id,external_id=:external_id,
                    occurrence_date=:occurrence_date,origin=:origin,local_hash=:local_hash,
                    remote_hash=:remote_hash,state=:state,conflict=:conflict,
                    missing_since=:missing_since,updated_at=:updated_at
                    WHERE id=:id""", mapping)
            else:
                db.execute("""INSERT INTO mappings
                    (stella_id,source_key,calendar_id,event_id,external_id,occurrence_date,
                     origin,local_hash,remote_hash,state,conflict,missing_since,updated_at)
                    VALUES (:stella_id,:source_key,:calendar_id,:event_id,:external_id,:occurrence_date,
                            :origin,:local_hash,:remote_hash,:state,:conflict,:missing_since,:updated_at)""", mapping)

    def _new_map(self, local, remote, origin, source_key=None):
        series = origin == "stella"
        return {"stella_id": local["id"], "source_key": source_key or _source_key(remote),
                "calendar_id": remote["calendar_id"], "event_id": remote.get("event_id") or "",
                "external_id": remote.get("external_id") or "",
                "occurrence_date": remote.get("occurrence_date") or remote["start_at"],
                "origin": origin, "local_hash": _fingerprint(local, series=series),
                "remote_hash": _fingerprint(remote, series=series, remote=True),
                "state": "active", "conflict": "", "missing_since": "", "updated_at": self.clock()}

    def _refresh_map(self, mapping, local, remote):
        mapping.update(self._new_map(local, remote, mapping["origin"], mapping["source_key"]))
        self._save_map(mapping)

    def status(self):
        native = self.bridge.call("status")
        selected = self._get("calendar_ids", [])
        calendars = []
        if native.get("authorization") == "full_access":
            try:
                calendars = self.bridge.call("calendars")["calendars"]
            except Exception:
                pass
        maps = self._maps()
        return {**native, "connected": bool(self._get("connected", False)), "calendar_ids": selected,
                "direction": self._get("direction", "bidirectional"), "calendars": calendars,
                "last_success": self._get("last_success"), "error": self._get("error", ""),
                "conflicts": [{"stella_id": row["stella_id"], "reason": row["conflict"]}
                              for row in maps if row["state"] == "conflict"],
                "pending_deletions": sum(row["state"] == "pending_delete" for row in maps)}

    def request_access(self):
        result = self.bridge.call("request_access")
        return {**result, **self.status()}

    def configure(self, calendars, direction):
        if direction not in self.DIRECTIONS:
            raise ValueError("invalid sync direction")
        if not isinstance(calendars, list) or not calendars or len(calendars) != len(set(calendars)):
            raise ValueError("select at least one distinct calendar")
        if self.bridge.call("status").get("authorization") != "full_access":
            raise PermissionError("Calendar full access is required")
        available = {row["id"]: row for row in self.bridge.call("calendars")["calendars"]}
        if any(key not in available for key in calendars):
            raise ValueError("selected calendar is unavailable")
        if direction in ("export", "bidirectional") and not any(available[key]["writable"] for key in calendars):
            raise ValueError("select a writable calendar for export")
        with self._lock:
            if not self._get("ever_connected", False):
                with self._connect() as db:
                    db.executemany("INSERT OR IGNORE INTO baseline_local VALUES (?)",
                                   [(row["id"],) for row in self.calendar.list_events() if row["source_type"] is None])
                self._set("ever_connected", True)
            self._set("calendar_ids", calendars)
            self._set("direction", direction)
            self._set("connected", True)
        return self.status()

    def disconnect(self):
        self._set("connected", False)
        return self.status()

    def is_connected(self):
        return bool(self._get("connected", False))

    @staticmethod
    def _match(remote, maps, ambiguous=False):
        for row in maps:
            if row["calendar_id"] == remote["calendar_id"] and row["event_id"] == remote.get("event_id") and row["occurrence_date"] == remote.get("occurrence_date"):
                return row
        matches = [row for row in maps if not ambiguous and row["calendar_id"] == remote["calendar_id"] and
                   row["external_id"] and row["external_id"] == remote.get("external_id") and
                   row["occurrence_date"] == remote.get("occurrence_date")]
        return matches[0] if len(matches) == 1 else None

    def _local(self, stella_id):
        try:
            return self.calendar.get_event(stella_id)
        except KeyError:
            return None

    def _conflict(self, mapping, reason):
        mapping["state"] = "conflict"
        mapping["conflict"] = reason
        mapping["updated_at"] = self.clock()
        self._save_map(mapping)

    def _write_payload(self, local, mapping=None, calendar_id=None, window=None):
        data = _content(local)
        data.update({"calendar_id": calendar_id or mapping["calendar_id"],
                     "stella_id": local["id"] if local["source_type"] is None else "",
                     "repeat_frequency": local["repeat_frequency"],
                     "repeat_days": json.loads(local["repeat_days"]),
                     "repeat_until": local["repeat_until"],
                     "repeat_timezone": local["repeat_timezone"],
                     "series": bool(local["repeat_frequency"] != "none" and local["source_type"] is None)})
        if mapping:
            data.update(event_id=mapping["event_id"], external_id=mapping["external_id"],
                        occurrence_date=mapping["occurrence_date"])
        if window and mapping is None:
            start = datetime.fromisoformat(local["start_at"])
            if not (datetime.fromisoformat(window[0]) <= start < datetime.fromisoformat(window[1])):
                window = ((start - timedelta(days=2)).isoformat(), (start + timedelta(days=2)).isoformat())
        if window:
            data.update(scan_start=window[0], scan_end=window[1])
        return data

    def _process_remote(self, remote, maps, direction, window, counts, ambiguous=False, moved_candidate=None):
        mapping = self._match(remote, maps, ambiguous) or moved_candidate
        if moved_candidate is not None:
            mapping["calendar_id"] = remote["calendar_id"]
            mapping["event_id"] = remote["event_id"]
        if mapping is None and remote.get("stella_id"):
            existing = next((row for row in maps if row["stella_id"] == remote["stella_id"] and row["origin"] == "stella"), None)
            if existing:
                # EventKit expands a Stella-owned series into multiple instances.
                # The Stella series already renders those instances itself.
                if remote.get("is_detached"):
                    series = self._local(existing["stella_id"])
                    if direction != "export" and series and series["repeat_frequency"] != "none":
                        day = datetime.fromisoformat(remote["occurrence_date"].replace("Z", "+00:00"))
                        day = day.astimezone(ZoneInfo(series["repeat_timezone"] or "UTC")).date().isoformat()
                        self.calendar.exclude_occurrence(series["id"], day)
                        key = _source_key(remote)
                        local = self.calendar.upsert_external_event("apple_calendar", key, _payload(remote))
                        exception_map = self._new_map(local, remote, "apple", key)
                        self._save_map(exception_map)
                        maps.append(exception_map)
                        counts["imported"] += 1
                    else:
                        self._conflict(existing, "Apple changed one occurrence of a Stella series")
                        counts["conflicts"] += 1
                return
            local = self._local(remote["stella_id"])
            if local and local["source_type"] is None:
                # The native write may have succeeded immediately before an app crash.
                mapping = self._new_map(local, remote, "stella")
                self._save_map(mapping)
                maps.append(mapping)
                return
        if mapping is None:
            if direction == "export":
                return
            key = _source_key(remote)
            local = self.calendar.upsert_external_event("apple_calendar", key, _payload(remote))
            mapping = self._new_map(local, remote, "apple", key)
            self._save_map(mapping)
            maps.append(mapping)
            counts["imported"] += 1
            return
        if mapping["state"] in ("remote_deleted", "locally_deleted", "deleted"):
            return
        local = self._local(mapping["stella_id"])
        if local is None:
            mapping["state"] = "pending_delete" if direction in ("export", "bidirectional") else "locally_deleted"
            self._save_map(mapping)
            return
        series = mapping["origin"] == "stella"
        local_hash = _fingerprint(local, series=series)
        remote_hash = _fingerprint(remote, series=series, remote=True)
        local_changed = local_hash != mapping["local_hash"]
        remote_changed = remote_hash != mapping["remote_hash"]
        if mapping["state"] == "conflict":
            return
        if local_changed and remote_changed:
            self._conflict(mapping, "Both Stella and Apple changed this event")
            counts["conflicts"] += 1
        elif remote_changed:
            if direction == "export":
                self._conflict(mapping, "Apple changed an export-only event")
                counts["conflicts"] += 1
            elif mapping["origin"] == "apple":
                local = self.calendar.upsert_external_event("apple_calendar", mapping["source_key"], _payload(remote),
                                                            event_id=local["id"], reconciled=True)
                self._refresh_map(mapping, local, remote)
                counts["updated"] += 1
            else:
                self._conflict(mapping, "Apple changed a Stella recurring series") if local["repeat_frequency"] != "none" else None
                if local["repeat_frequency"] != "none":
                    counts["conflicts"] += 1
                else:
                    local = self.calendar.update_event(local["id"], _payload(remote))
                    self._refresh_map(mapping, local, remote)
                    counts["updated"] += 1
        elif local_changed:
            if direction == "import":
                self._conflict(mapping, "Stella changed an import-only event")
                counts["conflicts"] += 1
            elif not remote.get("writable", False):
                self._conflict(mapping, "Apple calendar is read only")
                counts["conflicts"] += 1
            else:
                changed = self.bridge.call("upsert", **self._write_payload(local, mapping, window=window))["event"]
                self._refresh_map(mapping, local, changed)
                counts["exported"] += 1
        else:
            mapping["calendar_id"] = remote["calendar_id"]
            mapping["event_id"] = remote.get("event_id") or mapping["event_id"]
            mapping["missing_since"] = ""
            mapping["updated_at"] = self.clock()
            self._save_map(mapping)

    def sync(self, manual=False, confirm_deletions=False):
        with self._lock:
            counts = {"status": "success", "imported": 0, "updated": 0, "exported": 0,
                      "deleted_local": 0, "deleted_remote": 0, "conflicts": 0,
                      "pending_deletions": 0, "failed_calendar_ids": []}
            if not self._get("connected", False):
                counts["status"] = "disconnected"
                return counts
            native = self.bridge.call("status")
            if native.get("authorization") != "full_access":
                counts["status"] = native.get("authorization", "unavailable")
                return counts
            direction = self._get("direction", "bidirectional")
            selected = self._get("calendar_ids", [])
            now = datetime.fromisoformat(self.clock().replace("Z", "+00:00"))
            window = ((now - timedelta(days=365)).isoformat(), (now + timedelta(days=730)).isoformat())
            try:
                inventory = self.bridge.call("events", calendar_ids=selected, start=window[0], end=window[1])
                successful = set(inventory["successful_calendar_ids"]) & set(selected)
                counts["failed_calendar_ids"] = sorted(set(selected) - successful)
                if counts["failed_calendar_ids"]:
                    with self._connect() as db:
                        db.executemany("UPDATE mappings SET missing_since='' WHERE calendar_id=?",
                                       [(key,) for key in counts["failed_calendar_ids"]])
                maps = self._maps()
                seen = set()
                identity_counts = {}
                cross_counts = {}
                inventory_keys = set()
                for row in inventory["events"]:
                    identity = (row["calendar_id"], row.get("external_id"), row.get("occurrence_date"))
                    identity_counts[identity] = identity_counts.get(identity, 0) + 1
                    cross = (row.get("external_id"), row.get("occurrence_date"))
                    cross_counts[cross] = cross_counts.get(cross, 0) + 1
                    inventory_keys.add((row["calendar_id"], row.get("event_id"), row.get("occurrence_date")))
                for remote in inventory["events"]:
                    if remote["calendar_id"] not in successful:
                        continue
                    try:
                        identity = (remote["calendar_id"], remote.get("external_id"), remote.get("occurrence_date"))
                        ambiguous = identity_counts[identity] > 1
                        moved = None
                        cross = (remote.get("external_id"), remote.get("occurrence_date"))
                        if remote.get("external_id") and cross_counts[cross] == 1 and not self._match(remote, maps, ambiguous):
                            candidates = [row for row in maps if row["calendar_id"] != remote["calendar_id"] and
                                row["calendar_id"] in successful and row["external_id"] == remote["external_id"] and
                                row["occurrence_date"] == remote["occurrence_date"] and
                                (row["calendar_id"], row["event_id"], row["occurrence_date"]) not in inventory_keys]
                            if len(candidates) == 1:
                                moved = candidates[0]
                        self._process_remote(remote, maps, direction, window, counts, ambiguous, moved)
                        found = self._match(remote, maps, ambiguous)
                        if found:
                            seen.add(found["stella_id"])
                    except Exception:
                        counts["status"] = "error"
                maps = self._maps()
                for mapping in maps:
                    if mapping["calendar_id"] not in successful or mapping["stella_id"] in seen:
                        continue
                    if mapping["state"] in ("deleted", "remote_deleted", "locally_deleted", "conflict"):
                        continue
                    try:
                        found = self.bridge.call("lookup", **{key: mapping[key] for key in
                            ("calendar_id", "event_id", "external_id", "occurrence_date")},
                            scan_start=window[0], scan_end=window[1]).get("event")
                        if found:
                            self._process_remote(found, maps, direction, window, counts)
                            continue
                        if not mapping["missing_since"]:
                            mapping["missing_since"] = self.clock()
                            self._save_map(mapping)
                            continue
                        first_missing = datetime.fromisoformat(mapping["missing_since"].replace("Z", "+00:00"))
                        if now - first_missing < timedelta(minutes=1):
                            continue
                        local = self._local(mapping["stella_id"])
                        if local is None:
                            mapping["state"] = "deleted"
                        elif mapping["origin"] == "apple" and direction in ("import", "bidirectional") and _fingerprint(local) == mapping["local_hash"]:
                            self.calendar.delete_event(local["id"])
                            mapping["state"] = "remote_deleted"
                            counts["deleted_local"] += 1
                        else:
                            self._conflict(mapping, "Apple event was removed or moved outside the scan window")
                            counts["conflicts"] += 1
                            continue
                        self._save_map(mapping)
                    except Exception:
                        counts["status"] = "error"
                if direction in ("export", "bidirectional") and successful:
                    calendars = {row["id"]: row for row in self.bridge.call("calendars")["calendars"]}
                    targets = [key for key in selected if key in successful and calendars.get(key, {}).get("writable")]
                    if targets:
                        with self._connect() as db:
                            baseline = {row[0] for row in db.execute("SELECT stella_id FROM baseline_local")}
                        mapped = {row["stella_id"] for row in self._maps()}
                        for local in self.calendar.list_events():
                            if local["source_type"] is not None or local["id"] in mapped or local["id"] in baseline:
                                continue
                            try:
                                remote = self.bridge.call("upsert", **self._write_payload(local, calendar_id=targets[0], window=window))["event"]
                                self._save_map(self._new_map(local, remote, "stella"))
                                counts["exported"] += 1
                            except Exception:
                                counts["status"] = "error"
                for mapping in self._maps():
                    if mapping["state"] != "pending_delete" or mapping["calendar_id"] not in successful:
                        continue
                    counts["pending_deletions"] += 1
                    if manual and confirm_deletions:
                        try:
                            self.bridge.call("delete", calendar_id=mapping["calendar_id"], event_id=mapping["event_id"],
                                             external_id=mapping["external_id"], occurrence_date=mapping["occurrence_date"],
                                             series=mapping["origin"] == "stella", scan_start=window[0], scan_end=window[1])
                            mapping["state"] = "deleted"
                            self._save_map(mapping)
                            counts["deleted_remote"] += 1
                            counts["pending_deletions"] -= 1
                        except Exception:
                            counts["status"] = "error"
                if counts["failed_calendar_ids"]:
                    counts["status"] = "partial" if counts["status"] == "success" else counts["status"]
                if counts["status"] == "success":
                    self._set("last_success", self.clock())
                    self._set("error", "")
                else:
                    self._set("error", "Calendar sync needs another attempt" if counts["status"] == "error" else "Some calendars are unavailable")
            except Exception:
                counts["status"] = "error"
                self._set("error", "Calendar sync needs another attempt")
            return counts

    def resolve_conflict(self, stella_id, choice):
        if choice not in ("keep_stella", "keep_apple"):
            raise ValueError("invalid conflict resolution")
        mapping = next((row for row in self._maps() if row["stella_id"] == stella_id), None)
        if not mapping or mapping["state"] != "conflict":
            raise KeyError("conflict not found")
        local = self._local(stella_id)
        if local is None:
            raise KeyError("Stella event not found")
        if choice == "keep_apple" and mapping["origin"] == "stella" and local["repeat_frequency"] != "none":
            raise ValueError("Apple changes to a recurring series need manual review")
        remote = self.bridge.call("lookup", **{key: mapping[key] for key in
            ("calendar_id", "event_id", "external_id", "occurrence_date")}).get("event")
        if choice == "keep_stella":
            if remote is None:
                raise ValueError("Apple event is unavailable")
            remote = self.bridge.call("upsert", **self._write_payload(local, mapping))["event"]
        else:
            if remote is None:
                raise ValueError("Apple event is unavailable")
            if mapping["origin"] == "apple":
                local = self.calendar.upsert_external_event("apple_calendar", mapping["source_key"], _payload(remote),
                                                            event_id=local["id"], reconciled=True)
            else:
                local = self.calendar.update_event(local["id"], _payload(remote))
        self._refresh_map(mapping, local, remote)
        return self.status()

    def start_auto(self, interval=300):
        """Retry periodically and reconcile promptly after EventKit notifications."""
        if self._auto_started:
            return
        self._auto_started = True

        def poll():
            while not self._stop.is_set():
                if self._get("connected", False):
                    self.sync()
                self._stop.wait(interval)

        def watch():
            while not self._stop.is_set():
                if self._get("connected", False):
                    try:
                        self.bridge.watch(lambda: self.sync(), self._stop)
                    except Exception:
                        pass
                self._stop.wait(interval)

        threading.Thread(target=poll, name="apple-calendar-poll", daemon=True).start()
        threading.Thread(target=watch, name="apple-calendar-watch", daemon=True).start()
