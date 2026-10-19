"""Compatibility facade: same method surface as CalendarService, routed to plugin RPC."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from core.services import calendar_gateway


def _db_path() -> Path:
    from common.state_dir import calendar_db

    return Path(calendar_db())


class CalendarPluginFacade:
    """Drop-in for Application._Port when STELLA_CALENDAR_PLUGIN is enabled."""

    # -- categories ---------------------------------------------------------
    def categories(self) -> list:
        return self._value("categories", {})

    def create_category(self, payload: dict) -> dict:
        return self._value("create_category", dict(payload))

    def get_category(self, category_id: str) -> dict:
        return self._value("get_category", {"id": category_id})

    def update_category(self, category_id: str, payload: dict) -> dict:
        return self._value("update_category", {"id": category_id, "patch": dict(payload)})

    def delete_category(self, category_id: str) -> None:
        self._value("delete_category", {"id": category_id})

    def set_event_category(self, event_id: str, category_id: Optional[str]) -> dict:
        return self._value(
            "set_event_category", {"id": event_id, "category_id": category_id}
        )

    # -- events -------------------------------------------------------------
    def get_event(self, event_id: str) -> dict:
        return self._value("get_event", {"id": event_id})

    def list_events(self, start=None, end=None, category_id=None) -> list:
        return self._value(
            "list_events", {"start": start, "end": end, "category_id": category_id}
        )

    def create_event(self, payload: dict, *, _briefing_key: Optional[str] = None) -> dict:
        body = dict(payload)
        if _briefing_key:
            body["_briefing_key"] = _briefing_key
        return self._value("create_event", body)

    def update_event(self, event_id: str, payload: dict) -> dict:
        return self._value("update_event", {"id": event_id, "patch": dict(payload)})

    def delete_event(self, event_id: str) -> None:
        self._value("delete_event", {"id": event_id})

    def upsert_external_event(
        self, provider, source_key, payload, event_id=None, reconciled=False
    ) -> dict:
        return self._value(
            "upsert_external_event",
            {
                "provider": provider,
                "source_key": source_key,
                "payload": dict(payload),
                "event_id": event_id,
                "reconciled": reconciled,
            },
        )

    def exclude_occurrence(self, series_id: str, occurrence_on: str) -> None:
        self._value(
            "exclude_occurrence",
            {"series_id": series_id, "occurrence_on": occurrence_on},
        )

    # -- imports ------------------------------------------------------------
    def import_china_holidays(self, year) -> dict:
        return self._value("import_china_holidays", {"year": year})

    def create_special_date(self, payload: dict) -> dict:
        return self._value("create_special_date", dict(payload))

    def import_special_dates(self, content, format_name, zone) -> dict:
        return self._value(
            "import_special_dates",
            {"content": content, "format": format_name, "timezone": zone},
        )

    # -- briefing collaboration --------------------------------------------
    def ingest_briefing_revision(self, detail, revision: int) -> int:
        briefing = detail["briefing"]
        briefing_id = briefing["id"] if isinstance(briefing, dict) else briefing.id
        result = self._value(
            "ingest_briefing_revision",
            {"briefing_id": briefing_id, "revision": revision},
        )
        return int(result["count"])

    def has_source_tombstone(self, source_keys) -> bool:
        result = self._value(
            "has_source_tombstone", {"source_keys": [k for k in source_keys if k]}
        )
        return bool(result["tombstoned"])

    def sync_briefing_facts(self, event_id, changes, baseline, force=False):
        result = self._value(
            "sync_briefing_facts",
            {"id": event_id, "changes": dict(changes), "baseline": dict(baseline), "force": force},
        )
        return result["event"], result["conflicts"]

    # -----------------------------------------------------------------------
    def _value(self, method: str, params: dict[str, Any]) -> Any:
        result = calendar_gateway.invoke_calendar(method, params, db_path=_db_path())
        status = result.get("status")
        if status == "failed":
            err = result.get("error") or {}
            message = err.get("message") or "calendar plugin call failed"
            if err.get("code") == "not_found":
                raise KeyError(message)
            raise ValueError(message)
        if status != "succeeded":
            raise RuntimeError(f"calendar plugin returned {status}")
        value = result.get("value")
        if method in {"delete_category", "delete_event", "exclude_occurrence"}:
            return None
        return value
