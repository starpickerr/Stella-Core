"""Apple Reminders reconciliation against an isolated EventKit adapter."""

import copy
import threading
from datetime import datetime, timedelta, timezone

import pytest

from agent.scheduler.store import TaskStore
from agent.todos import TodoService
from agent.todos.apple_sync import AppleReminderSync


def reminder(identifier="r1", list_id="a", title="Homework", **updates):
    row = dict(list_id=list_id, reminder_id=identifier, external_id="external-" + identifier,
               stella_id="", title=title, notes="Apple note", due_on="2026-10-10",
               due_time="14:00", timezone="Asia/Shanghai", planned_on="2026-10-09",
               remind_at=None, alarm_count=0, priority=5, completed=False, completed_at=None,
               recurrence={"frequency": "none", "days": [], "until": None, "rule_count": 0},
               last_modified="2026-10-09T00:00:00Z", writable=True)
    row.update(updates)
    return row


class FakeBridge:
    def __init__(self, rows=()):
        self.rows = [copy.deepcopy(row) for row in rows]
        self.authorization = "full_access"
        self.available = {"a", "b"}
        self.failed = set()
        self.writes = []
        self.deletes = []
        self.fail_next_scan = False

    def call(self, op, **payload):
        if op == "reminder_status":
            return {"supported": True, "authorization": self.authorization}
        if op == "reminder_request_access":
            return {"authorization": self.authorization, "granted": self.authorization == "full_access"}
        if self.authorization != "full_access":
            raise PermissionError("Reminders full access is required")
        if op == "reminder_lists":
            return {"lists": [dict(id=key, title=key, source="iCloud", writable=True)
                              for key in sorted(self.available)]}
        if op == "reminders":
            if self.fail_next_scan:
                self.fail_next_scan = False
                raise RuntimeError("EventKit scan interrupted")
            good = set(payload["list_ids"]) & self.available - self.failed
            return {"reminders": copy.deepcopy([row for row in self.rows if row["list_id"] in good]),
                    "successful_list_ids": sorted(good),
                    "failed_list_ids": sorted(set(payload["list_ids"]) - good)}
        if op == "reminder_lookup":
            matches = [row for row in self.rows if row["list_id"] == payload["list_id"] and
                       (row["reminder_id"] == payload.get("reminder_id") or
                        row["external_id"] == payload.get("external_id") or
                        row["stella_id"] and row["stella_id"] == payload.get("stella_id"))]
            return {"reminder": copy.deepcopy(matches[0]) if len(matches) == 1 else None}
        if op == "reminder_upsert":
            self.writes.append(copy.deepcopy(payload))
            found = next((row for row in self.rows if row["list_id"] == payload["list_id"] and
                          row["reminder_id"] == payload.get("reminder_id")), None)
            if found is None:
                found = reminder("new-" + str(len(self.writes)), payload["list_id"],
                                 external_id="new-ext-" + str(len(self.writes)))
                self.rows.append(found)
            found.update({key: value for key, value in payload.items() if key in found and key not in
                          ("reminder_id", "external_id")})
            return {"reminder": copy.deepcopy(found)}
        if op == "reminder_delete":
            self.deletes.append(copy.deepcopy(payload))
            self.rows = [row for row in self.rows if not (row["list_id"] == payload["list_id"] and
                         row["reminder_id"] == payload["reminder_id"])]
            return {"deleted": True}
        raise AssertionError(op)


def manager(tmp_path, rows=()):
    todos = TodoService(tmp_path / "todos.db", tmp_path / "calendar.db",
                        scheduler_store=TaskStore(str(tmp_path / "scheduler" / "tasks.json")))
    bridge = FakeBridge(rows)
    current = [datetime(2026, 10, 9, tzinfo=timezone.utc)]
    sync = AppleReminderSync(bridge=bridge, db_path=tmp_path / "apple_reminders.db", todo_port=todos,
                             clock=lambda: current[0].isoformat())
    return sync, todos, bridge, current


