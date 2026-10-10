from datetime import datetime, timezone
import threading
import pytest

from agent.briefing.pipeline import BriefingPipeline
from agent.briefing import progress as briefing_progress
from agent.briefing.generator import AgentBriefingGenerator
from agent.briefing.service import BriefingService
from agent.briefing.sources.base import FetchResult, FetchedItem
from briefing_fakes import StaticSource
from briefing_fakes import DeterministicBriefingModel
from agent.briefing.store import BriefingStore

pytestmark = pytest.mark.usefixtures("deterministic_briefing_generator")


@pytest.fixture(autouse=True)
def fixed_briefing_clock(monkeypatch):
    monkeypatch.setattr(
        "agent.briefing.pipeline._now",
        lambda: datetime(2026, 9, 9, 8, tzinfo=timezone.utc),
    )


def _svc(tmp_path) -> BriefingService:
    return BriefingService(BriefingStore(tmp_path / "briefing.db"))


def test_concurrent_run_reports_active_briefing_instead_of_waiting(tmp_path):
    service = _svc(tmp_path)
    source = StaticSource([])
    assert service.store.run_lock.acquire(blocking=False)
    try:
        with pytest.raises(ValueError, match="正在生成"):
            BriefingPipeline(service, [source]).run(briefing_date="2026-09-09")
    finally:
        service.store.run_lock.release()


def test_generation_starts_once_after_every_source_finishes(tmp_path):
    service = _svc(tmp_path)
    metadata_started = threading.Event()
    release_metadata = threading.Event()
    sync_started = threading.Event()
    release_sync = threading.Event()

    class RecordingModel(DeterministicBriefingModel):
        def __init__(self):
            self.classification_calls = 0

        def call_stream(self, request):
            if any('"candidates"' in part.get("text", "") for part in request.messages[-1]["content"]):
                self.classification_calls += 1
            yield from super().call_stream(request)

    model = RecordingModel()

    class SlowElearningSource:
        name = "elearning"
        account_id = "school"
        on_items_ready = None

        def fetch(self, cursors):
            metadata_started.set()
            assert release_metadata.wait(10), "simulated metadata read was not released"
            rows = [FetchedItem(source="elearning", account_id="school", source_id="announcement:1",
                title="课程作业公告", occurred_at="2026-09-08T22:00:00Z", payload={"body": "明天交作业"})]
            if self.on_items_ready is not None:
                self.on_items_ready(rows)
            sync_started.set()
            assert release_sync.wait(10), "simulated file sync was not released"
            return FetchResult(rows, {"elearning_state": "updated"})

    outcome = {}
    email = StaticSource([_item("<mail@x>", "邮件课程通知")])
    def run():
        try:
            outcome["detail"] = BriefingPipeline(service, [email, SlowElearningSource()],
                generator=AgentBriefingGenerator(model=model)).run()
        except Exception as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert metadata_started.wait(5)
        release_metadata.set()
        assert sync_started.wait(5)
        assert model.classification_calls == 0
        snapshot = briefing_progress.snapshot()
        assert snapshot and "邮件课程通知" not in snapshot["body"] and "课程作业公告" not in snapshot["body"]
        assert service.get_cursor("elearning", "school", "elearning_state") is None
        assert service.get_briefing("brf-2026-09-09-morning")["briefing"].body == ""
    finally:
        release_sync.set()
        worker.join(10)
    assert not worker.is_alive()
    assert "error" not in outcome, outcome.get("error")
    assert "课程作业公告" in outcome["detail"]["briefing"].body
    assert "邮件课程通知" in outcome["detail"]["briefing"].body
    assert model.classification_calls == 1
    assert service.get_cursor("elearning", "school", "elearning_state").cursor_value == "updated"
    assert briefing_progress.snapshot() is None


def _item(source_id, title, sender="Ada", email="ada@example.com", **extra):
    values = dict(
        source="email",
        source_id=source_id,
        sender=sender,
        sender_email=email,
        title=title,
        snippet="",
        occurred_at="2026-09-08T22:00:00Z",
    )
    values.update(extra)
    return FetchedItem(**values)


def test_pipeline_filters_composes_and_advances_cursor(tmp_path):
    svc = _svc(tmp_path)
    svc.create_rule(
        {
            "action": "exclude",
            "match_field": "sender_domain",
            "match_value": "spam.example",
        }
    )
    source = StaticSource(
        [
            _item("<keep@x>", "请确认合同", snippet="今天下午前回复"),
            _item("<drop@x>", "促销", email="bot@spam.example"),
            _item("<noreply@x>", "Build passed", email="noreply@github.com"),
        ],
        cursors={"imap_uid": "42"},
    )
    detail = BriefingPipeline(svc, [source]).run(
        kind="morning", briefing_date="2026-09-09"
    )
    briefing = detail["briefing"]
    assert briefing.status == "completed"
    assert briefing.fetched_count == 3
    assert briefing.filtered_count == 1
    assert briefing.kept_count == 2
    assert "需处理" in briefing.body
    assert len(detail["items"]) == 2
    assert detail["items"][0].section == "action"
    assert svc.get_cursor("email", "default", "imap_uid").cursor_value == "42"


