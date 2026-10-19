"""External (Apple reminder) writes keep Stella-only state and never add a second notification."""

from datetime import datetime, timedelta, timezone

import pytest

from stella_tasks_domain.service import TodoService


@pytest.fixture
def todos(tmp_path, scheduler_store):
    return TodoService(tmp_path / "todos.db", tmp_path / "calendar.db", scheduler_store=scheduler_store)


def remote(**overrides):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    return {"title": "Apple assignment", "notes": "From Apple", "due_on": "2026-10-10",
            "due_time": "14:00", "timezone": "Asia/Shanghai", "planned_on": "2026-10-09",
            "remind_at": future.isoformat(), "priority": 2, "repeat_frequency": "none",
            "completed": False, **overrides}


def test_apple_import_is_idempotent_and_preserves_stella_only_fields(todos, scheduler_store):
    store = scheduler_store
    first = todos.upsert_external_todo("eventkit:assignment", remote())
    again = todos.upsert_external_todo("eventkit:assignment", remote())
    assert first["id"] == again["id"] and len(todos.list_todos()) == 1
    assert first["source_type"] == "apple_reminder"
    assert (first["due_on"], first["due_time"], first["timezone"], first["planned_on"]) == (
        "2026-10-10", "14:00", "Asia/Shanghai", "2026-10-09")
    assert first["scheduler_task_id"] is None and store.list_tasks() == []

    parent = todos.create_todo({"title": "Parent"})
    dependency = todos.create_todo({"title": "Prerequisite"})
    todos.move_todo(first["id"], parent["id"])
    todos.add_dependency(first["id"], dependency["id"])
    route = {"primary": {"channel_type": "telegram", "receiver": "100"}}
    todos.update_todo(first["id"], {"reminder_delivery": route})
    assert len(store.list_tasks()) == 1
    todos.change_todo_status(first["id"], "waiting")
    with pytest.raises(ValueError, match="modified"):
        todos.upsert_external_todo("eventkit:assignment", remote(title="Changed in Apple"))
    merged = todos.upsert_external_todo("eventkit:assignment", remote(title="Changed in Apple"), reconciled=True)
    assert merged["title"] == "Changed in Apple"
    assert merged["parent_id"] == parent["id"] and merged["dependency_ids"] == [dependency["id"]]
    assert merged["status"] == "waiting" and merged["reminder_delivery"]["primary"]["receiver"] == "100"
    assert merged["user_modified"] == 0 and len(store.list_tasks()) == 1


def test_apple_completion_does_not_confuse_cancelled_with_completed(todos):
    item = todos.upsert_external_todo("eventkit:complete", remote(remind_at=None))
    done = todos.upsert_external_todo("eventkit:complete", remote(remind_at=None, completed=True,
        completed_at="2026-10-09T06:00:00+00:00"), reconciled=True)
    assert done["status"] == "completed" and done["completed_at"].startswith("2026-10-09T06:00:00")
    active = todos.upsert_external_todo("eventkit:complete", remote(remind_at=None), reconciled=True)
    assert active["status"] == "todo" and active["completed_at"] is None
    todos.change_todo_status(item["id"], "cancelled")
    cancelled = todos.upsert_external_todo("eventkit:complete", remote(remind_at=None, completed=True), reconciled=True)
    assert cancelled["status"] == "cancelled" and cancelled["completed_at"] is None


def test_source_key_and_confirmed_delete_prevent_silent_reimport(todos):
    item = todos.upsert_external_todo("eventkit:delete", remote(remind_at=None))
    with pytest.raises(ValueError, match="confirmation"):
        todos.delete_external_todo("eventkit:delete")
    with pytest.raises(KeyError):
        todos.delete_external_todo("eventkit:other", confirm=True)
    assert todos.get_todo(item["id"])["source_key"] == "eventkit:delete"
    todos.delete_external_todo("eventkit:delete", confirm=True)
    with pytest.raises(ValueError, match="deleted"):
        todos.upsert_external_todo("eventkit:delete", remote(remind_at=None))


def test_external_parent_deletion_preserves_stella_subtasks(todos):
    parent = todos.upsert_external_todo("eventkit:parent", remote(remind_at=None))
    child = todos.add_subtask(parent["id"], {"title": "Stella-only child"})
    with pytest.raises(ValueError, match="subtask"):
        todos.delete_external_todo("eventkit:parent", confirm=True)
    assert todos.get_todo(parent["id"])["id"] == parent["id"]
    assert todos.get_todo(child["id"])["parent_id"] == parent["id"]


def test_apple_import_does_not_create_a_second_default_notification(todos, scheduler_store):
    store = scheduler_store
    due = datetime.now(timezone.utc) + timedelta(minutes=10)
    imported = todos.upsert_external_todo("eventkit:alarm", remote(
        due_on=due.date().isoformat(), due_time=due.strftime("%H:%M"), timezone="UTC",
        remind_at=(due - timedelta(minutes=5)).isoformat()))
    assert imported["remind_at"] is not None
    assert store.list_tasks() == []
    assert todos.claim_desktop_reminders(now=due + timedelta(minutes=2)) == []