def test_permission_list_selection_import_idempotency_and_restart(tmp_path):
    sync, todos, bridge, _ = manager(tmp_path, [reminder()])
    bridge.authorization = "denied"
    with pytest.raises(PermissionError):
        sync.configure(["a"], "bidirectional")
    bridge.authorization = "full_access"
    sync.configure(["a"], "import")
    assert sync.status()["list_ids"] == ["a"]
    assert sync.sync()["imported"] == 1
    item = todos.list_todos()[0]
    assert item["source_type"] == "apple_reminder" and item["priority"] == 2
    assert sync.sync()["imported"] == 0 and len(todos.list_todos()) == 1
    reopened = AppleReminderSync(bridge=bridge, db_path=tmp_path / "apple_reminders.db", todo_port=todos)
    assert reopened.sync()["imported"] == 0 and len(todos.list_todos()) == 1


def test_remote_update_preserves_advanced_status_and_list_move_identity(tmp_path):
    sync, todos, bridge, _ = manager(tmp_path, [reminder()])
    sync.configure(["a", "b"], "bidirectional")
    sync.sync()
    item = todos.list_todos()[0]
    todos.change_todo_status(item["id"], "waiting")
    bridge.rows[0].update(title="New title", list_id="b", reminder_id="new-id")
    result = sync.sync()
    changed = todos.get_todo(item["id"])
    assert result["updated"] == 1 and len(todos.list_todos()) == 1
    assert changed["title"] == "New title" and changed["status"] == "waiting"
    bridge.rows[0]["completed"] = True
    assert sync.sync()["updated"] == 1
    assert todos.get_todo(item["id"])["status"] == "completed"
    bridge.rows[0]["completed"] = False
    assert sync.sync()["updated"] == 1
    assert todos.get_todo(item["id"])["status"] == "todo"


def test_new_local_export_and_both_sides_edit_conflict(tmp_path):
    sync, todos, bridge, _ = manager(tmp_path, [reminder()])
    baseline = todos.create_todo({"title": "Pre-existing"})
    sync.configure(["a"], "bidirectional")
    sync.sync()
    local = todos.create_todo({"title": "New Stella task", "due_on": "2026-10-11", "priority": 3})
    assert sync.sync()["exported"] == 1
    assert bridge.writes[-1]["stella_id"] == local["id"]
    assert all(row.get("stella_id") != baseline["id"] for row in bridge.rows)
    imported = next(row for row in todos.list_todos() if row["source_type"] == "apple_reminder")
    todos.update_todo(imported["id"], {"title": "Local correction"})
    bridge.rows[0]["title"] = "Remote correction"
    result = sync.sync()
    assert result["conflicts"] == 1
    assert todos.get_todo(imported["id"])["title"] == "Local correction"
    assert sync.status()["conflicts"][0]["todo_id"] == imported["id"]


def test_partial_and_empty_scans_preserve_local_data_and_confirmed_delete(tmp_path):
    sync, todos, bridge, current = manager(tmp_path, [reminder(), reminder("r2")])
    sync.configure(["a"], "import")
    sync.sync()
    assert len(todos.list_todos()) == 2
    bridge.failed.add("a")
    assert sync.sync()["status"] == "partial" and len(todos.list_todos()) == 2
    bridge.failed.clear()
    bridge.rows.clear()
    assert sync.sync()["status"] == "partial" and len(todos.list_todos()) == 2
    bridge.rows.append(reminder("r2"))
    first = sync.sync()
    assert first["deleted_local"] == 0 and len(todos.list_todos()) == 2
    current[0] += timedelta(minutes=2)
    second = sync.sync()
    assert second["pending_local_deletions"] == 1 and len(todos.list_todos()) == 2
    confirmed = sync.sync(manual=True, confirm_local_deletions=True)
    assert confirmed["deleted_local"] == 1 and len(todos.list_todos()) == 1


def test_failed_scan_cannot_confirm_a_previously_staged_local_deletion(tmp_path):
    sync, todos, bridge, current = manager(tmp_path, [reminder(), reminder("r2")])
    sync.configure(["a"], "import")
    sync.sync()
    bridge.rows = [reminder("r2")]
    sync.sync()
    current[0] += timedelta(minutes=2)
    assert sync.sync()["pending_local_deletions"] == 1
    bridge.failed.add("a")
    result = sync.sync(manual=True, confirm_local_deletions=True)
    assert result["deleted_local"] == 0
    assert len(todos.list_todos()) == 2


