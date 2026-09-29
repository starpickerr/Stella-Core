from agent.briefing.pipeline import BriefingPipeline
from agent.briefing.service import BriefingService
from agent.briefing.sources.base import FetchedItem
from agent.briefing.sources.static import StaticSource
from agent.briefing.store import BriefingStore


def _svc(tmp_path) -> BriefingService:
    return BriefingService(BriefingStore(tmp_path / "briefing.db"))


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
    assert briefing.filtered_count == 2
    assert briefing.kept_count == 1
    assert "需回复" in briefing.body
    assert len(detail["items"]) == 1
    assert detail["items"][0].section == "action"
    assert svc.get_cursor("email", "default", "imap_uid").cursor_value == "42"


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
    svc.delete_rule(rule.id)
    again = BriefingPipeline(svc, [StaticSource([])]).run(briefing_date="2026-09-09")
    assert len(again["items"]) == 1
    assert again["briefing"].filtered_count == 0


def test_failed_retry_keeps_previous_document_and_cards(tmp_path):
    svc = _svc(tmp_path)
    first = BriefingPipeline(svc, [StaticSource([_item("<a@x>", "请确认合同")])]).run(briefing_date="2026-09-09")
    again = BriefingPipeline(svc, [StaticSource(error=RuntimeError("offline"))]).run(briefing_date="2026-09-09")
    assert again["briefing"].status == "failed"
    assert again["briefing"].body == first["briefing"].body
    assert again["items"] == first["items"]


def test_thread_merge_includes_original_message_and_uses_latest(tmp_path):
    svc = _svc(tmp_path)
    source = StaticSource([
        _item("<root@x>", "请确认原稿", occurred_at="2026-09-08T20:00:00Z"),
        _item("<reply@x>", "请确认修订稿", thread_id="<root@x>", occurred_at="2026-09-08T22:00:00Z"),
    ])
    detail = BriefingPipeline(svc, [source]).run(briefing_date="2026-09-09")
    assert len(detail["items"]) == 1
    assert detail["items"][0].source_id == "<reply@x>"


def test_mail_metadata_cannot_inject_markdown(tmp_path):
    svc = _svc(tmp_path)
    source = StaticSource([_item("<a@x>", "![image](https://evil.example/a)", snippet="<script>bad()</script>")])
    detail = BriefingPipeline(svc, [source]).run(briefing_date="2026-09-09")
    body = detail["briefing"].body
    assert "![image](https://evil.example/a)" not in body
    assert r"\!\[image\]" in body


def test_failed_today_sorts_before_older_completed_briefing(tmp_path):
    svc = _svc(tmp_path)
    BriefingPipeline(svc, [StaticSource([_item("<a@x>", "请确认合同")])]).run(briefing_date="2026-09-08")
    today = BriefingPipeline(svc, [StaticSource(error=RuntimeError("offline"))]).run(briefing_date="2026-09-09")
    assert svc.list_briefings()[0].id == today["briefing"].id
    assert today["briefing"].title == "9 月 9 日晨报"
