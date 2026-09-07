from datetime import datetime

from agent.scheduler.cron import iter_cron
from agent.scheduler.service import SchedulerService


def test_five_field_linux_crontab_is_daily_at_hour():
    start = datetime(2026, 9, 7, 15, 0, 0)
    nxt = iter_cron("0 9 * * *", start).get_next(datetime)
    assert nxt == datetime(2026, 9, 8, 9, 0, 0)


def test_six_field_quartz_puts_seconds_first():
    start = datetime(2026, 9, 7, 15, 0, 0)
    nxt = iter_cron("0 0 9 * * *", start).get_next(datetime)
    assert nxt == datetime(2026, 9, 8, 9, 0, 0)


def test_scheduler_service_uses_quartz_six_field():
    service = SchedulerService(task_store=None, execute_callback=lambda _t: None)
    nxt = service._calculate_next_run(
        {"schedule": {"type": "cron", "expression": "0 0 9 * * *"}},
        datetime(2026, 9, 7, 15, 0, 0),
    )
    assert nxt == datetime(2026, 9, 8, 9, 0, 0)
