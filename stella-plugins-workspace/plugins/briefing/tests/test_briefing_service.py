import pytest

from stella_briefing_domain.service import BriefingService, briefing_id_for
from stella_briefing_domain.store import BriefingStore


def _service(tmp_path) -> BriefingService:
    return BriefingService(BriefingStore(tmp_path / "briefing.db"))


def _mail(**extra):
    payload = {
        "source": "email",
        "source_id": "<msg-1@example.com>",
        "sender": "Ada",
        "sender_email": "ada@example.com",
        "title": "Need review",
        "snippet": "Please review the doc",
        "occurred_at": "2026-09-08T22:00:00Z",
    }
    payload.update(extra)
    return payload


def test_start_and_complete_briefing_copies_catalog_envelope(tmp_path):
    svc = _service(tmp_path)
    started = svc.start_briefing(briefing_date="2026-09-09")
    assert started.id == "brf-2026-09-09"
    assert started.status == "running"
    assert started.generated_at is None

    item, email = svc.upsert_source_item(_mail())
    assert email is not None
    assert email.sender_email == "ada@example.com"

    detail = svc.complete_briefing(
        started.id,
        {
            "status": "completed",
            "title": "9 月 9 日晨报",
            "body": "今日 1 件需处理。",
            "fetched_count": 4,
            "kept_count": 1,
            "filtered_count": 3,
            "items": [
                {
                    "source_item_id": item.id,
                    "section": "action",
                    "score": 80,
                }
            ],
        },
    )
    briefing = detail["briefing"]
    assert briefing.status == "completed"
    assert briefing.created_at == started.created_at
    assert briefing.generated_at is not None
    assert len(detail["items"]) == 1
    card = detail["items"][0]
    assert card.title == "Need review"
    assert card.sender == "Ada"
    assert card.section == "action"
    assert card.source_item_id == item.id


def test_rerun_keeps_created_at(tmp_path):
    svc = _service(tmp_path)
    first = svc.start_briefing(briefing_date="2026-09-09")
    svc.complete_briefing(first.id, {"status": "completed", "body": "v1", "items": []})
    second = svc.start_briefing(briefing_date="2026-09-09")
    assert second.id == first.id
    assert second.status == "running"
    assert second.created_at == first.created_at
    assert second.body == "v1"


def test_outbox_keeps_each_revision_and_independent_acks(tmp_path):
    svc = _service(tmp_path)
    first = svc.start_briefing(briefing_date="2026-09-09")
    svc.complete_briefing(first.id, {"status": "completed", "body": "v1", "items": [],
                                     "cursor_updates": [("email", "default", "uid", "1")]})
    svc.start_briefing(briefing_date="2026-09-09")
    svc.complete_briefing(first.id, {"status": "completed", "body": "v2", "items": [],
                                     "cursor_updates": [("email", "default", "uid", "2")]})
    events = svc.store.pending_projection_events()
    assert [row["revision"] for row in events] == [1, 2]
    assert '"body":"v1"' in events[0]["snapshot"]
    assert '"body":"v2"' in events[1]["snapshot"]
    assert svc.get_cursor("email", "default", "uid").cursor_value == "2"
    svc.store.ack_projection(first.id, 1, "calendar")
    pending = svc.store.pending_projection_events()
    assert pending[0]["calendar_ack_at"] is not None
    assert pending[0]["todo_ack_at"] is None


def test_update_item_status_and_list(tmp_path):
    svc = _service(tmp_path)
    started = svc.start_briefing(briefing_date="2026-09-09")
    item, _ = svc.upsert_source_item(_mail())
    detail = svc.complete_briefing(
        started.id,
        {
            "items": [{"source_item_id": item.id, "section": "fyi", "score": 10}],
        },
    )
    card = svc.update_item_status(detail["items"][0].id, "done")
    assert card.status == "done"
    listed = svc.list_briefings(status="completed")
    assert [row.id for row in listed] == [started.id]


def test_rules_and_cursors(tmp_path):
    svc = _service(tmp_path)
    rule = svc.create_rule(
        {
            "action": "exclude",
            "match_field": "sender_domain",
            "match_value": "spam.example",
        }
    )
    assert rule.enabled is True
    with pytest.raises(ValueError, match="same match"):
        svc.create_rule(
            {
                "action": "exclude",
                "match_field": "sender_domain",
                "match_value": "spam.example",
            }
        )
    updated = svc.update_rule(rule.id, {"enabled": False, "note": "off"})
    assert updated.enabled is False
    assert svc.list_rules(enabled_only=True) == []
    svc.delete_rule(rule.id)
    with pytest.raises(KeyError):
        svc.delete_rule(rule.id)

    cursor = svc.set_cursor("email", "imap_uid", "42")
    assert cursor.cursor_value == "42"
    assert svc.get_cursor("email", "default", "imap_uid").cursor_value == "42"


def test_validation_rejects_bad_payloads(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(ValueError, match="date"):
        briefing_id_for("09-09")
    with pytest.raises(ValueError, match="source_id"):
        svc.upsert_source_item({"source": "email", "occurred_at": "2026-09-08T22:00:00Z"})
    with pytest.raises(KeyError):
        svc.complete_briefing("missing", {"status": "completed"})
    with pytest.raises(KeyError):
        svc.update_item_status("missing", "done")
    with pytest.raises(ValueError, match="status"):
        started = svc.start_briefing(briefing_date="2026-09-09")
        svc.update_item_status(started.id, "open")
    with pytest.raises(ValueError, match="match_value"):
        svc.create_rule({"action": "exclude", "match_field": "title", "match_value": "  "})


def test_invalid_snapshot_does_not_write_document(tmp_path):
    svc = _service(tmp_path)
    started = svc.start_briefing(briefing_date="2026-09-09")
    with pytest.raises(ValueError):
        svc.complete_briefing(started.id, {"body": "should not save", "items": [{}]})
    assert svc.get_briefing(started.id)["briefing"] == started


def test_duplicate_cards_roll_back_document_and_snapshot(tmp_path):
    import sqlite3
    svc = _service(tmp_path)
    started = svc.start_briefing(briefing_date="2026-09-09")
    item, _ = svc.upsert_source_item(_mail())
    first = svc.complete_briefing(started.id, {"body": "first", "items": [{"source_item_id": item.id}]})
    with pytest.raises(sqlite3.IntegrityError):
        svc.complete_briefing(started.id, {"body": "second", "items": [{"source_item_id": item.id}] * 2})
    assert svc.get_briefing(started.id) == first
