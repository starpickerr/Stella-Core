"""Apple reminder writes reach the stella.tasks plugin through the Application port.

The external-write domain rules (idempotent import, Stella-only fields, confirmed
deletes, no second notification) live in
Stella-Plugins/plugins/tasks/tests/test_external_todos.py.
"""

from datetime import datetime, timedelta, timezone


def remote(**overrides):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    return {"title": "Apple assignment", "notes": "From Apple", "due_on": "2026-10-10",
            "due_time": "14:00", "timezone": "Asia/Shanghai", "planned_on": "2026-10-09",
            "remind_at": future.isoformat(), "priority": 2, "repeat_frequency": "none",
            "completed": False, **overrides}


def test_application_todo_port_uses_the_same_external_write_boundary(todos_plugin):
    from application import Application, RequestContext
    port = Application.port("todos", RequestContext.ambient("apple_sync"))
    item = port.upsert_external_todo("eventkit:port", remote(remind_at=None))
    assert port.get_todo(item["id"])["source_type"] == "apple_reminder"
    assert port.delete_external_todo("eventkit:port", confirm=True)["deleted"] == item["id"]