def test_classification_lists_every_mail_and_cards_have_no_limit(tmp_path):
    svc = _svc(tmp_path)
    source = StaticSource([
        *[_item(f"<keep-{i}@x>", f"邮件 {i}", payload={"body": f"完整内容 {i}"}) for i in range(15)],
        _item("<reply@x>", "线程回复", thread_id="<keep-0@x>"),
        _item("<drop@x>", "通知", email="noreply@example.com", payload={"_test_selected": False, "_test_reason": "测试排除"}),
        _item("<list@x>", "广告", payload={"list_unsubscribe": True, "_test_selected": False, "_test_reason": "测试排除"}),
    ])
    detail = BriefingPipeline(svc, [source]).run()
    briefing = detail["briefing"]
    assert briefing.mail_snapshot_available is True
    assert briefing.fetched_count == 18
    assert briefing.kept_count == 16
    assert briefing.filtered_count == 2
    assert len(detail["items"]) == 15
    assert len(detail["mail"]) == briefing.kept_count + briefing.filtered_count
    assert {row["source_id"] for row in detail["mail"]} == {row.source_id for row in source._items}
    mails = {row["source_id"]: row for row in detail["mail"]}
    assert mails["<keep-14@x>"]["body"] == "完整内容 14"
    assert mails["<drop@x>"]["filter_reason"] == "测试排除"
    assert mails["<list@x>"]["filter_reason"] == "测试排除"


def test_pipeline_partial_advances_only_successful_source(tmp_path):
    svc = _svc(tmp_path)
    ok = StaticSource(
        [_item("<ok@x>", "产品周报已发")],
        cursors={"imap_uid": "7"},
        name="email",
    )
    bad = StaticSource(
        error=RuntimeError("imap down"),
        name="sms",
        account_id="default",
        cursors={"since": "x"},
    )
    detail = BriefingPipeline(svc, [ok, bad]).run(briefing_date="2026-09-09")
    assert detail["briefing"].status == "partial"
    assert "sms" in detail["briefing"].error_message
    assert svc.get_cursor("email", "default", "imap_uid").cursor_value == "7"
    assert svc.get_cursor("sms", "default", "since") is None


def test_partial_source_keeps_previous_candidates_and_window(tmp_path):
    svc = _svc(tmp_path)
    first = BriefingPipeline(svc, [StaticSource([
        _item("<old@x>", "旧事项"),
    ], cursors={"imap_uid": "1"})]).run()

    class PartialSource(StaticSource):
        def fetch(self, cursors):
            return FetchResult([_item("<new@x>", "新事项")], {}, ["one folder failed"])

    # Another successful source makes this a partial revision rather than a
    # fully failed run; the email source must keep its previous projection.
    ok = StaticSource([], name="sms", cursors={"since": "2"})
    updated = BriefingPipeline(svc, [PartialSource(), ok]).run(operation="update")
    assert updated["briefing"].status == "partial"
    assert "email:default" not in updated["briefing"].updated_sources
    assert updated["briefing"].source_windows["email:default"] == first["briefing"].source_windows["email:default"]
    assert "<old@x>" in {row["source_id"] for row in updated["mail"]}
    assert svc.get_cursor("email", "default", "imap_uid").cursor_value == "1"


def test_pipeline_all_sources_failed_does_not_advance_cursor(tmp_path):
    svc = _svc(tmp_path)
    source = StaticSource(error=RuntimeError("offline"), cursors={"imap_uid": "9"})
    detail = BriefingPipeline(svc, [source]).run(briefing_date="2026-09-09")
    assert detail["briefing"].status == "failed"
    assert detail["items"] == []
    assert svc.get_cursor("email", "default", "imap_uid") is None


def test_rerun_keeps_candidates_and_user_status(tmp_path):
    svc = _svc(tmp_path)
    day = "2026-09-09"
    first = BriefingPipeline(svc, [StaticSource([_item("<a@x>", "请确认合同")])]).run(briefing_date=day)
    original = first["items"][0]
    svc.update_item_status(original.id, "done")
    again = BriefingPipeline(svc, [StaticSource([])]).run(briefing_date=day)
    assert again["briefing"].fetched_count == 1
    assert again["items"][0].id == original.id
    assert again["items"][0].status == "done"
    third = BriefingPipeline(svc, [StaticSource([_item("<b@x>", "请审批预算")])]).run(briefing_date=day)
    assert third["briefing"].fetched_count == 2
    assert {item.source_id for item in third["items"]} == {"<a@x>", "<b@x>"}


