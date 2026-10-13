"""Read-only upcoming Stella agenda for the existing briefing source pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from application import Application, RequestContext
from .base import FetchResult, FetchedItem


class CalendarAgendaSource:
    name = "calendar_agenda"
    account_id = "local"
    display_name = "Stella 日程"

    def __init__(self, calendar_port=None):
        self.calendar = calendar_port or Application.port("calendar", RequestContext.ambient("briefing"))

    def fetch(self, cursors):
        until = cursors.get("until")
        if not until:
            raise ValueError("briefing calendar window is required")
        now = datetime.fromisoformat(until.replace("Z", "+00:00")).astimezone(timezone.utc)
        finish = now + timedelta(days=1)
        items = []
        for event in self.calendar.list_events(now.isoformat(), finish.isoformat()):
            start = datetime.fromisoformat(event["start_at"])
            items.append(FetchedItem(
                source=self.name, account_id=self.account_id, source_id=event["id"],
                title=event["title"], sender="Stella 日程",
                snippet=f"{start.isoformat()} · {event['location']}" if event["location"] else start.isoformat(),
                occurred_at=now.isoformat().replace("+00:00", "Z"),
                payload={"body": event["description"], "information_type": "calendar_event",
                         "stella_calendar_event_id": event["id"]},
            ))
        return FetchResult(items=items)
