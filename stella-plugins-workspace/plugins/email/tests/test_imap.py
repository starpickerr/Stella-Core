from email.message import EmailMessage as RfcMessage
import pytest
from stella_email_domain.imap import parse_rfc822
from stella_email_domain.imap import EmailSource as DomainEmailSource


def EmailSource(**kwargs):
    config = dict(host='imap.example.test', port=993, user='test@example.test', password='test-secret', folder='INBOX')
    config.update(kwargs)
    if 'opener' in kwargs:
        config.setdefault('account_id', 'default')
    return DomainEmailSource(**config)

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


def test_parser_reads_body_and_ignores_attachment():
    msg = RfcMessage()
    msg["Subject"] = "Review"
    msg.set_content("Please approve the budget today.")
    msg.add_attachment(b"private attachment", maintype="text", subtype="plain", filename="secret.txt")
    parsed = parse_rfc822(msg.as_bytes(), uid="5", uidvalidity="7")
    assert parsed.snippet == "Please approve the budget today."
    assert parsed.payload["body"] == "Please approve the budget today."
    assert parsed.source_id == "imap-uid-7-5"
    assert parsed.url == ""


def test_parser_html_fallback_and_length_limit():
    msg = RfcMessage()
    msg.set_content("<style>secret</style><p>Please confirm &amp; reply</p><script>bad()</script>", subtype="html")
    parsed = parse_rfc822(msg.as_bytes(), uid="1")
    assert parsed.snippet == "Please confirm & reply"
    assert "secret" not in parsed.payload["body"]
    assert "bad()" not in parsed.payload["body"]
    msg.set_content("x" * 1000)
    parsed = parse_rfc822(msg.as_bytes(), uid="1")
    assert len(parsed.snippet) == 500
    assert parsed.payload["body"] == "x" * 1000


def test_refresh_reads_existing_bodies_without_rewinding_uid():
    fake = FakeIMAP([(1, _raw(msgid="<old@x>")), (5, _raw(msgid="<new@x>"))])
    result = EmailSource(opener=lambda: fake).fetch({
        "imap_uid": "9", "imap_uidvalidity": "9", "since": "2026-09-08T12:00:00Z",
        "refresh_existing_content": "1",
    })
    assert {row.source_id for row in result.items} == {"<old@x>", "<new@x>"}
    assert all(row.payload["body"] == "unused" for row in result.items)
    assert result.cursors["imap_uid"] == "9"


def test_connection_verifies_ssl_and_logs_out_on_failed_login():
    import ssl
    import sys
    from unittest.mock import patch
    source = EmailSource(host="imap.example.com", user="ada@example.com", password="secret")
    with patch("stella_email_domain.imap.imaplib.IMAP4_SSL") as connect:
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


def test_window_start_searches_offline_gap_and_fetches_over_200_messages():
    class RecordingIMAP(FakeIMAP):
        def uid(self, command, *args):
            if command == "SEARCH":
                self.search_args = args
            return super().uid(command, *args)
    fake = RecordingIMAP([(i, _raw(msgid=f"<mail-{i}@x>")) for i in range(1, 202)])
    result = EmailSource(opener=lambda: fake).fetch({"since": "2026-08-01T05:00:00Z"})
    assert fake.search_args == (None, "SINCE", "31-Jul-2026")
    assert len(result.items) == 201
    assert result.cursors["imap_uid"] == "201"


def test_dns_error_is_reported_before_authorization_code_validation():
    import socket
    from unittest.mock import patch
    source = EmailSource(host="imap.gmail.com", user="ada@gmail.com", password="private-code")
    with patch("stella_email_domain.imap.imaplib.IMAP4_SSL", side_effect=socket.gaierror(8, "nodename nor servname provided")):
        with pytest.raises(ValueError, match="尚未验证授权码") as error:
            source._connect()
    assert "imap.gmail.com" in str(error.value)
    assert "private-code" not in str(error.value)


def test_login_error_cleans_up_and_does_not_expose_code():
    import imaplib
    from unittest.mock import patch
    source = EmailSource(host="imap.gmail.com", user="ada@gmail.com", password="private-code")
    with patch("stella_email_domain.imap.imaplib.IMAP4_SSL") as connect:
        connect.return_value.login.side_effect = imaplib.IMAP4.error("AUTHENTICATIONFAILED private-code")
        with pytest.raises(ValueError, match="登录失败") as error:
            source._connect()
        connect.return_value.logout.assert_called_once_with()
    assert "private-code" not in str(error.value)


def test_connection_check_opens_folder_readonly_and_logs_out():
    fake = FakeIMAP([])
    source = EmailSource(opener=lambda: fake)
    result = source.check_connection()
    assert result["connected"] and result["folder_accessible"]
    assert fake.logged_out


