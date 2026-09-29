"""Daily continuity, immutable history, migration, and automatic generation."""
from datetime import datetime
from dataclasses import asdict
import sqlite3
import pytest

pytestmark = pytest.mark.usefixtures("deterministic_briefing_generator")

from agent.briefing.pipeline import BriefingPipeline
from agent.briefing.service import BriefingService
from agent.briefing.sources.base import FetchedItem
from agent.briefing.sources.static import StaticSource
from agent.briefing.store import BriefingStore, load_schema_sql


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


def test_night_window_extends_in_same_day_and_restarts_at_last_update(service):
    first = run(service, "2026-09-07T08:00:00+08:00", [
        item("before", "2026-09-06T19:59:59+08:00"),
        item("boundary", "2026-09-06T20:00:00+08:00"),
        item("night", "2026-09-06T20:00:01+08:00"),
    ])
    assert first["briefing"].window_start == "2026-09-06T12:00:00Z"
    assert {row["source_id"] for row in first["mail"]} == {"night"}
    afternoon = run(service, "2026-09-07T15:00:00+08:00", operation="update")
    assert afternoon["briefing"].window_start == first["briefing"].window_start
    assert afternoon["briefing"].window_end == "2026-09-07T07:00:00Z"
    evening = run(service, "2026-09-07T20:00:00+08:00", operation="update")
    next_day = run(service, "2026-09-08T08:00:00+08:00", [
        item("late", "2026-09-07T20:00:01+08:00"),
    ])
    assert next_day["briefing"].window_start == evening["briefing"].window_end == "2026-09-07T12:00:00Z"
    assert next_day["briefing"].window_end == "2026-09-08T00:00:00Z"
    assert {row["source_id"] for row in next_day["mail"]} == {"late"}


def test_window_end_records_fetch_completion(service):
    times = iter([dt("2026-09-07T08:00:00+08:00"), dt("2026-09-07T08:00:00+08:00"), dt("2026-09-07T08:00:30+08:00")])
    detail = BriefingPipeline(service, [StaticSource([
        item("during-fetch", "2026-09-07T08:00:10+08:00"),
    ])], clock=lambda: next(times)).run()
    assert detail["briefing"].window_end == detail["briefing"].generated_at == "2026-09-07T00:00:30Z"
    assert len(detail["mail"]) == 1


def test_legacy_two_day_bootstrap_is_corrected_without_rewriting_history(service):
    from agent.briefing.rules import fetched_to_payload
    old = service.start_briefing(briefing_date="2026-09-07")
    catalog, _ = service.upsert_source_item(fetched_to_payload(item("too-old", "2026-09-05T09:00:00+08:00")))
    service.store.add_candidates(old.id, [catalog.id])
    service.complete_briefing(old.id, {
        "run_at": "2026-09-07T00:00:00Z", "window_start": "2026-09-05T00:00:00Z",
        "window_end": "2026-09-07T00:00:00Z", "body": "old content",
    })
    detail = run(service, "2026-09-07T15:00:00+08:00", operation="update")
    assert detail["briefing"].window_start == "2026-09-06T12:00:00Z"
    assert detail["mail"] == []
    assert service.store.list_candidates(old.id) == []
    historical = service.get_revision(old.id, 1)
    assert historical["briefing"]["window_start"] == "2026-09-05T00:00:00Z"
    assert historical["briefing"]["body"] == "old content"
    assert historical["briefing"]["mail_snapshot_available"] is False


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


def test_snapshot_archive_rolls_back_with_duplicate_mail(service):
    first = run(service, "2026-09-09T08:00:00+08:00", [item("a", "2026-09-09T07:00:00+08:00")])
    changed = {**first["mail"][0], "category": "filtered", "body": "changed"}
    with pytest.raises(sqlite3.IntegrityError):
        service.complete_briefing(first["briefing"].id, {"body": "changed", "mail": [changed, changed]})
    assert service.get_briefing(first["briefing"].id) == first


def test_migration_preserves_previous_snapshot(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(load_schema_sql().split('-- Immutable generation')[0]
        .replace("    window_start     TEXT,\n    window_end       TEXT,\n", "")
        .replace("    mail_snapshot_available INTEGER NOT NULL DEFAULT 0,\n", ""))
    conn.execute("INSERT INTO briefings (id,kind,status,title,body,generated_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)", ("brf-2026-09-06-morning","morning","completed","9 月 6 日晨报","saved content","2026-09-06T05:00:00Z","2026-09-06T00:00:00Z","2026-09-06T05:00:00Z"))
    conn.commit(); conn.close()
    store = BriefingStore(path)
    old = store.get_briefing("brf-2026-09-06-morning")
    assert old.title == "2026年9月6日·简报"
    assert old.window_end == old.generated_at
    assert old.mail_snapshot_available is False
    assert store.get_revision(old.id, 1)["briefing"]["body"] == "saved content"
    assert len(BriefingStore(path).list_revisions(old.id)) == 1