def test_confirmed_remote_delete_with_local_child_reports_resolvable_conflict(tmp_path):
    sync, todos, bridge, current = manager(tmp_path, [reminder(), reminder("r2")])
    sync.configure(["a"], "import")
    sync.sync()
    parent = next(row for row in todos.list_todos() if row["title"] == "Homework")
    child = todos.add_subtask(parent["id"], {"title": "Keep me"})
    bridge.rows = [reminder("r2")]
    sync.sync()
    current[0] += timedelta(minutes=2)
    sync.sync()
    result = sync.sync(manual=True, confirm_local_deletions=True)
    assert result["deleted_local"] == 0
    assert "subtasks" in sync.status()["conflicts"][0]["reason"]
    assert todos.get_todo(child["id"])["parent_id"] == parent["id"]


def test_native_save_without_mapping_recovers_stella_marker(tmp_path):
    sync, todos, bridge, _ = manager(tmp_path)
    sync.configure(["a"], "bidirectional")
    sync.sync()
    own = todos.create_todo({"title": "A local task"})
    bridge.rows.append(reminder("saved", stella_id=own["id"], title="A local task"))
    result = sync.sync()
    assert result["imported"] == 0
    assert len(todos.list_todos()) == 1
    assert sync._maps()[0]["todo_id"] == own["id"]


def test_relative_alarm_is_not_imported_or_overwritten(tmp_path):
    sync, todos, bridge, _ = manager(tmp_path, [reminder(remind_at=None, alarm_count=1)])
    sync.configure(["a"], "bidirectional")
    assert sync.sync()["conflicts"] == 1
    assert todos.list_todos() == [] and bridge.writes == []
    with pytest.raises(ValueError, match="unsupported"):
        sync.one_time("import", "a", ["r1"], confirm=True)


def test_preview_does_not_write_or_connect(tmp_path):
    sync, todos, bridge, _ = manager(tmp_path, [reminder()])
    preview = sync.preview(["a"], "import")
    assert preview["new"] == 1 and not bridge.writes and not todos.list_todos()
    assert sync.status()["connected"] is False


def test_preview_reports_updates_and_conflicts_without_mutation(tmp_path):
    sync, todos, bridge, _ = manager(tmp_path, [reminder()])
    sync.configure(["a"], "bidirectional")
    sync.sync()
    imported = todos.list_todos()[0]
    bridge.rows[0]["title"] = "Changed remotely"
    preview = sync.preview(["a"], "bidirectional")
    assert preview["updated"] == 1 and preview["conflicts"] == 0
    assert todos.get_todo(imported["id"])["title"] == "Homework"
    todos.update_todo(imported["id"], {"title": "Changed locally"})
    preview = sync.preview(["a"], "bidirectional")
    assert preview["updated"] == 0 and preview["conflicts"] == 1
    assert bridge.rows[0]["title"] == "Changed remotely"


def test_failed_scan_restarts_without_duplicate_import(tmp_path):
    sync, todos, bridge, _ = manager(tmp_path, [reminder()])
    sync.configure(["a"], "import")
    bridge.fail_next_scan = True
    assert sync.sync()["status"] == "error" and todos.list_todos() == []
    reopened = AppleReminderSync(bridge=bridge, db_path=tmp_path / "apple_reminders.db", todo_port=todos)
    assert reopened.sync()["imported"] == 1
    assert reopened.sync()["imported"] == 0 and len(todos.list_todos()) == 1


def test_ambiguous_ids_and_unsupported_recurrence_are_conflicts_not_imports(tmp_path):
    complex_rule = {"frequency": "monthly", "days": [1], "until": None,
                    "interval": 1, "count": 0, "rule_count": 1, "set_positions": [2]}
    rows = [reminder("r1", external_id="shared"), reminder("r2", list_id="b", external_id="shared"),
            reminder("r3", recurrence=complex_rule)]
    sync, todos, _, _ = manager(tmp_path, rows)
    sync.configure(["a", "b"], "import")
    result = sync.sync()
    assert result["conflicts"] == 3 and result["imported"] == 0
    assert todos.list_todos() == []


def test_shared_eventkit_runner_polls_and_watches_reminder_changes():
    from agent.calendar.apple_runtime import EventKitAutoRunner
    calls = []
    changed = threading.Event()

    class Bridge:
        def watch(self, callback, stop, kind="calendar"):
            calls.append(kind)
            callback()
            changed.set()
            stop.wait(0.01)

    runner = EventKitAutoRunner(Bridge(), lambda: True, lambda: calls.append("sync"),
                               kind="reminder", interval=0.01)
    runner.start()
    assert changed.wait(1)
    runner.stop()
    assert "reminder" in calls and "sync" in calls
