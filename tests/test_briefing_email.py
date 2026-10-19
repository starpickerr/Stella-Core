"""Core generation with the external Email reader, using fake IMAP only."""
from datetime import datetime, timezone
from email.message import EmailMessage as RfcMessage
import pytest
from agent.briefing.pipeline import BriefingPipeline
from tests.briefing_domain import BriefingService, BriefingStore
from tests.email_domain import EmailSource
from agent.tools.briefing.briefing_tool import BriefingTool

pytestmark = pytest.mark.usefixtures('deterministic_briefing_generator')

@pytest.fixture(autouse=True)
def fixed_briefing_clock(monkeypatch):
    monkeypatch.setattr(
        "agent.briefing.pipeline._now",
        lambda: datetime(2026, 9, 9, 8, tzinfo=timezone.utc),
    )


def _raw(
    *,
    msgid="<m1@example.com>",
    subject="请确认合同",
    from_addr="Ada <ada@example.com>",
    date="Tue, 8 Sep 2026 22:00:00 +0000",
    extra=None,
) -> bytes:
    msg = RfcMessage()
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg["Date"] = date
    msg["Message-ID"] = msgid
    if extra:
        for key, value in extra.items():
            if key in msg:
                msg.replace_header(key, value)
            else:
                msg[key] = value
    msg.set_content("unused")
    return msg.as_bytes()


class FakeIMAP:
    def __init__(self, messages, uidvalidity="9"):
        self.messages = {str(uid): raw for uid, raw in messages}
        self.untagged_responses = {"UIDVALIDITY": [uidvalidity.encode()]}
        self.logged_out = False

    def select(self, folder, readonly=True):
        assert folder == "INBOX"
        assert readonly is True
        return "OK", [b"2"]

    def uid(self, command, *args):
        cmd = command.upper()
        if cmd == "SEARCH":
            parts = [str(a) for a in args if a is not None]
            uids = sorted(self.messages, key=int)
            if parts and parts[0].upper() == "UID":
                start = int(parts[1].split(":")[0])
                uids = [uid for uid in uids if int(uid) >= start]
            return "OK", [" ".join(uids).encode()]
        if cmd == "FETCH":
            assert args[1] == "(BODY.PEEK[])"
            uid = str(args[0])
            raw = self.messages[uid]
            return "OK", [(b"%s (UID %s RFC822.HEADER {%d}" % (uid.encode(), uid.encode(), len(raw)), raw), b")"]
        raise AssertionError(command)

    def logout(self):
        self.logged_out = True
        return "OK", []


def test_email_source_through_pipeline(tmp_path):
    svc = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    fake = FakeIMAP(
        [
            (1, _raw(msgid="<keep@x>", subject="请确认合同")),
            (2, _raw(msgid="<noise@x>", subject="Build", extra={"From": "CI <noreply@github.com>"})),
        ]
    )
    detail = BriefingPipeline(svc, [EmailSource(opener=lambda: fake)]).run(
        briefing_date="2026-09-09"
    )
    assert detail["briefing"].status == "completed"
    assert detail["briefing"].fetched_count == 2
    assert detail["briefing"].kept_count == 2
    assert svc.get_cursor("email", "default", "imap_uid").cursor_value == "2"


def test_briefing_tool_run_and_get(tmp_path):
    svc = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    fake = FakeIMAP([(1, _raw())])
    pipeline = BriefingPipeline(svc, [EmailSource(opener=lambda: fake)])
    tool = BriefingTool(service=svc, pipeline=pipeline)
    ran = tool.execute({"action": "run", "briefing_date": "2026-09-09"})
    assert ran.status == "success"
    assert "请确认合同" in ran.result
    listed = tool.execute({"action": "list"})
    assert "brf-2026-09-09" in listed.result
    got = tool.execute({"action": "get", "briefing_id": "brf-2026-09-09"})
    assert got.status == "success"
    item_id = svc.get_briefing("brf-2026-09-09")["items"][0].id
    marked = tool.execute({"action": "item_status", "item_id": item_id, "status": "done"})
    assert marked.status == "success"
    assert "done" in marked.result


def test_pipeline_hydrates_cached_summary_only_messages(tmp_path):
    from agent.briefing.sources.base import FetchedItem
    svc = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    svc.upsert_source_item(FetchedItem(
        source="email", source_id="<m1@example.com>", title="旧摘要", occurred_at="2026-09-08T22:00:00Z",
    ).to_catalog_payload())
    svc.set_cursor("email", "imap_uid", "1")
    svc.set_cursor("email", "imap_uidvalidity", "9")
    detail = BriefingPipeline(svc, [EmailSource(opener=lambda: FakeIMAP([(1, _raw())]))]).run()
    assert len(detail["mail"]) == 1
    assert detail["mail"][0]["body_available"] is True
    assert detail["mail"][0]["body"] == "unused"


def test_fetch_failure_never_skips_uid_or_commits_cursor(tmp_path):
    class BrokenIMAP(FakeIMAP):
        def uid(self, command, *args):
            if command.upper() == "FETCH" and str(args[0]) == "2":
                return "NO", [b"temporary error"]
            return super().uid(command, *args)
    svc = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    fake = BrokenIMAP([(1, _raw(msgid="<one@x>")), (2, _raw(msgid="<two@x>")), (3, _raw(msgid="<three@x>"))])
    detail = BriefingPipeline(svc, [EmailSource(opener=lambda: fake)]).run(briefing_date="2026-09-09")
    assert detail["briefing"].status == "failed"
    assert svc.get_cursor("email", "default", "imap_uid") is None
    assert fake.logged_out is True


def test_tool_reports_failed_generation_and_can_disable_rule(tmp_path):
    svc = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    from briefing_fakes import StaticSource
    tool = BriefingTool(service=svc, pipeline=BriefingPipeline(svc, [StaticSource(error=RuntimeError("offline"))]))
    assert tool.execute({"action": "run"}).status != "success"
    rule = svc.create_rule({"action": "exclude", "match_field": "sender", "match_value": "Ada"})
    assert tool.execute({"action": "update_rule", "rule_id": rule.id, "enabled": False}).status == "success"
    assert svc.get_rule(rule.id).enabled is False
