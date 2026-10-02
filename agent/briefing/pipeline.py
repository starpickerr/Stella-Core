"""Daily run: fetch → catalog upsert → Agent decisions and draft → persist.

Cursors advance only after a non-failed briefing is saved. Source adapters
are injected; IMAP lives in sources.email.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from common.log import logger

from agent.briefing.generator import AgentBriefingGenerator, briefing_title
from agent.briefing.models import EmailMessage, SourceItem
from agent.briefing.service import BriefingService, briefing_id_for
from agent.briefing.sources.base import FetchResult, FetchedItem, Source
from agent.briefing.sources.registry import select_sources, source_key


def _now():
    return datetime.now().astimezone()


class BriefingPipeline:
    def __init__(
        self,
        service: Optional[BriefingService] = None,
        sources: Optional[Sequence[Source]] = None,
        clock=None,
        generator=None,
    ):
        self.service = service if service is not None else BriefingService()
        self.sources = list(sources or [])
        self.clock = clock or _now
        self.generator = generator if generator is not None else AgentBriefingGenerator()

    def run(
        self,
        kind: str = "morning",
        briefing_date: Optional[str] = None,
        operation: str = "upsert",
        trigger: str = "manual",
        sources=None,
    ) -> dict:
        selected = select_sources(self.sources, sources)
        if not selected:
            raise ValueError("no briefing sources configured")
        if operation not in {"create", "update", "upsert"}:
            raise ValueError("operation must be create or update")
        if trigger not in {"manual", "scheduled"}:
            raise ValueError("invalid briefing trigger")
        # Serialize shared-store runs so two requests cannot race the same cursor.
        with self.service.store.run_lock:
            day = briefing_date or self.clock().date().isoformat()
            existing = self.service.store.get_briefing(briefing_id_for(day, kind))
            if operation == "create" and existing and existing.generated_at:
                return self.service.get_briefing(existing.id)
            if operation == "update" and (not existing or not existing.generated_at):
                raise ValueError("generate this day's briefing before updating it")
            return self._run(kind, day, trigger, selected)

    def _run(self, kind: str, day: str, trigger: str, selected) -> dict:
        local_now = self.clock()
        end = local_now.astimezone(timezone.utc).replace(microsecond=0)
        existing = self.service.store.get_briefing(briefing_id_for(day, kind))
        previous = [row for row in self.service.list_briefings(kind=kind)
                    if row.id[4:14] < day and row.generated_at]
        boundary = max((row.window_end or row.generated_at for row in previous),
                       key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")), default=None)
        # A first briefing begins at 20:00 on the previous local calendar day.
        initial = datetime.combine(
            date.fromisoformat(day) - timedelta(days=1), datetime.min.time()
        ).replace(hour=20, tzinfo=local_now.tzinfo)
        default_start = initial.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        start = existing.window_start if existing and existing.window_start else boundary or default_start
        if existing and existing.window_start and not previous:
            # Correct the earlier 48-hour bootstrap on the next successful
            # update. Archived windows and classification history stay intact.
            for revision in reversed(self.service.store.list_revisions(existing.id)):
                old = self.service.store.get_revision(existing.id, revision["number"])["briefing"]
                if old.get("window_end") and old.get("window_start"):
                    old_start = datetime.fromisoformat(old["window_start"].replace("Z", "+00:00"))
                    old_end = datetime.fromisoformat(old["window_end"].replace("Z", "+00:00"))
                    if old_end - old_start == timedelta(days=2) and old["window_start"] == existing.window_start:
                        start = default_start
                    break
        finish = end.isoformat().replace("+00:00", "Z")
        if datetime.fromisoformat(start.replace("Z", "+00:00")) > end:
            raise ValueError("briefing end precedes the previous successful update")
        briefing = self.service.start_briefing(kind=kind, briefing_date=day)
        prior_detail = self.service.get_briefing(briefing.id)
        source_windows = {key: dict(value) for key, value in briefing.source_windows.items()}
        starts = {}
        for source in selected:
            key = source_key(source)
            prior = [row.source_windows[key]["end"] for row in previous
                     if row.source_windows.get(key, {}).get("end")]
            legacy = boundary if source.name == "email" and any(not row.source_windows for row in previous) else None
            current_legacy_start = start if briefing.window_start and source.name == "email" and not briefing.source_windows else None
            starts[key] = source_windows.get(key, {}).get("start") or current_legacy_start or max(prior, default=None) or legacy or default_start
        pending_cursors: List[Tuple[Source, Dict[str, str]]] = []
        errors: List[str] = []
        refreshed = []
        fully_refreshed = set()

        try:
            for source in selected:
                try:
                    result = self._fetch_source(source, starts[source_key(source)], finish)
                except Exception as exc:
                    label = getattr(source, "display_name", source.name)
                    logger.warning(
                        f"[BriefingPipeline] source {label} failed: {exc}"
                    )
                    errors.append(f"{label}: {exc}")
                    continue
                pending_cursors.append((source, result.cursors))
                self._upsert_fetched(result.items)
                refreshed.append(source)
                errors.extend(result.errors)
                if not result.errors:
                    fully_refreshed.add(source_key(source))
                    source_windows[source_key(source)] = {"source": source.name, "account_id": source.account_id,
                        "name": getattr(source, "display_name", source.name), "start": starts[source_key(source)], "end": finish}

            finish = self.clock().astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            catalog_rows = []
            for source in refreshed:
                key = source_key(source)
                catalog_rows.extend(self.service.store.window_candidates(starts[key], finish, [(source.name, source.account_id)]))
                if key in fully_refreshed:
                    source_windows[key]["end"] = finish
            refreshed_keys = {source_key(source) for source in refreshed}
            preserved_decisions = {}
            for snapshot in prior_detail.get("mail", []):
                key = snapshot["source"] + ":" + snapshot["account_id"]
                if key in refreshed_keys:
                    continue
                item, email = self._restore_candidate(snapshot)
                catalog_rows.append((item, email))
                decision = snapshot.get("decision") or self._legacy_decision(snapshot, prior_detail["items"])
                preserved_decisions[item.id] = decision
            windows = [window for window in source_windows.values() if window.get("end")]
            if windows:
                start = min(window["start"] for window in windows)
            fetched_count = len(catalog_rows)
            if errors and not pending_cursors:
                status = "failed"
            elif errors:
                status = "partial"
            else:
                status = "completed"

            drafted, mail = {}, []
            if status != "failed":
                drafted = self.generator.generate(catalog_rows, self.service.list_rules(enabled_only=True),
                    briefing_date=day, kind=kind, window_start=start, window_end=finish,
                    preserved_decisions=preserved_decisions)
                mail = drafted["mail"]
            filtered_count = sum(row["category"] == "filtered" for row in mail)

            detail = self.service.complete_briefing(
                briefing.id,
                {
                    "status": status,
                    "run_at": finish,
                    "window_start": start,
                    "window_end": finish,
                    "trigger": trigger,
                    "title": (briefing.title or briefing_title(day, kind)) if status == "failed" else drafted["title"],
                    "body": drafted["body"] if status != "failed" else briefing.body,
                    "fetched_count": fetched_count if status != "failed" else briefing.fetched_count,
                    "kept_count": len(mail) - filtered_count if status != "failed" else briefing.kept_count,
                    "filtered_count": filtered_count if status != "failed" else briefing.filtered_count,
                    "error_message": "; ".join(errors),
                    "cursor_updates": [
                        (source.name, source.account_id, key, value)
                        for source, cursors in pending_cursors
                        if source_key(source) in fully_refreshed
                        for key, value in cursors.items()
                    ],
                    **({"items": drafted["items"], "mail": mail, "rule_text": drafted.get("rule_text", ""),
                        "source_windows": source_windows, "updated_sources": [source_key(source) for source in refreshed]} if status != "failed" else {}),
                },
            )
            if status != "failed":
                from agent.briefing.outbox import dispatch_pending
                dispatch_pending(self.service.store)
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

    @staticmethod
    def _restore_candidate(snapshot):
        payload = dict(snapshot.get("metadata", {}))
        if snapshot.get("body_available"):
            payload["body"] = snapshot.get("body", "")
        item = SourceItem(**{key: snapshot.get(key, "") for key in (
            "id", "source", "account_id", "source_id", "thread_id", "sender", "title", "snippet", "occurred_at", "url")},
            payload=payload)
        email = EmailMessage(item.id, snapshot.get("sender_email", ""), snapshot.get("list_id", "")) if item.source == "email" else None
        return item, email

    @staticmethod
    def _legacy_decision(snapshot, cards):
        card = next((card for card in cards if card.source_item_id == snapshot["id"]), None)
        return {"id": snapshot["id"], "selected": snapshot["category"] == "selected",
                "reason": snapshot.get("filter_reason") or "保留上次筛选结果",
                "section": card.section if card else "fyi", "score": card.score if card else 50,
                "summary": card.snippet if card else snapshot.get("snippet") or snapshot["title"]}

    def _fetch_source(self, source: Source, start: str, end: str) -> FetchResult:
        cursors: Dict[str, str] = {}
        # Adapters may use several keys; we pass known values and ignore misses.
        for key in ("imap_uid", "imap_uidvalidity", "sync_token", "since", "elearning_state"):
            row = self.service.get_cursor(source.name, source.account_id, key)
            if row is not None:
                cursors[key] = row.cursor_value
        cursors.update({"since": start, "until": end})
        if source.name == "email":
            old_rows = self.service.store.window_candidates(start, end, [(source.name, source.account_id)])
            if any("body" not in row[0].payload for row in old_rows):
                cursors["refresh_existing_content"] = "1"
        return source.fetch(cursors)

    def _upsert_fetched(
        self, items: Iterable[FetchedItem]
    ) -> List[Tuple[SourceItem, Optional[EmailMessage]]]:
        rows = []
        for fetched in items:
            rows.append(self.service.upsert_source_item(fetched.to_catalog_payload()))
        return rows