def test_rerun_reapplies_rules_to_previously_filtered_mail(tmp_path):
    svc = _svc(tmp_path)
    rule = svc.create_rule({"action": "exclude", "match_field": "sender", "match_value": "Ada"})
    first = BriefingPipeline(svc, [StaticSource([_item("<a@x>", "请确认合同")])]).run(briefing_date="2026-09-09")
    assert first["items"] == []
    assert first["mail"][0]["category"] == "filtered"
    assert first["mail"][0]["filter_reason"] == "测试模型筛选结果"
    svc.delete_rule(rule.id)
    again = BriefingPipeline(svc, [StaticSource([])]).run(briefing_date="2026-09-09")
    assert len(again["items"]) == 1
    assert again["briefing"].filtered_count == 0
    assert again["mail"][0]["category"] == "selected"
    assert svc.get_revision(first["briefing"].id, 1)["mail"] == first["mail"]


def test_failed_retry_keeps_previous_document_and_cards(tmp_path):
    svc = _svc(tmp_path)
    first = BriefingPipeline(svc, [StaticSource([_item("<a@x>", "请确认合同")])]).run(briefing_date="2026-09-09")
    again = BriefingPipeline(svc, [StaticSource(error=RuntimeError("offline"))]).run(briefing_date="2026-09-09")
    assert again["briefing"].status == "failed"
    assert again["briefing"].body == first["briefing"].body
    assert again["items"] == first["items"]
    assert again["mail"] == first["mail"]
    assert again["briefing"].mail_snapshot_available is True
    assert svc.get_revision(first["briefing"].id, 2)["mail"] == first["mail"]


def test_mail_snapshots_do_not_follow_catalog_changes(tmp_path):
    svc = _svc(tmp_path)
    first = BriefingPipeline(svc, [StaticSource([
        _item("<a@x>", "旧标题", payload={"body": "旧正文"}),
    ])]).run()
    second = BriefingPipeline(svc, [StaticSource([
        _item("<a@x>", "新标题", payload={"body": "新正文"}),
    ])]).run(operation="update")
    assert second["mail"][0]["title"] == "新标题"
    assert second["mail"][0]["body"] == "新正文"
    assert svc.get_revision(first["briefing"].id, 1)["mail"] == first["mail"]


def test_failed_generation_keeps_catalog_and_cursor_unchanged(tmp_path):
    svc = _svc(tmp_path)
    source_id = "<a@x>"
    first = BriefingPipeline(svc, [StaticSource([
        _item(source_id, "旧标题"),
    ], cursors={"imap_uid": "1"})]).run()

    class BrokenGenerator:
        def generate(self, *_args, **_kwargs):
            raise RuntimeError("model unavailable")

    with pytest.raises(RuntimeError, match="model unavailable"):
        BriefingPipeline(svc, [StaticSource([
            _item(source_id, "未提交的新标题"),
        ], cursors={"imap_uid": "2"})], generator=BrokenGenerator()).run(operation="update")

    item, _ = svc.store.get_source_item_by_key("email", "default", source_id)
    assert item.title == "旧标题"
    assert svc.get_cursor("email", "default", "imap_uid").cursor_value == "1"
    assert svc.get_revision(first["briefing"].id, 1)["mail"] == first["mail"]


def test_snapshot_failure_rolls_back_candidate_and_cursor_promotion(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    archive = svc.store._archive
    failed_once = False

    def fail_once(*args):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("snapshot failed")
        return archive(*args)

    monkeypatch.setattr(svc.store, "_archive", fail_once)
    with pytest.raises(RuntimeError, match="snapshot failed"):
        BriefingPipeline(svc, [StaticSource([
            _item("<new@x>", "待提交"),
        ], cursors={"imap_uid": "7"})]).run()
    assert svc.store.get_source_item_by_key("email", "default", "<new@x>") is None
    assert svc.get_cursor("email", "default", "imap_uid") is None
    assert svc.store.pending_projection_events() == []


def test_thread_merge_includes_original_message_and_uses_latest(tmp_path):
    svc = _svc(tmp_path)
    source = StaticSource([
        _item("<root@x>", "请确认原稿", occurred_at="2026-09-08T20:00:00Z"),
        _item("<reply@x>", "请确认修订稿", thread_id="<root@x>", occurred_at="2026-09-08T22:00:00Z"),
    ])
    detail = BriefingPipeline(svc, [source]).run(briefing_date="2026-09-09")
    assert len(detail["items"]) == 1
    assert detail["items"][0].source_id == "<reply@x>"


def test_failed_today_sorts_before_older_completed_briefing(tmp_path):
    svc = _svc(tmp_path)
    BriefingPipeline(svc, [StaticSource([_item("<a@x>", "请确认合同")])]).run(briefing_date="2026-09-08")
    today = BriefingPipeline(svc, [StaticSource(error=RuntimeError("offline"))]).run(briefing_date="2026-09-09")
    assert svc.list_briefings()[0].id == today["briefing"].id
    assert today["briefing"].title == "2026年9月9日·简报"
