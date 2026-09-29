"""Daily run: fetch → catalog upsert → filter → compose → persist.

Cursors advance only after a non-failed briefing is saved. Adapters are
injected so tests can use StaticSource; IMAP lives in sources.email.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from common.log import logger

from agent.briefing.compose import compose
from agent.briefing.models import EmailMessage, SourceItem
from agent.briefing.rules import filter_candidates, fetched_to_payload
from agent.briefing.service import BriefingService
from agent.briefing.sources.base import FetchResult, FetchedItem, Source


class BriefingPipeline:
    def __init__(
        self,
        service: Optional[BriefingService] = None,
        sources: Optional[Sequence[Source]] = None,
    ):
        self.service = service if service is not None else BriefingService()
        self.sources = list(sources or [])

    def run(
        self,
        kind: str = "morning",
        briefing_date: Optional[str] = None,
    ) -> dict:
        if not self.sources:
            raise ValueError("no briefing sources configured")
        day = briefing_date or date.today().isoformat()
        # Serialize shared-store runs so two requests cannot race the same cursor.
        with self.service.store.run_lock:
            return self._run(kind, day)

    def _run(self, kind: str, day: str) -> dict:
        briefing = self.service.start_briefing(kind=kind, briefing_date=day)
        pending_cursors: List[Tuple[Source, Dict[str, str]]] = []
        errors: List[str] = []

        try:
            for source in self.sources:
                try:
                    result = self._fetch_source(source)
                except Exception as exc:
                    logger.warning(
                        f"[BriefingPipeline] source {source.name} failed: {exc}"
                    )
                    errors.append(f"{source.name}: {exc}")
                    continue
                pending_cursors.append((source, result.cursors))
                rows = self._upsert_fetched(result.items)
                self.service.store.add_candidates(briefing.id, [row[0].id for row in rows])

            catalog_rows = self.service.store.list_candidates(briefing.id)
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
                    "error_message": str(exc),
                },
            )
            raise

    def _fetch_source(self, source: Source) -> FetchResult:
        cursors: Dict[str, str] = {}
        # Adapters may use several keys; we pass known values and ignore misses.
        for key in ("imap_uid", "imap_uidvalidity", "sync_token", "since"):
            row = self.service.get_cursor(source.name, source.account_id, key)
            if row is not None:
                cursors[key] = row.cursor_value
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