def test_imap_id_is_sent_after_login_before_opening_folder():
    from unittest.mock import patch

    events = []

    class IdRequiredIMAP(FakeIMAP):
        def __init__(self):
            super().__init__([])
            self.identified = False

        def socket(self):
            return self

        def settimeout(self, seconds):
            assert seconds == 30

        def login(self, user, password):
            events.append("login")
            return "OK", []

        def capability(self):
            events.append("capability")
            return "OK", [b"IMAP4rev1 ID UIDPLUS"]

        def xatom(self, command, payload):
            events.append("id")
            assert command == "ID"
            assert '"name" "Stella"' in payload
            self.identified = True
            return "OK", []

        def list(self):
            events.append("list")
            return "OK", [b'() "/" "INBOX"']

        def select(self, folder, readonly=True):
            events.append("select")
            if not self.identified:
                return "NO", [b"EXAMINE Unsafe Login. Please contact kefu@188.com for help"]
            return super().select(folder, readonly)

    client = IdRequiredIMAP()
    with patch("stella_email_domain.imap.imaplib.IMAP4_SSL", return_value=client):
        result = EmailSource(host="imap.163.com", user="ada@163.com", password="auth-code").check_connection()

    assert result["folder_accessible"] is True
    assert events == ["login", "capability", "id", "list", "select"]
    assert client.logged_out


def test_imap_id_is_not_sent_without_server_capability():
    from unittest.mock import patch

    class PlainIMAP(FakeIMAP):
        def __init__(self):
            super().__init__([])
            self.id_calls = 0

        def socket(self):
            return self

        def settimeout(self, seconds):
            pass

        def login(self, user, password):
            return "OK", []

        def capability(self):
            return "OK", [b"IMAP4rev1 IDLE UIDPLUS"]

        def xatom(self, command, payload):
            self.id_calls += 1
            raise AssertionError("ID is not advertised")

    client = PlainIMAP()
    with patch("stella_email_domain.imap.imaplib.IMAP4_SSL", return_value=client):
        result = EmailSource(host="imap.example.com", user="ada@example.com", password="auth-code").check_connection()

    assert result["folder_accessible"] is True
    assert client.id_calls == 0


def test_connection_lists_provider_folders_and_reports_select_failure_without_secret():
    import base64

    encoded = base64.b64encode("收件箱".encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
    wire_name = f"&{encoded}-"

    class FolderIMAP(FakeIMAP):
        def list(self):
            return "OK", [b'(\\Noselect) "/" "Root"', b'() "/" "INBOX"',
                          f'() "/" "{wire_name}"'.encode()]

        def select(self, folder, readonly=True):
            assert readonly is True
            return ("NO", [b"Access denied private-code for this mailbox"]) if folder == "INBOX" else ("OK", [b"1"])

    fake = FolderIMAP([])
    settings = dict(host="imap.163.com", port=993, user="ada@163.com", password="private-code")
    result = EmailSource(**settings, folder="INBOX", opener=lambda: fake).check_connection()
    assert result["connected"] and not result["folder_accessible"]
    assert result["folders"] == [{"name": "INBOX", "label": "INBOX"},
                                 {"name": wire_name, "label": "收件箱"}]
    assert "Access denied" in result["message"]
    assert "private-code" not in result["message"]
    assert fake.logged_out

    other = FolderIMAP([])
    selected = EmailSource(**settings, folder=wire_name, opener=lambda: other).check_connection()
    assert selected["folder_accessible"] and other.logged_out


def test_fetch_reports_select_reason_and_keeps_password_private():
    class DeniedIMAP(FakeIMAP):
        def select(self, folder, readonly=True):
            return "NO", [b"IMAP access denied private-code"]

    fake = DeniedIMAP([])
    source = EmailSource(host="imap.163.com", port=993, user="ada@163.com",
                         password="private-code", folder="INBOX", opener=lambda: fake)
    with pytest.raises(ValueError, match="IMAP access denied") as error:
        source.fetch({})
    assert "private-code" not in str(error.value)
    assert fake.logged_out


def test_unsafe_login_is_reported_as_server_security_rejection():
    class DeniedIMAP(FakeIMAP):
        def select(self, folder, readonly=True):
            return "NO", [b"EXAMINE Unsafe Login. Please contact kefu@188.com for help"]

    result = EmailSource(password="private-code", opener=lambda: DeniedIMAP([])).check_connection()

    assert result["connected"] is True
    assert result["folder_accessible"] is False
    assert "邮箱服务器" in result["message"]
    assert "文件夹名称错误" in result["message"]
    assert "请在简报设置中测试连接" not in result["message"]
