"""Cron expression helpers for the scheduler.

Supports both:
- 5 fields (Linux crontab): minute hour day month weekday
- 6 fields (Quartz):        second minute hour day month weekday

``second_at_beginning=True`` makes a 6-field expression mean Quartz rather
than croniter's default (which treats the extra field as year).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from croniter import croniter


def iter_cron(expression: str, start_time: datetime | None = None) -> Any:
    kwargs = {"second_at_beginning": True}
    if start_time is None:
        return croniter(expression, **kwargs)
    return croniter(expression, start_time, **kwargs)
