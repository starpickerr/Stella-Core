"""Host orchestrator: fetch sources, draft with the model, persist via plugin.

Credentials stay in source plugins. Snapshot/cursor/outbox writes go through
``run_pipeline`` on the Briefing owner. Core keeps fetch timing, progress, and
Agent drafting (Model Service boundary) only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from contextlib import contextmanager
from typing import Dict, List, Optional, Sequence, Tuple
import time
import threading

from common.log import logger
from agent.protocol.cancel import AgentCancelledError

from agent.briefing.generator import AgentBriefingGenerator
from agent.briefing import progress as briefing_progress
from agent.briefing.models import EmailMessage, SourceItem
from core.services.briefing_public import default_service
from agent.briefing.sources.base import FetchResult, Source
from agent.briefing.sources.registry import select_sources, source_key


def _now():
    return datetime.now().astimezone()


@contextmanager
def _stage_heartbeat(day: str, stage: str):
    stopped = threading.Event()
    started = time.monotonic()

    def report():
        while not stopped.wait(30):
            logger.info("[BriefingPipeline] still running date=%s stage=%s elapsed=%.0fs",
                        day, stage, time.monotonic() - started)

    worker = threading.Thread(target=report, name="briefing-progress", daemon=True)
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join(timeout=1)


class BriefingPipeline:
    def __init__(
        self,
        service=None,
        sources: Optional[Sequence[Source]] = None,
        clock=None,
        generator=None,
        cancel_event=None,
    ):
        self.service = service if service is not None else default_service()
        self.sources = list(sources or [])
        self.clock = clock or _now
        self.generator = generator if generator is not None else AgentBriefingGenerator()
        self.cancel_event = cancel_event

    def _check_cancelled(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise AgentCancelledError("briefing cancelled by user")

    def run(
        self,
        briefing_date: Optional[str] = None,
        operation: str = "upsert",
        trigger: str = "manual",
        sources=None,
    ) -> dict:
        self._check_cancelled()
        selected = select_sources(self.sources, sources)
        if not selected:
            raise ValueError("no briefing sources configured")
        if operation not in {"create", "update", "upsert"}:
            raise ValueError("operation must be create or update")
        if trigger not in {"manual", "scheduled"}:
            raise ValueError("invalid briefing trigger")
        # A second request must report the active run instead of waiting behind
        # an unbounded source or model call with no response to its caller.
        if not self.service.store.run_lock.acquire(blocking=False):
            raise ValueError("简报正在生成，请等待当前运行完成后刷新")
        try:
            day = briefing_date or self.clock().date().isoformat()
            existing = self.service.briefing_for_date(day)
            if operation == "create" and existing and existing.generated_at:
                return self.service.get_briefing(existing.id)
            if operation == "update" and (not existing or not existing.generated_at):
                raise ValueError("generate this day's briefing before updating it")
            return self._run(day, trigger, selected, existing)
        finally:
            self.service.store.run_lock.release()

    def _run(self, day: str, trigger: str, selected, existing) -> dict:
        local_now = self.clock()
        end = local_now.astimezone(timezone.utc).replace(microsecond=0)
        previous = [row for row in self.service.list_briefings()
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

        briefing = self.service.start_briefing(briefing_date=day)
        run_started = time.monotonic()
        logger.info("[BriefingPipeline] started date=%s trigger=%s sources=%d", day, trigger, len(selected))
        prior_detail = self.service.get_briefing(briefing.id) or {"mail": [], "items": []}
        source_windows = {key: dict(value) for key, value in briefing.source_windows.items()}
        starts = {}
        for source in selected:
            key = source_key(source)
            prior = [row.source_windows[key]["end"] for row in previous
                     if row.source_windows.get(key, {}).get("end")]
            legacy = boundary if source.name == "email" and any(not row.source_windows for row in previous) else None
            current_legacy_start = (
                start if briefing.window_start and source.name == "email" and not briefing.source_windows
                else None)
            starts[key] = (
                source_windows.get(key, {}).get("start") or current_legacy_start
                or max(prior, default=None) or legacy or default_start)

        progress_id = briefing.id
        payload: List[dict] = []
        fetched_rows: List[Tuple] = []
        refreshed_accounts: List[Tuple[str, str, str]] = []  # source, account, start
        fully_refreshed = set()
        pending_ok = False
        errors: List[str] = []
        completed_sources = 0

        try:
            rules = self.service.list_rules(enabled_only=True)
            briefing_progress.begin(progress_id, len(selected))
            for source in selected:
                self._check_cancelled()
                key = source_key(source)
                label = getattr(source, "display_name", source.name)
                source_started = time.monotonic()
                logger.info("[BriefingPipeline] fetching date=%s source=%s", day, source.name)
                entry = {
                    "source": source.name,
                    "account_id": source.account_id,
                    "name": label,
                    "window_start": starts[key],
                    "items": [],
                }
                try:
                    with _stage_heartbeat(day, f"fetch:{source.name}"):
                        result = self._fetch_source(source, starts[key], finish)
                    self._check_cancelled()
                except AgentCancelledError:
                    raise
                except Exception as exc:
                    logger.warning("[BriefingPipeline] source %s failed: %s", label, exc)
                    errors.append(f"{label}: {exc}")
                    entry["errors"] = [str(exc)]
                    # No ``cursors`` key: distinguishes hard fetch failure from a partial FetchResult.
                    payload.append(entry)
                    completed_sources += 1
                    briefing_progress.update(progress_id, completed_sources=completed_sources)
                    continue
                pending_ok = True
                entry["cursors"] = dict(result.cursors)
                if result.errors:
                    errors.extend(result.errors)
                    entry["errors"] = list(result.errors)
                else:
                    fully_refreshed.add(key)
                # Resolve catalog ids before drafting so run_pipeline staging reuses them.
                for fetched in result.items:
                    row = self.service.build_source_item(fetched.to_catalog_payload())
                    item, _email = row
                    entry["items"].append({**fetched.to_catalog_payload(), "id": item.id})
                    fetched_rows.append(row)
                refreshed_accounts.append((source.name, source.account_id, starts[key]))
                logger.info(
                    "[BriefingPipeline] fetched date=%s source=%s items=%d errors=%d elapsed=%.1fs",
                    day, source.name, len(result.items), len(result.errors),
                    time.monotonic() - source_started)
                payload.append(entry)
                completed_sources += 1
                briefing_progress.update(progress_id, completed_sources=completed_sources)

            briefing_progress.update(progress_id, stage="finalizing")
            finish = self.clock().astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            catalog_rows = self._window_catalog(refreshed_accounts, fetched_rows, finish)
            catalog_keys = {(item.source, item.account_id, item.source_id) for item, _email in catalog_rows}
            preserved_decisions = {}
            for snapshot in prior_detail.get("mail", []):
                key = snapshot["source"] + ":" + snapshot["account_id"]
                occurred = datetime.fromisoformat(snapshot["occurred_at"].replace("Z", "+00:00"))
                lower = (
                    datetime.fromisoformat(starts[key].replace("Z", "+00:00"))
                    if key in fully_refreshed else None)
                if key in fully_refreshed and occurred > lower:
                    continue
                item, email = self._restore_candidate(snapshot)
                item_key = (item.source, item.account_id, item.source_id)
                if item_key not in catalog_keys:
                    catalog_rows.append((item, email))
                    catalog_keys.add(item_key)
                decision = snapshot.get("decision") or self._legacy_decision(snapshot, prior_detail.get("items") or [])
                preserved_decisions[item.id] = decision
            windows = [starts[key] for key in fully_refreshed]
            if windows:
                start = min(windows)
            if errors and not pending_ok:
                status = "failed"
            elif errors:
                status = "partial"
            else:
                status = "completed"

            draft = None
            if status != "failed":
                self._check_cancelled()
                logger.info("[BriefingPipeline] drafting date=%s candidates=%d", day, len(catalog_rows))
                progress = getattr(self.generator, "progress", None)
                if hasattr(self.generator, "progress"):
                    def report(stage):
                        logger.info("[BriefingPipeline] date=%s %s", day, stage)
                        if progress:
                            progress(stage)
                    self.generator.progress = report
                try:
                    with _stage_heartbeat(day, "draft"):
                        draft = self.generator.generate(
                            catalog_rows, rules, briefing_date=day,
                            window_start=start, window_end=finish,
                            preserved_decisions=preserved_decisions)
                finally:
                    if hasattr(self.generator, "progress"):
                        self.generator.progress = progress
                self._check_cancelled()

            detail = self.service.run_pipeline(
                briefing_date=day, operation="upsert", trigger=trigger,
                sources=payload, draft=draft, run_at=finish,
                acquire_lock=not self.service.store.run_lock.locked())
            briefing = detail["briefing"] if isinstance(detail, dict) else detail
            status_name = getattr(briefing, "status", None) or (briefing or {}).get("status")
            if status_name and status_name != "failed":
                self.service.store.dispatch_outbox()
            logger.info("[BriefingPipeline] finished date=%s status=%s elapsed=%.1fs",
                        day, status_name, time.monotonic() - run_started)
            return detail
        except Exception as exc:
            logger.error("[BriefingPipeline] run failed: %s", exc)
            if not isinstance(exc, AgentCancelledError):
                try:
                    # Force a failed snapshot without promoting fetched items or cursors.
                    self.service.run_pipeline(
                        briefing_date=day, operation="upsert", trigger=trigger,
                        sources=[{
                            "source": "pipeline", "account_id": "default", "name": "简报",
                            "items": [], "errors": [str(exc)],
                        }],
                        draft=None, run_at=finish,
                        acquire_lock=not self.service.store.run_lock.locked())
                except Exception:
                    logger.exception("[BriefingPipeline] failed to persist error briefing")
            raise
        finally:
            briefing_progress.finish(progress_id)

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
        card = next((card for card in cards if getattr(card, "source_item_id", None) == snapshot["id"]
                     or (isinstance(card, dict) and card.get("source_item_id") == snapshot["id"])), None)
        section = getattr(card, "section", None) if card and not isinstance(card, dict) else (card or {}).get("section", "fyi")
        score = getattr(card, "score", None) if card and not isinstance(card, dict) else (card or {}).get("score", 50)
        snippet = getattr(card, "snippet", None) if card and not isinstance(card, dict) else (card or {}).get("snippet")
        return {"id": snapshot["id"], "selected": snapshot["category"] == "selected",
                "reason": snapshot.get("filter_reason") or "保留上次筛选结果",
                "section": section or "fyi", "score": score if score is not None else 50,
                "summary": snippet if snippet is not None else snapshot.get("snippet") or snapshot["title"]}

    def _window_catalog(self, refreshed_accounts, fetched_rows, finish: str):
        """Mirror plugin staged_window_candidates without a host staging round-trip."""
        by_account: Dict[Tuple[str, str], List[Tuple]] = {}
        for item, email in fetched_rows:
            by_account.setdefault((item.source, item.account_id), []).append((item, email))
        catalog: Dict[Tuple[str, str, str], Tuple] = {}
        for name, account, src_start in refreshed_accounts:
            for item, email in self.service.store.window_candidates(
                    src_start, finish, [(name, account)]):
                catalog[(item.source, item.account_id, item.source_id)] = (item, email)
            start_at = datetime.fromisoformat(src_start.replace("Z", "+00:00"))
            end_at = datetime.fromisoformat(finish.replace("Z", "+00:00"))
            for item, email in by_account.get((name, account), []):
                key = (item.source, item.account_id, item.source_id)
                catalog.pop(key, None)
                occurred = datetime.fromisoformat(item.occurred_at.replace("Z", "+00:00"))
                if occurred > end_at:
                    continue
                if occurred <= start_at:
                    previous = self.service.store.get_source_item_by_key(
                        item.source, item.account_id, item.source_id)
                    if previous:
                        prior, _prior_email = previous
                        keys = ("due_at", "start_at", "end_at", "submission_status",
                                "score", "grade", "workflow_state")
                        if prior.title == item.title and all(
                                prior.payload.get(field) == item.payload.get(field) for field in keys):
                            continue
                catalog[key] = (item, email)
        return sorted(catalog.values(), key=lambda row: (
            datetime.fromisoformat(row[0].occurred_at.replace("Z", "+00:00")), row[0].id))

    def _fetch_source(self, source: Source, start: str, end: str) -> FetchResult:
        self._check_cancelled()
        if hasattr(source, "cancel_event"):
            source.cancel_event = self.cancel_event
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
        from core.plugins.caller import consumer_plugin_scope
        from core.security.source_collection import briefing_source_collection
        with consumer_plugin_scope("stella.briefing"), briefing_source_collection():
            return source.fetch(cursors)
