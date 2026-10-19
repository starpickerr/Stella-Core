"""Reminder -> host scheduler task mapping (adapter-driven; no host imports)."""

from __future__ import annotations

from datetime import datetime, timezone


def task_id_for(todo_id: str) -> str:
    return "todo-reminder:" + todo_id


def sync_task(store, todo_id: str, title: str, remind_at: str | None,
              reminder_delivery: dict | None = None) -> None:
    """Create/update/delete the host scheduler task for one reminder.

    ``store`` is a host-provided adapter exposing get_task/add_task/update_task/delete_task.
    """
    task_id = task_id_for(todo_id)
    existing = store.get_task(task_id)
    if not remind_at:
        if existing:
            store.delete_task(task_id)
        return

    instant = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("remind_at must include a timezone")
    if instant <= datetime.now(timezone.utc):
        if existing:
            store.delete_task(task_id)
        return
    stamp = datetime.now(timezone.utc).isoformat()
    task = {
        "id": task_id,
        "name": "事务提醒：" + title,
        "enabled": True,
        "schedule": {"type": "once", "run_at": remind_at},
        "next_run_at": instant.astimezone().replace(tzinfo=None).isoformat(),
        "action": {"type": "application_command", "domain": "todos",
                   "command": "QueueTodoReminder", "params": [todo_id, remind_at]},
        "reminder_delivery": reminder_delivery,
        "linked_todo_id": todo_id,
        "created_at": existing.get("created_at", stamp) if existing else stamp,
        "updated_at": stamp,
    }
    if existing:
        store.update_task(task_id, task)
    else:
        store.add_task(task)
