"""Published Chinese holiday schedules and all-day special-date file readers."""

from __future__ import annotations

import csv
import io
import re
from datetime import date


# State Council holiday notices. End dates are inclusive; make-up workdays are separate.
HOLIDAY_SCHEDULES = {
    2025: {
        "source": "https://www.gov.cn/zhengce/zhengceku/202411/content_6986383.htm",
        "off": [
            ("元旦", "2025-01-01", "2025-01-01"),
            ("春节", "2025-01-28", "2025-02-04"),
            ("清明节", "2025-04-04", "2025-04-06"),
            ("劳动节", "2025-05-01", "2025-05-05"),
            ("端午节", "2025-05-31", "2025-06-02"),
            ("国庆节·中秋节", "2025-10-01", "2025-10-08"),
        ],
        "work": ["2025-01-26", "2025-02-08", "2025-04-27", "2025-09-28", "2025-10-11"],
    },
    2026: {
        "source": "https://www.gov.cn/zhengce/zhengceku/202511/content_7047091.htm",
        "off": [
            ("元旦", "2026-01-01", "2026-01-03"),
            ("春节", "2026-02-15", "2026-02-23"),
            ("清明节", "2026-04-04", "2026-04-06"),
            ("劳动节", "2026-05-01", "2026-05-05"),
            ("端午节", "2026-06-19", "2026-06-21"),
            ("中秋节", "2026-09-25", "2026-09-27"),
            ("国庆节", "2026-10-01", "2026-10-07"),
        ],
        "work": ["2026-01-04", "2026-02-14", "2026-02-28", "2026-05-09", "2026-09-20", "2026-10-10"],
    },
}


def _date(value):
    if not isinstance(value, str):
        raise ValueError("date must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise ValueError("date must be YYYY-MM-DD") from exc


def parse_special_dates(content, format_name):
    """Read CSV or all-day iCalendar events as name/date/annual/description/uid rows."""
    if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > 1024 * 1024:
        raise ValueError("date file must be nonempty and at most 1 MB")
    if format_name == "csv":
        reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
        if not reader.fieldnames or not {"title", "date"}.issubset(set(reader.fieldnames)):
            raise ValueError("CSV must have title,date headers")
        rows = []
        for index, entry in enumerate(reader, 2):
            if None in entry:
                raise ValueError(f"CSV row {index}: too many columns")
            if not entry or not any((value or "").strip() for value in entry.values()):
                continue
            annual = (entry.get("annual") or "").strip().lower()
            if annual not in ("", "0", "1", "true", "false", "yes", "no"):
                raise ValueError(f"CSV row {index}: annual must be true or false")
            rows.append({"title": (entry.get("title") or "").strip(), "date": _date(entry.get("date")),
                         "annual": annual in ("1", "true", "yes"),
                         "description": (entry.get("description") or "").strip(),
                         "uid": (entry.get("uid") or "").strip()})
    elif format_name == "ics":
        lines = []
        for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if line.startswith((" ", "\t")) and lines:
                lines[-1] += line[1:]
            else:
                lines.append(line)
        rows, event = [], None
        for line in lines:
            if line == "BEGIN:VEVENT":
                event = {}
            elif line == "END:VEVENT" and event is not None:
                start = event.get("DTSTART", "")
                if not re.fullmatch(r"\d{8}", start):
                    raise ValueError("ICS import supports all-day VEVENT dates only")
                day = _date(f"{start[:4]}-{start[4:6]}-{start[6:]}")
                rule = event.get("RRULE", "")
                if rule and rule not in ("FREQ=YEARLY", "FREQ=YEARLY;INTERVAL=1"):
                    raise ValueError("ICS import supports simple yearly repeats only")
                if any(name in event for name in ("EXDATE", "RECURRENCE-ID", "RDATE")):
                    raise ValueError("ICS import does not support date exceptions")
                rows.append({"title": event.get("SUMMARY", "").replace("\\,", ",").replace("\\n", "\n"),
                             "date": day, "annual": bool(rule),
                             "description": event.get("DESCRIPTION", "").replace("\\n", "\n"),
                             "uid": event.get("UID", "")})
                event = None
            elif event is not None and ":" in line:
                name, value = line.split(":", 1)
                event[name.split(";", 1)[0].upper()] = value.strip()
    else:
        raise ValueError("format must be csv or ics")
    if not rows or len(rows) > 500:
        raise ValueError("date file must contain 1-500 dates")
    return rows
