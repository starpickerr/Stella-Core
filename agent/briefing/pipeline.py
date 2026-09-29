"""Daily run: fetch → catalog upsert → filter → compose → persist.

Cursors advance only after a non-failed briefing is saved. Adapters are
injected so tests can use StaticSource; IMAP lives in sources.email.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from common.log import logger

from agent.briefing.compose import compose
from agent.briefing.models import EmailMessage, SourceItem
from agent.briefing.rules import filter_candidates, fetched_to_payload
from agent.briefing.service import BriefingService, briefing_id_for
from agent.briefing.sources.base import FetchResult, FetchedItem, Source


def _now():
    return datetime.now().astimezone()


class BriefingPipeline:
    def __init__(
        self,
        service: Optional[BriefingService] = None,
        sources: Optional[Sequence[Source]] = None,
        clock=None,
    ):
        self.service = service if service is not None else BriefingService()
        self.sources = list(sources or [])
        self.clock = clock or _now

    def run(
        self,
        kind: str = "morning",
        briefing_date: Optional[str] = None,
        operation: str = "upsert",
        trigger: str = "manual",
    ) -> dict:
        if not self.sources:
            raise ValueError("no briefing sources configured")
        if operation not in {"create", "update", "upsert"}:
            raise ValueError("operation must be create or update")
        if trigger not in {"manual", "scheduled"}:
            raise ValueError("invalid briefing trigger")
        day = briefing_date or self.clock().date().isoformat()
        # Serialize shared-store runs so two requests cannot race the same cursor.
        with self.service.store.run_lock:
            existing = self.service.store.get_briefing(briefing_id_for(day, kind))
            if operation == "create" and existing and existing.generated_at:
                return self.service.get_briefing(existing.id)
            if operation == "update" and (not existing or not existing.generated_at):
                raise ValueError("generate this day's briefing before updating it")
            return self._run(kind, day, trigger)

    def _run(self, kind: str, day: str, trigger: str) -> dict:
        end = self.clock().astimezone(timezone.utc).replace(microsecond=0)
        existing = self.service.store.get_briefing(briefing_id_for(day, kind))
        if existing and existing.window_start:
            start = existing.window_start
        else:
            previous = [row for row in self.service.list_briefings(kind=kind)
                        if row.id[4:14] < day and row.generated_at]
            boundary = max((row.window_end or row.generated_at for row in previous),
                           key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")), default=None)
            start = boundary or (end - timedelta(days=2)).isoformat().replace("+00:00", "Z")
        finish = end.isoformat().replace("+00:00", "Z")
        if datetime.fromisoformat(start.replace("Z", "+00:00")) > end:
            raise ValueError("briefing end precedes the previous successful update")
        briefing = self.service.start_briefing(kind=kind, briefing_date=day)
        pending_cursors: List[Tuple[Source, Dict[str, str]]] = []
        errors: List[str] = []

        try:
            for source in self.sources:
                try:
                    result = self._fetch_source(source, start, finish)
                except Exception as exc:
                    logger.warning(
                        f"[BriefingPipeline] source {source.name} failed: {exc}"
                    )
                    errors.append(f"{source.name}: {exc}")
                    continue
                pending_cursors.append((source, result.cursors))
                self._upsert_fetched(result.items)

            catalog_rows = self.service.store.window_candidates(
                start, finish, [(source.name, source.account_id) for source in self.sources])
            self.service.store.add_candidates(briefing.id, [row[0].id for row in catalog_rows])
            fetched_count = len(catalog_rows)
            rules = self.service.list_rules(enabled_only=True)
            kept, filtered_count = filter_candidates(catalog_rows, rules)
            drafted = compose(kept, briefing_date=day, kind=kind)

            if errors and not pending_cursors:
                status = "failed"
            elif errors:
                status = "partial"
            else:
                status = "completed"

            detail = self.service.complete_briefing(
                briefing.id,
                {
                    "status": status,
                    "run_at": finish,
                    "window_start": start,
                    "window_end": finish,
                    "trigger": trigger,
                    "title": briefing.title or drafted["title"] if status == "failed" else drafted["title"],
                    "body": drafted["body"] if status != "failed" else briefing.body,
                    "fetched_count": fetched_count if status != "failed" else briefing.fetched_count,
                    "kept_count": drafted["kept_count"] if status != "failed" else briefing.kept_count,
                    "filtered_count": filtered_count if status != "failed" else briefing.filtered_count,
                    "error_message": "; ".join(errors),
                    **({"items": drafted["items"]} if status != "failed" else {}),
                },
            )
            if status != "failed":
                self._commit_cursors(pending_cursors)
            return detail
        except Exception as exc:
            logger.error(f"[BriefingPipeline] run failed: {exc}")
            self.service.complete_briefing(
                briefing.id,
                {
                    "status": "failed",
                    "run_at": finish,
                    "trigger": trigger,
                    "error_message": str(exc),
                },
            )
            raise

    def _fetch_source(self, source: Source, start: str, end: str) -> FetchResult:
        cursors: Dict[str, str] = {}
        # Adapters may use several keys; we pass known values and ignore misses.
        for key in ("imap_uid", "imap_uidvalidity", "sync_token", "since"):
            row = self.service.get_cursor(source.name, source.account_id, key)
            if row is not None:
                cursors[key] = row.cursor_value
        cursors.update({"since": start, "until": end})
        return source.fetch(cursors)

    def _upsert_fetched(
        self, items: Iterable[FetchedItem]
    ) -> List[Tuple[SourceItem, Optional[EmailMessage]]]:
        rows = []
        for fetched in items:
            rows.append(self.service.upsert_source_item(fetched_to_payload(fetched)))
        return rows

    def _commit_cursors(self, pending: Sequence[Tuple[Source, Dict[str, str]]]) -> None:
        for source, cursors in pending:
            for key, value in cursors.items():
                self.service.set_cursor(source.name, key, value, source.account_id)
