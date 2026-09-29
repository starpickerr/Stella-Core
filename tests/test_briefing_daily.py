"""Daily continuity, immutable history, migration, and automatic generation."""
from datetime import datetime
from dataclasses import asdict
import sqlite3
import pytest

from agent.briefing.pipeline import BriefingPipeline
from agent.briefing.service import BriefingService
from agent.briefing.sources.base import FetchedItem
from agent.briefing.sources.static import StaticSource
from agent.briefing.store import BriefingStore, load_schema_sql
from agent.briefing.scheduler import BriefingScheduler


def dt(value):
    return datetime.fromisoformat(value)


@pytest.fixture
def service(tmp_path):
    return BriefingService(BriefingStore(tmp_path / "briefing.db"))


def item(key, time):
    return FetchedItem(source="email", source_id=key, sender="Ada", sender_email="ada@example.com", title=key, occurred_at=time)


def run(service, at, items=(), **kwargs):
    return BriefingPipeline(service, [StaticSource(items)], clock=lambda: dt(at)).run(**kwargs)


def test_daily_updates_and_next_day_continue_at_last_update(service):
    first = run(service, "2026-09-06T08:00:00+08:00", [item("morning", "2026-09-06T07:00:00+08:00")], operation="create")
    card = first["items"][0]
    service.update_item_status(card.id, "done")
    second = run(service, "2026-09-06T13:00:00+08:00", [item("noon", "2026-09-06T12:00:00+08:00")], operation="update")
    assert first["briefing"].id == second["briefing"].id
    assert second["briefing"].title == "2026年9月6日·简报"
    assert second["briefing"].window_start == first["briefing"].window_start
    assert second["briefing"].window_end == "2026-09-06T05:00:00Z"
    assert next(row for row in second["items"] if row.id == card.id).status == "done"
    historical = service.get_revision(first["briefing"].id, 1)
    assert historical["items"][0]["status"] == "undo"
    assert historical["briefing"]["body"] == first["briefing"].body
    third = run(service, "2026-09-07T08:00:00+08:00", [
        item("old", "2026-09-06T12:59:59+08:00"),
        item("boundary", "2026-09-06T13:00:00+08:00"),
        item("evening", "2026-09-06T20:00:00+08:00"),
        item("end", "2026-09-07T08:00:00+08:00"),
        item("future", "2026-09-07T08:00:01+08:00"),
    ])
    assert third["briefing"].window_start == second["briefing"].window_end
    assert {row.source_id for row in third["items"]} == {"evening", "end"}
    updated = run(service, "2026-09-07T09:00:00+08:00", operation="update")
    assert {row.source_id for row in updated["items"]} == {"evening", "end", "future"}
    assert len(service.list_briefings()) == 2


def test_duplicate_create_is_idempotent_and_missing_update_rejected(service):
    with pytest.raises(ValueError, match="before updating"):
        run(service, "2026-09-09T08:00:00+08:00", operation="update")
    first = run(service, "2026-09-09T07:00:00+08:00", operation="create")
    second = run(service, "2026-09-09T08:00:00+08:00", operation="create", trigger="scheduled")
    assert second == first
    assert len(second["revisions"]) == 1


def test_failed_update_keeps_successful_boundary_and_history(service):
    first = run(service, "2026-09-06T13:00:00+08:00")
    failed = BriefingPipeline(service, [StaticSource(error=RuntimeError("offline"))], clock=lambda: dt("2026-09-06T15:00:00+08:00")).run(operation="update")
    assert failed["briefing"].window_end == first["briefing"].window_end
    assert failed["revisions"][0]["status"] == "failed"
    next_day = run(service, "2026-09-07T08:00:00+08:00")
    assert next_day["briefing"].window_start == first["briefing"].window_end


def test_snapshot_archive_rolls_back_with_cards(service):
    first = run(service, "2026-09-09T08:00:00+08:00", [item("a", "2026-09-09T07:00:00+08:00")])
    with pytest.raises(sqlite3.IntegrityError):
        service.complete_briefing(first["briefing"].id, {"items": [asdict(first["items"][0])] * 2})
    assert service.get_briefing(first["briefing"].id) == first


def test_migration_preserves_previous_snapshot(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(load_schema_sql().split('-- Immutable generation')[0].replace("    window_start     TEXT,\n    window_end       TEXT,\n", ""))
    conn.execute("INSERT INTO briefings (id,kind,status,title,body,generated_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)", ("brf-2026-09-06-morning","morning","completed","9 月 6 日晨报","saved content","2026-09-06T05:00:00Z","2026-09-06T00:00:00Z","2026-09-06T05:00:00Z"))
    conn.commit(); conn.close()
    store = BriefingStore(path)
    old = store.get_briefing("brf-2026-09-06-morning")
    assert old.title == "2026年9月6日·简报"
    assert old.window_end == old.generated_at
    assert store.get_revision(old.id, 1)["briefing"]["body"] == "saved content"
    assert len(BriefingStore(path).list_revisions(old.id)) == 1


def test_scheduler_at_eight_catches_up_and_skips_existing(service):
    current = [dt("2026-09-09T07:59:59+08:00")]
    scheduler = BriefingScheduler(service, clock=lambda: current[0], configured=lambda: True,
        pipeline_factory=lambda: BriefingPipeline(service, [StaticSource([])], clock=lambda: current[0]))
    scheduler.tick()
    assert not service.list_briefings()
    current[0] = dt("2026-09-09T08:00:00+08:00")
    scheduler.tick(); scheduler.tick()
    assert len(service.list_briefings()) == 1
    assert service.get_briefing("brf-2026-09-09-morning")["revisions"][0]["trigger"] == "scheduled"
    current[0] = dt("2026-09-10T10:00:00+08:00")
    scheduler.tick()
    assert len(service.list_briefings()) == 2


def test_scheduler_retries_failure_and_waits_for_mailbox(service):
    current = [dt("2026-09-09T08:00:00+08:00")]
    configured = [False]
    sources = [StaticSource(error=RuntimeError("offline"))]
    scheduler = BriefingScheduler(service, clock=lambda: current[0], configured=lambda: configured[0],
        pipeline_factory=lambda: BriefingPipeline(service, sources, clock=lambda: current[0]))
    scheduler.tick()
    assert not service.list_briefings()
    configured[0] = True
    scheduler.tick()
    first = service.get_briefing("brf-2026-09-09-morning")
    assert first["briefing"].generated_at is None
    sources[0] = StaticSource([])
    current[0] = dt("2026-09-09T08:01:00+08:00")
    scheduler.tick()
    assert service.get_briefing(first["briefing"].id) == first
    current[0] = dt("2026-09-09T08:05:00+08:00")
    scheduler.tick()
    assert service.get_briefing(first["briefing"].id)["briefing"].status == "completed"
