"""Tasks domain behaviour: TodoService rules, schema migration, reminders and scheduler links."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from stella_tasks_domain.service import TodoService


@pytest.fixture
def service(tmp_path):
    return TodoService(tmp_path / "todos.db", tmp_path / "calendar.db")


def test_undated_todo_can_be_edited_completed_and_deleted(service):
    todo = service.create_todo({"title": "交作业", "notes": "上传 PDF", "priority": 2})
    assert todo["due_on"] is None and todo["completed_at"] is None
    assert [row["id"] for row in service.list_todos()] == [todo["id"]]
    assert service.list_todos("2026-10-01", "2026-10-02") == []
    service.complete_todo(todo["id"], True)
    assert service.list_todos(include_completed=False) == []
    service.complete_todo(todo["id"], False)
    updated = service.update_todo(todo["id"], {"due_on": "2026-10-02", "due_time": "09:30"})
    assert updated["due_time"] == "09:30" and updated["user_modified"] == 1
    assert service.list_todos("2026-10-02", "2026-10-03")[0]["id"] == todo["id"]
    service.delete_todo(todo["id"])
    assert service.list_todos() == []


def test_old_database_migrates_without_losing_todos(service):
    old = service.create_todo({"title": "Existing", "due_on": "2026-10-02"})
    with sqlite3.connect(service.db_path) as db:
        for column in ("planned_on", "list_name", "tags", "flagged", "checklist"):
            db.execute(f"ALTER TABLE todos DROP COLUMN {column}")
    reopened = TodoService(service.db_path, service.legacy_calendar_db_path)
    migrated = reopened.get_todo(old["id"])
    assert migrated["title"] == "Existing" and migrated["due_on"] == "2026-10-02"
    assert migrated["tags"] == "[]" and migrated["list_name"] == "" and migrated["flagged"] == 0
    updated = reopened.update_todo(old["id"], {"planned_on": "2026-10-01", "list_name": "Work",
        "tags": ["urgent", "urgent"], "flagged": True,
        "checklist": [{"id": "upload", "title": "Upload PDF"}]})
    assert updated["planned_on"] == "2026-10-01" and updated["due_on"] == "2026-10-02"
    assert json.loads(updated["tags"]) == ["urgent"]


def test_status_migration_preserves_completed_legacy_rows(service):
    done = service.create_todo({"title": "Old completed task"})
    completed = service.complete_todo(done["id"], True)
    with sqlite3.connect(service.db_path) as db:
        db.execute("DROP INDEX todos_parent_order")
        for column in ("status", "parent_id", "sort_order", "remind_at"):
            db.execute(f"ALTER TABLE todos DROP COLUMN {column}")
    reopened = TodoService(service.db_path, service.legacy_calendar_db_path)
    migrated = reopened.get_todo(done["id"])
    assert migrated["status"] == "completed"
    assert migrated["completed_at"] == completed["completed_at"]
    assert migrated["parent_id"] is None
    assert reopened.list_todos(include_completed=False) == []


def test_subtasks_status_progress_and_explicit_parent_completion(service):
    parent = service.create_todo({"title": "Homework"})
    first = service.add_subtask(parent["id"], {"title": "Read"})
    second = service.add_subtask(parent["id"], {"title": "Solve"})
    leaf = service.add_subtask(second["id"], {"title": "Problem 1"})
    assert service.get_todo(parent["id"])["progress_total"] == 2
    service.change_todo_status(first["id"], "completed")
    assert service.get_todo(parent["id"])["progress_percent"] == 50
    read_at = service.get_todo(first["id"])["completed_at"]
    service.complete_todo(parent["id"], True)
    assert service.get_todo(parent["id"])["status"] == "completed"
    assert service.get_todo(second["id"])["status"] == "completed"
    assert service.get_todo(leaf["id"])["status"] == "completed"
    assert service.get_todo(first["id"])["completed_at"] == read_at
    assert service.get_todo(parent["id"])["progress_percent"] == 100
    service.change_todo_status(leaf["id"], "cancelled")
    assert service.get_todo(second["id"])["progress_total"] == 0
    service.change_todo_status(parent["id"], "in_progress")
    assert service.get_todo(parent["id"])["completed_at"] is None
    assert service.get_todo(second["id"])["status"] == "completed"
    assert service.get_todo(first["id"])["status"] == "completed"


def test_complete_parent_cascades_and_keeps_independent_uncomplete(service):
    parent = service.create_todo({"title": "Parent"})
    child = service.add_subtask(parent["id"], {"title": "Child"})
    dropped = service.add_subtask(child["id"], {"title": "Dropped"})
    service.change_todo_status(dropped["id"], "cancelled")
    outside = service.create_todo({"title": "Outside"})
    service.add_dependency(parent["id"], outside["id"])
    with pytest.raises(ValueError, match="unfinished_dependencies:1"):
        service.complete_todo(parent["id"], True)
    assert service.get_todo(child["id"])["status"] == "todo"
    service.complete_todo(parent["id"], True, force=True)
    assert service.get_todo(parent["id"])["status"] == "completed"
    assert service.get_todo(child["id"])["status"] == "completed"
    assert service.get_todo(dropped["id"])["status"] == "cancelled"
    assert service.get_todo(outside["id"])["status"] == "todo"
    service.complete_todo(parent["id"], False)
    assert service.get_todo(parent["id"])["status"] == "todo"
    assert service.get_todo(parent["id"])["completed_at"] is None
    assert service.get_todo(child["id"])["status"] == "completed"

    nested = service.create_todo({"title": "Deep"})
    current = nested
    for level in range(12):
        current = service.add_subtask(current["id"], {"title": f"Level {level}"})
    service.complete_todo(nested["id"], True)
    assert service.get_todo(current["id"])["status"] == "completed"

    first = service.add_subtask(service.create_todo({"title": "Linked"})["id"], {"title": "First"})
    second = service.add_subtask(first["parent_id"], {"title": "Second"})
    service.add_dependency(second["id"], first["id"])
    service.complete_todo(first["parent_id"], True)
    assert service.get_todo(first["id"])["status"] == "completed"
    assert service.get_todo(second["id"])["status"] == "completed"


def test_move_reorder_promote_and_cycle_rejection(service):
    first = service.create_todo({"title": "First"})
    second = service.create_todo({"title": "Second"})
    third = service.add_subtask(first["id"], {"title": "Third"})
    service.move_todo(second["id"], first["id"], 0)
    assert [row["title"] for row in sorted(
        (row for row in service.list_todos() if row["parent_id"] == first["id"]),
        key=lambda row: row["sort_order"])] == ["Second", "Third"]
    with pytest.raises(ValueError, match="cycle"):
        service.move_todo(first["id"], third["id"])
    service.move_todo(third["id"], None, 0)
    assert service.get_todo(third["id"])["parent_id"] is None
    assert service.get_todo(first["id"])["progress_total"] == 1


def test_deep_subtasks_move_and_delete_share_one_tree(service):
    root = service.create_todo({"title": "Root"})
    parent = root
    for level in range(16):
        parent = service.add_subtask(parent["id"], {"title": f"Level {level}"})
    leaf = parent
    sibling = service.add_subtask(root["id"], {"title": "Sibling"})
    assert leaf["id"] in {row["id"] for row in service.list_todos_focus()}
    with pytest.raises(ValueError, match="cycle"):
        service.move_todo(root["id"], leaf["id"])
    service.move_todo(leaf["id"], sibling["id"], 0)
    assert service.get_todo(leaf["id"])["parent_id"] == sibling["id"]
    assert service.get_todo(sibling["id"])["progress_total"] == 1
    service.delete_todo(root["id"])
    assert service.list_todos() == []


def test_corrupt_parent_cycle_does_not_hang_move_or_delete(service):
    first = service.create_todo({"title": "First"})
    second = service.create_todo({"title": "Second"})
    other = service.create_todo({"title": "Other"})
    with sqlite3.connect(service.db_path) as db:
        db.execute("UPDATE todos SET parent_id=? WHERE id=?", (second["id"], first["id"]))
        db.execute("UPDATE todos SET parent_id=? WHERE id=?", (first["id"], second["id"]))
    with pytest.raises(ValueError, match="cycle"):
        service.move_todo(other["id"], first["id"])
    service.delete_todo(first["id"])
    assert [row["id"] for row in service.list_todos()] == [other["id"]]


def test_recurring_task_cannot_be_parent_or_child(service):
    recurring = service.create_todo({"title": "Daily", "due_on": "2026-10-02", "repeat_frequency": "daily"})
    with pytest.raises(ValueError, match="recurring"):
        service.add_subtask(recurring["id"], {"title": "Child"})
    parent = service.create_todo({"title": "Parent"})
    with pytest.raises(ValueError, match="recurring"):
        service.create_todo({"title": "Child", "parent_id": parent["id"],
                             "due_on": "2026-10-02", "repeat_frequency": "daily"})


def test_dependencies_are_separate_from_hierarchy_and_gate_progress(service):
    check = service.create_todo({"title": "Check answers"})
    submit = service.create_todo({"title": "Submit homework"})
    service.add_dependency(submit["id"], check["id"])
    assert service.get_todo(submit["id"])["parent_id"] is None
    assert service.get_todo(submit["id"])["blocked_by"] == [check["id"]]
    with pytest.raises(ValueError, match="unfinished_dependencies"):
        service.change_todo_status(submit["id"], "in_progress")
    with pytest.raises(ValueError, match="cycle"):
        service.add_dependency(check["id"], submit["id"])
    service.complete_todo(check["id"], True)
    service.change_todo_status(submit["id"], "in_progress")
    assert service.get_todo(submit["id"])["blocked_by"] == []
    service.remove_dependency(submit["id"], check["id"])
    assert service.get_todo(submit["id"])["dependency_ids"] == []
    later = service.create_todo({"title": "Later"})
    with pytest.raises(ValueError, match="active task"):
        service.add_dependency(submit["id"], later["id"])


def test_independent_reminder_can_be_rescheduled_and_cancelled(service):
    todo = service.create_todo({"title": "Review", "remind_at": "2026-10-02T08:00:00+08:00"})
    first_due = datetime.fromisoformat("2026-10-02T00:01:00+00:00")
    first = service.claim_desktop_reminders(first_due)
    assert len(first) == 1 and first[0]["todo_id"] == todo["id"]
    service.update_todo(todo["id"], {"remind_at": "2026-10-02T09:00:00+08:00"})
    assert not service.acknowledge_desktop_reminder(first[0]["delivery_id"], first[0]["claim_id"], True)
    second = service.claim_desktop_reminders(datetime.fromisoformat("2026-10-02T01:01:00+00:00"))
    assert len(second) == 1 and second[0]["delivery_id"] != first[0]["delivery_id"]
    service.change_todo_status(todo["id"], "cancelled")
    assert service.claim_desktop_reminders(datetime.fromisoformat("2026-10-02T01:02:00+00:00")) == []


def test_explicit_reminder_creates_and_updates_linked_scheduler_task(tmp_path, scheduler_store_cls):
    store = scheduler_store_cls()
    service = TodoService(tmp_path / "todos.db", tmp_path / "calendar.db", scheduler_store=store)
    first = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0).isoformat()
    second = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(microsecond=0).isoformat()
    todo = service.create_todo({"title": "交作业", "remind_at": first})
    linked = store.get_task(todo["scheduler_task_id"])
    assert linked["linked_todo_id"] == todo["id"]
    assert linked["schedule"] == {"type": "once", "run_at": first}
    assert linked["action"]["params"] == [todo["id"], first]
    assert not todo["reminder_sync_pending"]
    assert not service.queue_scheduled_reminder(todo["id"], first)

    updated = service.update_todo(todo["id"], {"title": "提交报告", "remind_at": second})
    linked = store.get_task(updated["scheduler_task_id"])
    assert linked["name"] == "事务提醒：提交报告"
    assert linked["schedule"]["run_at"] == second
    assert not service.queue_scheduled_reminder(todo["id"], first, now=datetime.now(timezone.utc) + timedelta(hours=4))
    assert service.queue_scheduled_reminder(todo["id"], second, now=datetime.now(timezone.utc) + timedelta(hours=4))
    assert service.queue_scheduled_reminder(todo["id"], second, now=datetime.now(timezone.utc) + timedelta(hours=4))
    deliveries = service.claim_desktop_reminders(datetime.now(timezone.utc) + timedelta(hours=4))
    assert len(deliveries) == 1 and deliveries[0]["todo_id"] == todo["id"]

    service.change_todo_status(todo["id"], "completed")
    assert store.get_task(linked["id"]) is None
    assert service.get_todo(todo["id"])["scheduler_task_id"] is None
    restored = service.change_todo_status(todo["id"], "todo")
    assert restored["scheduler_task_id"] == linked["id"]
    parent = service.create_todo({"title": "大事务"})
    child = service.add_subtask(parent["id"], {"title": "子事务", "remind_at": first})
    assert store.get_task(child["scheduler_task_id"])
    service.delete_todo(parent["id"])
    assert store.get_task(child["scheduler_task_id"]) is None


def test_reminder_route_persists_and_updates_one_scheduler_task(tmp_path, scheduler_store_cls):
    store = scheduler_store_cls()
    service = TodoService(tmp_path / "todos.db", tmp_path / "calendar.db", scheduler_store=store)
    instant = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)
    local = instant.astimezone(timezone(timedelta(hours=8))).isoformat()
    utc = instant.isoformat()
    telegram = {"primary": {"channel_type": "telegram", "receiver": "100"}}
    todo = service.create_todo({"title": "Submit", "remind_at": local, "reminder_delivery": telegram})
    task_id = todo["scheduler_task_id"]
    assert todo["remind_at"] == utc
    assert todo["reminder_delivery"]["primary"]["receiver"] == "100"
    assert todo["reminder_delivery"]["needs_reselect"] is False
    assert service.list_todos()[0]["reminder_delivery"] == todo["reminder_delivery"]
    assert store.get_task(task_id)["reminder_delivery"] == todo["reminder_delivery"]
    assert todo["reminder_delivery_status"] is None

    changed = service.update_todo(todo["id"], {"remind_at": utc,
        "reminder_delivery": {"primary": {"channel_type": "telegram", "receiver": "200"}}})
    assert changed["scheduler_task_id"] == task_id
    assert store.get_task(task_id)["reminder_delivery"]["primary"]["receiver"] == "200"
    assert len(store.list_tasks()) == 1
    assert service.queue_scheduled_reminder(todo["id"], local, now=instant + timedelta(minutes=1))
    assert service.queue_scheduled_reminder(todo["id"], utc, now=instant + timedelta(minutes=1))
    assert service.get_todo(todo["id"])["reminder_delivery_status"]["status"] == "pending"
    assert service.list_todos()[0]["reminder_delivery_status"]["status"] == "pending"
    service.update_todo(todo["id"], {"remind_at": None})
    assert service.get_todo(todo["id"])["reminder_delivery"]["primary"] is None
    assert service.get_todo(todo["id"])["reminder_delivery_status"]["status"] == "cancelled"
    assert store.get_task(task_id) is None


def test_reminder_route_requires_time_and_legacy_rows_default_to_desktop(tmp_path):
    service = TodoService(tmp_path / "todos.db", tmp_path / "calendar.db")
    with pytest.raises(ValueError, match="remind_at"):
        service.create_todo({"title": "No time", "reminder_delivery": {
            "primary": {"channel_type": "telegram", "receiver": "100"}}})
    instant = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    todo = service.create_todo({"title": "Legacy", "remind_at": instant})
    with sqlite3.connect(service.db_path) as db:
        db.execute("ALTER TABLE todos DROP COLUMN reminder_delivery")
    reopened = TodoService(service.db_path, service.legacy_calendar_db_path)
    assert reopened.get_todo(todo["id"])["reminder_delivery"] == {
        "primary": None, "needs_reselect": False}
    assert reopened.list_todos()[0]["reminder_delivery"]["primary"] is None
    with pytest.raises(ValueError, match="remind_at"):
        reopened.update_todo(todo["id"], {"remind_at": None, "reminder_delivery": {
            "primary": {"channel_type": "telegram", "receiver": "100"}}})


def test_disconnected_route_does_not_block_unrelated_todo_edit(tmp_path):
    # The domain validates routes structurally and never consults live channels, so a
    # channel that disconnects after the route was saved cannot block other edits.
    # Core keeps the runtime-disconnected variant in tests/test_todos.py (real worker).
    service = TodoService(tmp_path / "todos.db", tmp_path / "calendar.db")
    instant = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    todo = service.create_todo({"title": "Original", "remind_at": instant,
        "reminder_delivery": {"primary": {"channel_type": "telegram", "receiver": "100"}}})
    renamed = service.update_todo(todo["id"], {"title": "Renamed"})
    assert renamed["title"] == "Renamed"
    assert renamed["reminder_delivery"] == todo["reminder_delivery"]


def test_scheduler_link_retries_after_store_failure(tmp_path, scheduler_store_cls):
    class FlakyStore(scheduler_store_cls):
        fail = True

        def add_task(self, task):
            if self.fail:
                raise OSError("scheduler unavailable")
            return super().add_task(task)

    store = FlakyStore()
    path = tmp_path / "todos.db"
    service = TodoService(path, tmp_path / "calendar.db", scheduler_store=store)
    reminder = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    todo = service.create_todo({"title": "稍后提醒", "remind_at": reminder})
    assert todo["reminder_sync_pending"]
    assert store.get_task(todo["scheduler_task_id"]) is None
    store.fail = False
    reopened = TodoService(path, tmp_path / "calendar.db", scheduler_store=store)
    assert store.get_task(todo["scheduler_task_id"])
    assert not reopened.get_todo(todo["id"])["reminder_sync_pending"]


def test_existing_explicit_reminder_is_linked_on_upgrade(tmp_path, scheduler_store_cls):
    path = tmp_path / "todos.db"
    reminder = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    original = TodoService(path, tmp_path / "calendar.db")
    todo = original.create_todo({"title": "旧事务", "remind_at": reminder})
    assert todo["scheduler_task_id"]
    store = scheduler_store_cls()
    upgraded = TodoService(path, tmp_path / "calendar.db", scheduler_store=store)
    assert store.get_task(todo["scheduler_task_id"])["schedule"]["run_at"] == reminder
    assert not upgraded.get_todo(todo["id"])["reminder_sync_pending"]


def test_opening_todos_does_not_write_existing_scheduler_links_under_writer_lock(tmp_path, monkeypatch, scheduler_store_cls):
    import sqlite3

    path = tmp_path / "todos.db"
    calendar_path = tmp_path / "calendar.db"
    sqlite3.connect(str(calendar_path)).close()
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    store = scheduler_store_cls()
    original = TodoService(path, calendar_path, scheduler_store=store)
    reminder = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    todo = original.create_todo({"title": "已有提醒", "remind_at": reminder})
    real_connect = sqlite3.connect

    def quick_connect(database, *args, **kwargs):
        if str(database) == str(path):
            kwargs["timeout"] = 0.05
        return real_connect(database, *args, **kwargs)

    with real_connect(str(path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE todos SET title=title WHERE id=?", (todo["id"],))
        monkeypatch.setattr(sqlite3, "connect", quick_connect)
        reopened = TodoService(path, calendar_path, scheduler_store=store)
        assert reopened.list_todos()[0]["id"] == todo["id"]


def test_opening_todos_defers_pending_scheduler_sync_until_lock_clears(tmp_path, monkeypatch, scheduler_store_cls):
    import sqlite3
    from contextlib import contextmanager

    path = tmp_path / "todos.db"
    store = scheduler_store_cls()
    original = TodoService(path, tmp_path / "calendar.db", scheduler_store=store)
    reminder = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    todo = original.create_todo({"title": "待同步提醒", "remind_at": reminder})
    with sqlite3.connect(str(path)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("UPDATE todo_scheduler_links SET state='pending' WHERE todo_id=?", (todo["id"],))

    real_connect = TodoService._connect

    @contextmanager
    def quick_connect(self):
        with real_connect(self) as db:
            db.execute("PRAGMA busy_timeout=50")
            yield db

    with sqlite3.connect(str(path)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE todos SET title=title WHERE id=?", (todo["id"],))
        monkeypatch.setattr(TodoService, "_connect", quick_connect)
        reopened = TodoService(path, tmp_path / "calendar.db", scheduler_store=store)
        assert reopened.list_todos()[0]["id"] == todo["id"]
    TodoService(path, tmp_path / "calendar.db", scheduler_store=store)
    with sqlite3.connect(str(path)) as db:
        assert db.execute("SELECT state FROM todo_scheduler_links WHERE todo_id=?", (todo["id"],)).fetchone()[0] == "synced"


def test_missing_scheduler_link_backfill_recovers_after_writer_lock(tmp_path, monkeypatch, scheduler_store_cls):
    import sqlite3
    from contextlib import contextmanager

    path = tmp_path / "todos.db"
    store = scheduler_store_cls()
    original = TodoService(path, tmp_path / "calendar.db", scheduler_store=store)
    reminder = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    todo = original.create_todo({"title": "待回填提醒", "remind_at": reminder})
    with sqlite3.connect(str(path)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("DELETE FROM todo_scheduler_links WHERE todo_id=?", (todo["id"],))

    real_connect = TodoService._connect

    @contextmanager
    def quick_connect(self):
        with real_connect(self) as db:
            db.execute("PRAGMA busy_timeout=50")
            yield db

    with sqlite3.connect(str(path)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE todos SET title=title WHERE id=?", (todo["id"],))
        monkeypatch.setattr(TodoService, "_connect", quick_connect)
        reopened = TodoService(path, tmp_path / "calendar.db", scheduler_store=store)
        assert reopened.list_todos()[0]["id"] == todo["id"]
    TodoService(path, tmp_path / "calendar.db", scheduler_store=store)
    with sqlite3.connect(str(path)) as db:
        assert db.execute("SELECT state FROM todo_scheduler_links WHERE todo_id=?", (todo["id"],)).fetchone()[0] == "synced"


def test_desktop_migrations_defer_together_and_recover_after_writer_lock(tmp_path, monkeypatch, scheduler_store_cls):
    import sqlite3
    from contextlib import contextmanager

    path = tmp_path / "todos.db"
    calendar_path = tmp_path / "calendar.db"
    sqlite3.connect(str(calendar_path)).close()
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    store = scheduler_store_cls()
    TodoService(path, calendar_path, scheduler_store=store)
    with sqlite3.connect(str(path)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("DELETE FROM todo_migrations WHERE name IN ('calendar_affairs_v1','desktop_reminders_v1')")

    real_connect = TodoService._connect

    @contextmanager
    def quick_connect(self):
        with real_connect(self) as db:
            db.execute("PRAGMA busy_timeout=50")
            yield db

    with sqlite3.connect(str(path)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE todo_migrations SET name=name")
        monkeypatch.setattr(TodoService, "_connect", quick_connect)
        assert TodoService(path, calendar_path, scheduler_store=store).list_todos() == []
        with sqlite3.connect(str(path)) as reader:
            assert reader.execute("SELECT count(*) FROM todo_migrations").fetchone()[0] == 0
    TodoService(path, calendar_path, scheduler_store=store)
    with sqlite3.connect(str(path)) as db:
        assert {row[0] for row in db.execute("SELECT name FROM todo_migrations")} == {"calendar_affairs_v1", "desktop_reminders_v1"}


def test_same_service_retries_calendar_migration_after_the_writer_lock(tmp_path, monkeypatch, scheduler_store_cls):
    import sqlite3
    from contextlib import contextmanager

    path = tmp_path / "todos.db"
    calendar_path = tmp_path / "calendar.db"
    sqlite3.connect(str(calendar_path)).close()
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    store = scheduler_store_cls()
    TodoService(path, calendar_path, scheduler_store=store)
    with sqlite3.connect(str(path)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("DELETE FROM todo_migrations WHERE name IN ('calendar_affairs_v1','desktop_reminders_v1')")
    real_connect = TodoService._connect

    @contextmanager
    def quick_connect(self):
        with real_connect(self) as db:
            db.execute("PRAGMA busy_timeout=50")
            yield db

    with sqlite3.connect(str(path)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE todo_migrations SET name=name")
        monkeypatch.setattr(TodoService, "_connect", quick_connect)
        service = TodoService(path, calendar_path, scheduler_store=store)
        assert service.list_todos() == []
    monkeypatch.setattr(TodoService, "_connect", real_connect)
    assert service.list_todos() == []
    with sqlite3.connect(str(path)) as db:
        assert {row[0] for row in db.execute("SELECT name FROM todo_migrations")} == {
            "calendar_affairs_v1", "desktop_reminders_v1"}


def test_repeating_checklist_completion_and_plan_date_are_occurrence_scoped(service):
    todo = service.create_todo({"title": "Daily", "due_on": "2026-10-02", "planned_on": "2026-10-01",
        "repeat_frequency": "daily", "checklist": [{"id": "step", "title": "Check"}]})
    service.complete_checklist_item(f"{todo['id']}@2026-10-02", "step", True)
    rows = service.list_todos("2026-10-02", "2026-10-04")
    assert rows[0]["planned_on"] == "2026-10-01" and rows[1]["planned_on"] == "2026-10-02"
    assert json.loads(rows[0]["checklist"])[0]["completed"] is True
    assert json.loads(rows[1]["checklist"])[0]["completed"] is False
    assert service.list_todos_focus("2026-10-02")[0]["id"] == rows[0]["id"]
    service.complete_todo(rows[0]["id"], True)
    focus = service.list_todos_focus("2026-10-02")
    assert len(focus) == 2
    assert focus[0]["id"] == rows[1]["id"] and focus[0]["completed_at"] is None
    assert focus[1]["id"] == rows[0]["id"] and focus[1]["completed_at"] is not None


def test_focus_keeps_sparse_leap_year_series_visible(service):
    todo = service.create_todo({"title": "Leap day", "due_on": "2096-02-29", "repeat_frequency": "yearly"})
    service.complete_todo(f"{todo['id']}@2096-02-29", True)
    focus = service.list_todos_focus("2100-03-01")
    assert focus[0]["due_on"] == "2104-02-29" and focus[0]["completed_at"] is None


@pytest.mark.parametrize("payload", [{"tags": "oops"}, {"flagged": 2}, {"planned_on": "tomorrow"},
    {"checklist": [{"title": "", "completed": True}]},
    {"checklist": [{"id": "x", "title": "One"}, {"id": "x", "title": "Two"}]}])
def test_organization_fields_reject_invalid_values(service, payload):
    with pytest.raises(ValueError):
        service.create_todo({"title": "Test", **payload})
    assert service.list_todos() == []


def test_weekly_completion_applies_to_one_occurrence(service):
    todo = service.create_todo({"title": "上交周报", "due_on": "2026-10-05", "due_time": "17:00",
                                "repeat_frequency": "weekly", "repeat_days": [0], "repeat_until": "2026-10-19"})
    rows = service.list_todos("2026-10-01", "2026-10-22")
    assert [row["due_on"] for row in rows] == ["2026-10-05", "2026-10-12", "2026-10-19"]
    service.complete_todo(rows[0]["id"], True)
    assert [bool(row["completed_at"]) for row in service.list_todos("2026-10-01", "2026-10-22")] == [True, False, False]
    with pytest.raises(ValueError, match="occurrence"):
        service.complete_todo(todo["id"], True)


def test_todo_validation(service):
    for payload in ({"title": "x", "due_time": "09:00"}, {"title": "x", "priority": 4},
                    {"title": "x", "repeat_frequency": "daily"}, {"title": "x", "due_on": "2026-02-30"}):
        with pytest.raises(ValueError):
            service.create_todo(payload)


def test_briefing_actions_create_todos_and_preserve_user_edits(service):
    item = SimpleNamespace(source="elearning", account_id="student", source_id="homework-1",
                           source_item_id="source-1", section="action", title="交作业", snippet="课后作业",
                           payload={"due_at": "2026-10-02T20:00:00+08:00"}, url="https://example.test",
                           id="card-1")
    detail = {"briefing": SimpleNamespace(id="briefing-1"), "items": [item], "mail": []}
    service.ingest_briefing(detail)
    service.ingest_briefing(detail)
    assert service.list_todos() == []
    key = json.dumps([item.source, item.account_id, item.source_id], separators=(',', ':'))
    service._upsert_sourced_todo(key, item, item.payload['due_at'], 'briefing-1')
    service._upsert_sourced_todo(key, item, item.payload['due_at'], 'briefing-1')
    rows = service.list_todos()
    assert len(rows) == 1 and rows[0]["due_on"] == "2026-10-02" and rows[0]["due_time"] == "20:00"
    service.complete_todo(rows[0]["id"], True)
    item.section = "fyi"
    service.ingest_briefing(detail)
    service._upsert_sourced_todo(key, item, item.payload['due_at'], 'briefing-1')
    assert len(service.list_todos()) == 1 and service.list_todos()[0]["completed_at"]


def test_migrates_old_calendar_affairs_and_completion(tmp_path, legacy_calendar_db):
    calendar_path = tmp_path / "calendar.db"
    legacy_calendar_db(calendar_path)
    with sqlite3.connect(calendar_path) as db:
        db.executescript("""CREATE TABLE calendar_affairs (
            id TEXT PRIMARY KEY,title TEXT,notes TEXT,due_on TEXT,due_time TEXT,timezone TEXT,
            priority INTEGER,completed_at TEXT,repeat_frequency TEXT,repeat_days TEXT,repeat_until TEXT,
            source_type TEXT,source_key TEXT,source_url TEXT,user_modified INTEGER,created_at TEXT,updated_at TEXT);
            CREATE TABLE calendar_affair_completions (affair_id TEXT,occurrence_on TEXT,completed_at TEXT);
            CREATE TABLE calendar_affair_notifications (affair_id TEXT,occurrence_on TEXT,notified_at TEXT);""")
        db.execute("INSERT INTO calendar_affairs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("old-id", "旧重复事务", "备注", "2026-10-01", "09:00", "Asia/Shanghai", 2, None,
                    "daily", "[]", None, None, None, "", 1, "2026-09-01", "2026-09-01"))
        db.execute("INSERT INTO calendar_affair_completions VALUES (?,?,?)",
                   ("old-id", "2026-10-01", "2026-10-01T01:00:00+00:00"))
        db.execute("INSERT INTO calendar_affair_notifications VALUES (?,?,?)",
                   ("old-id", "2026-10-01", "2026-10-01T01:00:00+00:00"))
    service = TodoService(tmp_path / "todos.db", calendar_path)
    rows = service.list_todos("2026-10-01", "2026-10-03")
    assert rows[0]["id"] == "old-id@2026-10-01" and rows[0]["completed_at"]
    assert rows[1]["id"] == "old-id@2026-10-02" and not rows[1]["completed_at"]
    assert service.claim_due_todo_notifications(datetime(2026, 10, 1, 1, 1, tzinfo=timezone.utc)) == []


def test_due_notifications_claim_once_and_skip_completed_occurrences(service):
    due = {"due_on": "2026-10-01", "due_time": "09:00", "timezone": "Asia/Shanghai"}
    single = service.create_todo({"title": "交作业", **due})
    recurring = service.create_todo({"title": "打卡", **due, "repeat_frequency": "daily"})
    service.complete_todo(f"{recurring['id']}@2026-10-01", True)
    now = datetime(2026, 10, 1, 1, 1, tzinfo=timezone.utc)
    assert [row["id"] for row in service.claim_due_todo_notifications(now)] == [single["id"]]
    assert service.claim_due_todo_notifications(now) == []
    tomorrow = datetime(2026, 10, 2, 1, 1, tzinfo=timezone.utc)
    assert f"{recurring['id']}@2026-10-02" in [row["id"] for row in service.claim_due_todo_notifications(tomorrow)]


def test_desktop_reminder_lease_ack_and_retry(service):
    from datetime import datetime, timezone

    todo = service.create_todo({"title": "Pay bill", "due_on": "2026-10-02",
                                "due_time": "08:00", "timezone": "Asia/Shanghai"})
    due = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
    claimed = service.claim_desktop_reminders(due)
    assert len(claimed) == 1
    assert claimed[0]["todo_id"] == todo["id"]
    assert service.claim_desktop_reminders(due) == []
    delivery = claimed[0]
    assert not service.acknowledge_desktop_reminder(delivery["delivery_id"], "wrong", True)
    assert service.acknowledge_desktop_reminder(delivery["delivery_id"], delivery["claim_id"], False)
    retried = service.claim_desktop_reminders(due)
    assert retried[0]["delivery_id"] == delivery["delivery_id"]
    assert retried[0]["claim_id"] != delivery["claim_id"]
    assert service.acknowledge_desktop_reminder(retried[0]["delivery_id"], retried[0]["claim_id"], True)
    assert service.claim_desktop_reminders(due) == []


def test_desktop_reminder_cancels_on_completion(service):
    from datetime import datetime, timezone

    todo = service.create_todo({"title": "Review", "due_on": "2026-10-02",
                                "due_time": "08:00", "timezone": "Asia/Shanghai"})
    due = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
    delivery = service.claim_desktop_reminders(due)[0]
    service.complete_todo(todo["id"], True)
    assert not service.acknowledge_desktop_reminder(delivery["delivery_id"], delivery["claim_id"], True)
    assert service.claim_desktop_reminders(due) == []


def test_desktop_migration_records_old_claim_as_unknown(service, monkeypatch):
    todo = service.create_todo({"title": "Legacy", "due_on": "2026-10-02",
                                "due_time": "08:00", "timezone": "Asia/Shanghai"})
    with sqlite3.connect(service.db_path) as db:
        db.execute("INSERT INTO todo_notifications VALUES (?,?,?)",
                   (todo["id"], "2026-10-02", "2026-10-02T00:30:00+00:00"))
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    reopened = TodoService(service.db_path, service.legacy_calendar_db_path)
    with sqlite3.connect(service.db_path) as db:
        assert db.execute("SELECT state FROM reminder_occurrences WHERE todo_id=?",
                          (todo["id"],)).fetchone()[0] == "legacy_claimed_unknown"
        assert db.execute("SELECT status FROM reminder_deliveries").fetchone()[0] == "legacy_claimed_unknown"
    assert reopened.claim_desktop_reminders(datetime(2026, 10, 2, 1, tzinfo=timezone.utc)) == []


def test_legacy_unknown_reminder_needs_explicit_retry(service, monkeypatch):
    todo = service.create_todo({"title": "Review", "due_on": "2026-10-02",
                                "due_time": "08:00", "timezone": "Asia/Shanghai"})
    with sqlite3.connect(service.db_path) as db:
        db.execute("INSERT INTO todo_notifications VALUES (?,?,?)",
                   (todo["id"], "2026-10-02", datetime.now(timezone.utc).isoformat()))
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    reopened = TodoService(service.db_path, service.legacy_calendar_db_path)
    uncertain = reopened.list_uncertain_reminders()
    assert len(uncertain) == 1 and uncertain[0]["title"] == "Review"
    assert reopened.retry_uncertain_reminder(uncertain[0]["delivery_id"])
    assert reopened.list_uncertain_reminders() == []
    due = datetime(2026, 10, 2, 1, tzinfo=timezone.utc)
    assert reopened.claim_desktop_reminders(due)[0]["delivery_id"] == uncertain[0]["delivery_id"]


def test_legacy_unknown_reminder_is_cancelled_if_todo_completed(service, monkeypatch):
    todo = service.create_todo({"title": "Review", "due_on": "2026-10-02",
                                "due_time": "08:00", "timezone": "Asia/Shanghai"})
    with sqlite3.connect(service.db_path) as db:
        db.execute("INSERT INTO todo_notifications VALUES (?,?,?)",
                   (todo["id"], "2026-10-02", "2026-10-02T00:30:00+00:00"))
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    reopened = TodoService(service.db_path, service.legacy_calendar_db_path)
    reminder = reopened.list_uncertain_reminders()[0]
    reopened.complete_todo(todo["id"], True)
    assert not reopened.retry_uncertain_reminder(reminder["delivery_id"])
    assert reopened.list_uncertain_reminders() == []


def test_legacy_unknown_reminder_is_cancelled_if_todo_was_edited(service, monkeypatch):
    todo = service.create_todo({"title": "Review", "due_on": "2026-10-02",
                                "due_time": "08:00", "timezone": "Asia/Shanghai"})
    with sqlite3.connect(service.db_path) as db:
        db.execute("INSERT INTO todo_notifications VALUES (?,?,?)",
                   (todo["id"], "2026-10-02", "2026-10-02T00:30:00+00:00"))
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    reopened = TodoService(service.db_path, service.legacy_calendar_db_path)
    reminder = reopened.list_uncertain_reminders()[0]
    reopened.update_todo(todo["id"], {"due_time": "09:00"})
    assert not reopened.retry_uncertain_reminder(reminder["delivery_id"])
    assert reopened.list_uncertain_reminders() == []

