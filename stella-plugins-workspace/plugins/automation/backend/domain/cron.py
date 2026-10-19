"""Dependency-free cron evaluation (5-field crontab or 6-field Quartz, seconds first).

Mirrors the subset of ``croniter(..., second_at_beginning=True)`` the scheduler
uses: ``*``, ``?``, lists, ranges, ``a-b/n`` and ``*/n`` steps, month/weekday
names, Sunday as 0 or 7, and the crontab rule that day-of-month and
day-of-week match with OR when both are restricted.
"""

from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timedelta

_MONTHS = {n: i for i, n in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_DAYS = {n: i for i, n in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}

_SEARCH_DAYS = 366 * 8


def _value(token: str, names: dict[str, int], low: int, high: int) -> int:
    text = token.strip().lower()
    number = names[text] if text in names else int(text)
    if not low <= number <= high:
        raise ValueError(f"cron value out of range: {token}")
    return number


def _parse_field(text: str, low: int, high: int, names: dict[str, int] | None = None) -> tuple[set[int], bool]:
    """Return (allowed values, restricted?)."""
    names = names or {}
    if text in {"*", "?"}:
        return set(range(low, high + 1)), False
    values: set[int] = set()
    for part in text.split(","):
        step, stepped = 1, False
        if "/" in part:
            part, step_text = part.split("/", 1)
            step, stepped = int(step_text), True
            if step <= 0:
                raise ValueError("cron step must be positive")
        if part in {"*", "?", ""}:
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = _value(a, names, low, high), _value(b, names, low, high)
        else:
            start = _value(part, names, low, high)
            end = high if stepped else start
        if start > end:
            raise ValueError("cron range start exceeds end")
        values.update(range(start, end + 1, step))
    return values, True


class CronExpression:
    def __init__(self, expression: str):
        fields = str(expression or "").split()
        if len(fields) not in (5, 6):
            raise ValueError("cron expression must have 5 or 6 fields")
        if len(fields) == 5:
            fields = ["0", *fields]
        sec, minute, hour, dom, month, dow = fields
        self.seconds = sorted(_parse_field(sec, 0, 59)[0])
        self.minutes = sorted(_parse_field(minute, 0, 59)[0])
        self.hours = sorted(_parse_field(hour, 0, 23)[0])
        self.dom, self.dom_restricted = _parse_field(dom, 1, 31)
        self.months = _parse_field(month, 1, 12, _MONTHS)[0]
        weekdays, self.dow_restricted = _parse_field(dow, 0, 7, _DAYS)
        self.dow = {0 if v == 7 else v for v in weekdays}

    def _day_matches(self, day: datetime) -> bool:
        if day.month not in self.months:
            return False
        dom_ok = day.day in self.dom
        dow_ok = (day.isoweekday() % 7) in self.dow
        if self.dom_restricted and self.dow_restricted:
            return dom_ok or dow_ok
        return dom_ok and dow_ok

    def _first_time(self, floor: tuple[int, int, int]):
        """Smallest (h, m, s) in the schedule that is >= ``floor``."""
        for hour in self.hours[bisect_left(self.hours, floor[0]):]:
            for minute in self.minutes:
                for second in self.seconds:
                    if (hour, minute, second) >= floor:
                        return hour, minute, second
        return None

    def next_after(self, start: datetime) -> datetime:
        """First match strictly after ``start`` (sub-second parts ignored)."""
        moment = start.replace(microsecond=0) + timedelta(seconds=1)
        day = moment.replace(hour=0, minute=0, second=0)
        for offset in range(_SEARCH_DAYS):
            current = day + timedelta(days=offset)
            if not self._day_matches(current):
                continue
            found = self._first_time((moment.hour, moment.minute, moment.second) if offset == 0 else (0, 0, 0))
            if found:
                return current.replace(hour=found[0], minute=found[1], second=found[2])
        raise ValueError("cron expression never fires")


def next_cron(expression: str, start: datetime) -> datetime:
    return CronExpression(expression).next_after(start)
