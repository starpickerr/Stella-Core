from email.message import EmailMessage as RfcMessage

from agent.briefing.pipeline import BriefingPipeline
from agent.briefing.service import BriefingService
from agent.briefing.sources.email import parse_rfc822, EmailSource
from agent.briefing.store import BriefingStore
from agent.tools.briefing.briefing_tool import BriefingTool


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
            assert args[1] == "(BODY.PEEK[]<0.65536>)"
            uid = str(args[0])
            raw = self.messages[uid]
            return "OK", [(b"%s (UID %s RFC822.HEADER {%d}" % (uid.encode(), uid.encode(), len(raw)), raw), b")"]
        raise AssertionError(command)

    def logout(self):
        self.logged_out = True
        return "OK", []


def test_parse_rfc822_envelope_and_list_headers():
    raw = _raw(
        extra={
            "In-Reply-To": "<root@example.com>",
            "List-Id": "Dev <dev.example.com>",
            "List-Unsubscribe": "<mailto:unsub@example.com>",
        }
    )
    item = parse_rfc822(raw, uid="12")
    assert item.source == "email"
    assert item.source_id == "<m1@example.com>"
    assert item.sender == "Ada"
    assert item.sender_email == "ada@example.com"
    assert item.title == "请确认合同"
    assert item.thread_id == "<root@example.com>"
    assert item.list_id == "dev.example.com"
    assert item.payload["list_unsubscribe"] is True
    assert item.occurred_at.startswith("2026-09-08T22:00:00")


def test_email_source_incremental_uid(tmp_path):
    fake = FakeIMAP(
        [
            (1, _raw(msgid="<old@x>", subject="old")),
            (5, _raw(msgid="<new@x>", subject="new")),
        ]
    )
    source = EmailSource(opener=lambda: fake, lookback_days=2)
    first = source.fetch({})
    assert [row.source_id for row in first.items] == ["<old@x>", "<new@x>"]
    assert first.cursors["imap_uid"] == "5"
    assert first.cursors["imap_uidvalidity"] == "9"
    assert fake.logged_out is True

    fake2 = FakeIMAP(
        [
            (1, _raw(msgid="<old@x>", subject="old")),
            (5, _raw(msgid="<new@x>", subject="new")),
            (8, _raw(msgid="<newer@x>", subject="newer")),
        ]
    )
    source2 = EmailSource(opener=lambda: fake2)
    again = source2.fetch({"imap_uid": "5", "imap_uidvalidity": "9"})
    assert [row.source_id for row in again.items] == ["<newer@x>"]
    assert again.cursors["imap_uid"] == "8"


def test_uidvalidity_reset_refetches(tmp_path):
    fake = FakeIMAP([(3, _raw(msgid="<a@x>", subject="a"))], uidvalidity="100")
    source = EmailSource(opener=lambda: fake)
    result = source.fetch({"imap_uid": "99", "imap_uidvalidity": "1"})
    assert [row.source_id for row in result.items] == ["<a@x>"]
    assert result.cursors["imap_uidvalidity"] == "100"


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
    assert detail["briefing"].kept_count == 1
    assert svc.get_cursor("email", "default", "imap_uid").cursor_value == "2"


def test_briefing_tool_run_and_get(tmp_path):
    svc = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    fake = FakeIMAP([(1, _raw())])
    pipeline = BriefingPipeline(svc, [EmailSource(opener=lambda: fake)])
    tool = BriefingTool(service=svc, pipeline=pipeline)
    ran = tool.execute({"action": "run", "briefing_date": "2026-09-09"})
    assert ran.status == "success"
    assert "请确认合同" in ran.result
    listed = tool.execute({"action": "list", "kind": "morning"})
    assert "brf-2026-09-09-morning" in listed.result
    got = tool.execute({"action": "get", "briefing_id": "brf-2026-09-09-morning"})
    assert got.status == "success"
    item_id = svc.get_briefing("brf-2026-09-09-morning")["items"][0].id
    marked = tool.execute({"action": "item_status", "item_id": item_id, "status": "done"})
    assert marked.status == "success"
    assert "done" in marked.result


def test_parser_reads_body_and_ignores_attachment():
    msg = RfcMessage()
    msg["Subject"] = "Review"
    msg.set_content("Please approve the budget today.")
    msg.add_attachment(b"private attachment", maintype="text", subtype="plain", filename="secret.txt")
    parsed = parse_rfc822(msg.as_bytes(), uid="5", uidvalidity="7")
    assert parsed.snippet == "Please approve the budget today."
    assert parsed.source_id == "imap-uid-7-5"
    assert parsed.url == ""


def test_parser_html_fallback_and_length_limit():
    msg = RfcMessage()
    msg.set_content("<style>secret</style><p>Please confirm &amp; reply</p><script>bad()</script>", subtype="html")
    parsed = parse_rfc822(msg.as_bytes(), uid="1")
    assert parsed.snippet == "Please confirm & reply"
    msg.set_content("x" * 1000)
    assert len(parse_rfc822(msg.as_bytes(), uid="1").snippet) == 500


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
    from agent.briefing.sources.static import StaticSource
    tool = BriefingTool(service=svc, pipeline=BriefingPipeline(svc, [StaticSource(error=RuntimeError("offline"))]))
    assert tool.execute({"action": "run"}).status != "success"
    rule = svc.create_rule({"action": "exclude", "match_field": "sender", "match_value": "Ada"})
    assert tool.execute({"action": "update_rule", "rule_id": rule.id, "enabled": False}).status == "success"
    assert svc.get_rule(rule.id).enabled is False


def test_connection_verifies_ssl_and_logs_out_on_failed_login():
    import ssl
    import sys
    from unittest.mock import patch
    source = EmailSource(host="imap.example.com", user="ada@example.com", password="secret")
    with patch("agent.briefing.sources.email.imaplib.IMAP4_SSL") as connect:
        client = connect.return_value
        client.login.side_effect = RuntimeError("bad credentials")
        import pytest
        with pytest.raises(RuntimeError, match="bad credentials"):
            source._connect()
        context = connect.call_args.kwargs["ssl_context"]
        assert context.check_hostname is True
        assert context.verify_mode == ssl.CERT_REQUIRED
        if sys.version_info >= (3, 9):
            assert connect.call_args.kwargs["timeout"] == 30
        client.logout.assert_called_once_with()
