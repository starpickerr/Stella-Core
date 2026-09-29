"""Register the daily briefing in the shared scheduler; no private worker."""
from datetime import datetime, timedelta

from agent.scheduler.cron import iter_cron

DAILY_BRIEFING_TASK_ID = "daily-briefing"


def ensure_daily_briefing_task(task_store, now=None):
    """Provision once, preserving the user's edits, pause and deletion."""
    now = now or datetime.now()
    expression = "0 8 * * *"
    latest = iter_cron(expression, now + timedelta(microseconds=1)).get_prev(datetime)
    next_run = latest if latest.date() == now.date() else iter_cron(expression, now).get_next(datetime)
    return task_store.ensure_default_task({
        "id": DAILY_BRIEFING_TASK_ID,
        "name": "每日简报",
        "enabled": True,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "next_run_at": next_run.isoformat(),
        "schedule": {"type": "cron", "expression": expression},
        "catch_up": "same_day",
        "retry_interval_seconds": 300,
        "action": {
            "type": "tool_call",
            "call_name": "briefing",
            "call_params": {"action": "run", "operation": "create"},
            "silent": True,
        },
    })
