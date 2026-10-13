"""Selective updates, independent source windows and source discovery."""
from datetime import datetime
import sqlite3

import pytest

from agent.briefing.pipeline import BriefingPipeline
from agent.briefing.service import BriefingService
from agent.briefing.sources.base import FetchedItem, FetchResult
from agent.briefing.sources.registry import select_sources, public_sources
from briefing_fakes import StaticSource
from agent.briefing.store import BriefingStore, load_schema_sql
from agent.tools.briefing.briefing_tool import BriefingTool


class TrackedSource(StaticSource):
    def __init__(self, name, account_id, items=()):
        super().__init__(list(items), name=name, account_id=account_id, cursors={"since": "saved"})
        self.calls = []

    def fetch(self, cursors):
        self.calls.append(dict(cursors))
        return super().fetch(cursors)


def item(source, account, key, at):
    return FetchedItem(source=source, account_id=account, source_id=key, title=key,
                       occurred_at=at, payload={"body": key + " 正文"})


@pytest.fixture
def service(tmp_path):
    return BriefingService(BriefingStore(tmp_path / "briefing.db"))


def test_partial_update_keeps_other_sources_and_independent_next_day_boundary(service, deterministic_briefing_generator):
    email = TrackedSource("email", "a", [item("email", "a", "邮件", "2026-09-08T23:00:00Z")])
    canvas = TrackedSource("elearning", "b", [item("elearning", "b", "课程公告", "2026-09-08T23:00:00Z")])
    now = [datetime.fromisoformat("2026-09-09T08:00:00+08:00")]
    pipeline = BriefingPipeline(service, [email, canvas], clock=lambda: now[0])
    first = pipeline.run()
    cursor_before = service.get_cursor("elearning", "b", "since")
    course_card = next(card for card in first["items"] if card.source == "elearning")
    service.update_item_status(course_card.id, "done")
    email._items.append(item("email", "a", "下午邮件", "2026-09-09T06:00:00Z"))
    now[0] = datetime.fromisoformat("2026-09-09T15:00:00+08:00")
    partial = pipeline.run(operation="update", sources=["email:a"])
    assert len(email.calls) == 2 and len(canvas.calls) == 1
    assert len(partial["mail"]) == 3
    assert next(card for card in partial["items"] if card.id == course_card.id).status == "done"
    assert partial["briefing"].source_windows["elearning:b"]["end"] == "2026-09-09T00:00:00Z"
    assert partial["briefing"].source_windows["email:a"]["end"] == "2026-09-09T07:00:00Z"
    assert partial["briefing"].updated_sources == ["email:a"]
    assert service.get_cursor("elearning", "b", "since") == cursor_before
    # New day email-only generation does not advance eLearning's last boundary.
    now[0] = datetime.fromisoformat("2026-09-10T08:00:00+08:00")
    pipeline.run(operation="create", sources=["email"])
    canvas._items.append(item("elearning", "b", "未同步的公告", "2026-09-09T02:00:00Z"))
    now[0] = datetime.fromisoformat("2026-09-10T15:00:00+08:00")
    last = pipeline.run(operation="update", sources=["elearning"])
    assert canvas.calls[-1]["since"] == "2026-09-09T00:00:00Z"
    assert last["briefing"].source_windows["elearning:b"]["start"] == "2026-09-09T00:00:00Z"
    assert "未同步的公告" in {row["title"] for row in last["mail"]}
    assert len(service.get_revision(first["briefing"].id, 1)["mail"]) == 2


def test_account_selection_never_fetches_other_mailbox(service, deterministic_briefing_generator):
    first = TrackedSource("email", "a")
    second = TrackedSource("email", "b")
    pipeline = BriefingPipeline(service, [first, second])
    pipeline.run(sources=["email:b"])
    assert first.calls == [] and len(second.calls) == 1


@pytest.mark.parametrize("selection", [[], "email", ["missing"], ["all", "email"], [1]])
def test_invalid_selection_has_no_side_effects(service, selection):
    source = TrackedSource("email", "a")
    with pytest.raises(ValueError):
        BriefingPipeline(service, [source]).run(sources=selection)
    assert source.calls == [] and service.list_briefings() == []


def test_all_and_group_selection_and_source_registry(monkeypatch):
    available = [TrackedSource("email", "a"), TrackedSource("email", "b"), TrackedSource("elearning", "c")]
    assert select_sources(available) == available
    assert select_sources(available, ["all"]) == available
    assert select_sources(available, ["email"]) == available[:2]
    monkeypatch.setattr("agent.briefing.sources.registry.configured_sources", lambda: available)
    assert [row["id"] for row in public_sources()] == ["email:a", "email:b", "elearning:c"]
    result = BriefingTool().execute({"action": "sources"})
    assert result.status == "success" and "elearning:c" in result.result


def test_failed_selected_source_preserves_other_source_and_does_not_advance(service, deterministic_briefing_generator):
    email = TrackedSource("email", "a", [item("email", "a", "邮件", "2026-09-08T23:00:00Z")])
    canvas = TrackedSource("elearning", "b", [item("elearning", "b", "课程", "2026-09-08T23:00:00Z")])
    def at():
        return datetime.fromisoformat("2026-09-09T08:00:00+08:00")
    pipeline = BriefingPipeline(service, [email, canvas], clock=at)
    first = pipeline.run()
    canvas._error = RuntimeError("offline")
    failed = pipeline.run(operation="update", sources=["elearning"])
    assert failed["briefing"].status == "failed"
    assert failed["briefing"].source_windows == first["briefing"].source_windows
    assert failed["mail"] == first["mail"] and failed["items"] == first["items"]
    assert len(email.calls) == 1


def test_partial_source_read_does_not_advance_its_boundary(service, deterministic_briefing_generator):
    email = TrackedSource("email", "a")
    canvas = TrackedSource("elearning", "b")
    canvas.fetch = lambda cursors: FetchResult([], {}, ["课程文件暂不可访问"])
    result = BriefingPipeline(service, [email, canvas]).run()
    assert result["briefing"].status == "partial"
    assert "email:a" in result["briefing"].source_windows
    assert "elearning:b" not in result["briefing"].source_windows


def test_old_database_gains_source_windows_without_changing_old_revision(tmp_path):
    path = tmp_path / "old.db"
    sql = load_schema_sql().replace("    source_windows   TEXT    NOT NULL DEFAULT '{}',\n", "").replace("    updated_sources  TEXT    NOT NULL DEFAULT '[]',\n", "")
    conn = sqlite3.connect(path)
    conn.executescript(sql)
    conn.execute("ALTER TABLE briefings ADD COLUMN kind TEXT NOT NULL DEFAULT 'morning'")
    conn.execute("INSERT INTO briefings (id,kind,status,title,body,generated_at,created_at,updated_at,window_start,window_end) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("brf-2026-09-09-morning", "morning", "completed", "简报", "旧正文", "2026-09-09T00:00:00Z",
         "2026-09-09T00:00:00Z", "2026-09-09T00:00:00Z", "2026-09-08T12:00:00Z", "2026-09-09T00:00:00Z"))
    conn.commit()
    conn.close()
    service = BriefingService(BriefingStore(path))
    detail = service.get_briefing("brf-2026-09-09-morning")
    assert detail["briefing"].source_windows == {} and detail["briefing"].updated_sources == []
    assert service.get_revision(detail["briefing"].id, 1)["briefing"]["body"] == "旧正文"
