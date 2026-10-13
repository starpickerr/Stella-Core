"""One scheduler task for each active, explicit todo reminder."""

from __future__ import annotations

import os
from datetime import datetime, timezone


def default_scheduler_store():
    from common.state_dir import shared_root
    from agent.registry import get_agent_registry

    root = shared_root()
    agent_id = get_agent_registry().default_agent_id
    path = str(root / "scheduler" / "tasks.json")
    if os.environ.get("STELLA_DESKTOP") == "1":
        from agent.scheduler.automation_store import AutomationStore
        from agent.scheduler.integration import get_task_store
        return get_task_store(str(root), agent_id) or AutomationStore(path, agent_id)
    from agent.scheduler.store import TaskStore
    return TaskStore(path)


def task_id_for(todo_id: str) -> str:
    return "todo-reminder:" + todo_id


def sync_task(store, todo_id: str, title: str, remind_at: str | None,
              reminder_delivery: dict | None = None) -> None:
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
