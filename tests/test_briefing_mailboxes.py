"""Multiple account credentials, migrations and all generation entry points."""
import json
from datetime import datetime

import pytest

pytestmark = pytest.mark.usefixtures("deterministic_briefing_generator")

from agent.briefing import settings
from agent.briefing.pipeline import BriefingPipeline
from agent.briefing.scheduler import BriefingScheduler
from agent.briefing.service import BriefingService
from agent.briefing.sources.base import FetchedItem, FetchResult
from agent.briefing.sources.email import EmailSource
from agent.briefing.store import BriefingStore
from agent.tools.briefing.briefing_tool import BriefingTool
from channel.web.web_channel import _briefing_pipeline


@pytest.fixture
def path(tmp_path, monkeypatch):
    for key in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD", "IMAP_PORT", "IMAP_FOLDER"):
        monkeypatch.delenv(key, raising=False)
    target = tmp_path / "mailbox.json"
    monkeypatch.setattr(settings, "mailbox_path", lambda: target)
    monkeypatch.setattr("agent.briefing.scheduler.mailbox_path", lambda: target)
    return target


def add(user, password="secret"):
    return settings.save_mailbox({"action": "add", "host": "imap.example.com", "user": user, "password": password})


def test_accounts_keep_separate_passwords_and_replacements(path):
    first = add("ada@example.com", "ada-secret")
    second = add("bob@example.com", "bob-secret")
    assert first["id"] != second["id"]
    settings.save_mailbox({"id": second["id"], "password": "new-bob-secret"})
    settings.save_mailbox({"id": first["id"], "password": settings.PASSWORD_MASK, "folder": "Work"})
    rows = settings.load_mailboxes()
    assert rows[0]["password"] == "ada-secret"
    assert rows[1]["password"] == "new-bob-secret"
    assert rows[0]["folder"] == "Work"
    public = settings.public_mailboxes()
    assert all(row["password_masked"] == "********" for row in public["mailboxes"])
    assert all(row["configured"] for row in public["mailboxes"])
    assert "secret" not in json.dumps(public)


def test_new_account_cannot_inherit_password_or_save_mask(path):
    add("ada@example.com", "ada-secret")
    before = path.read_bytes()
    for value in ("", "********"):
        with pytest.raises(ValueError, match="授权码"):
            add("bob@example.com", value)
        assert path.read_bytes() == before
    with pytest.raises(ValueError, match="邮箱不存在"):
        settings.save_mailbox({"id": "missing", "password": "replacement"})
    assert path.read_bytes() == before


def test_duplicate_mailbox_does_not_duplicate_ingestion(path):
    add("ada@example.com")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="已经添加"):
        add("ada@example.com")
    assert path.read_bytes() == before
    other_folder = settings.save_mailbox({"action": "add", "host": "imap.example.com", "user": "ada@example.com", "password": "secret", "folder": "Work"})
    assert other_folder["folder"] == "Work"
    assert len(settings.email_sources()) == 2


def test_legacy_account_migrates_without_resetting_source_identity(path):
    cfg = {"host": "imap.example.com", "user": "ada@example.com", "password": "old-secret", "port": 993, "folder": "INBOX"}
    path.write_text(json.dumps(cfg))
    previous_identity = EmailSource(**cfg).account_id
    assert settings.public_mailboxes()["mailboxes"][0]["id"] == "legacy"
    add("bob@example.com", "bob-secret")
    assert json.loads(path.read_text())["version"] == 2
    assert settings.load_mailboxes()[0]["password"] == "old-secret"
    assert settings.email_sources()[0].account_id == previous_identity


def test_delete_all_is_authoritative_even_with_environment_credentials(path, monkeypatch):
    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "env@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "env-secret")
    assert settings.load_mailboxes()[0]["id"] == "environment"
    settings.delete_mailbox("environment")
    assert settings.load_mailboxes() == []
    assert settings.public_mailboxes()["configured"] is False
    assert settings.email_sources() == []


def test_connection_draft_uses_only_the_selected_account(path, monkeypatch):
    add("ada@example.com", "ada-secret")
    second = add("bob@example.com", "bob-secret")
    before = path.read_bytes()
    checked = []
    monkeypatch.setattr(EmailSource, "check_connection", lambda source: checked.append(source._settings()))
    settings.check_mailbox_connection({"id": second["id"], "password": "", "folder": "Work"})
    assert checked[0]["user"] == "bob@example.com"
    assert checked[0]["password"] == "bob-secret"
    assert checked[0]["folder"] == "Work"
    assert path.read_bytes() == before


def test_all_entry_points_use_all_accounts_and_re_read_edits(path, tmp_path):
    add("ada@example.com", "ada-secret")
    second = add("bob@example.com", "bob-secret")
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    scheduler = BriefingScheduler(service)
    pipelines = [_briefing_pipeline(service), BriefingTool()._get_pipeline(service), scheduler.pipeline_factory()]
    for pipeline in pipelines:
        assert [source._settings()["user"] for source in pipeline.sources] == ["ada@example.com", "bob@example.com"]
    settings.save_mailbox({"id": second["id"], "password": "replacement"})
    assert scheduler.pipeline_factory().sources[1]._settings()["password"] == "replacement"


def test_shared_message_ids_and_uids_remain_separate_and_failed_account_is_named(path, tmp_path, monkeypatch):
    add("ada@example.com", "ada-secret")
    add("bob@example.com", "bob-secret")
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    now = lambda: datetime.fromisoformat("2026-09-09T08:00:00+08:00")
    calls = []

    def fetch(source, cursors):
        calls.append((source._settings()["user"], cursors.get("imap_uid")))
        return FetchResult(items=[FetchedItem(
            source="email", account_id=source.account_id, source_id="<shared@example.com>",
            title=source._settings()["user"], sender="Ada", sender_email="ada@example.com",
            occurred_at="2026-09-08T23:00:00Z", payload={"body": "full content"},
        )], cursors={"imap_uid": "42"})

    monkeypatch.setattr(EmailSource, "fetch", fetch)
    first = BriefingPipeline(service, settings.email_sources(), clock=now).run()
    assert len(first["items"]) == len(first["mail"]) == 2
    assert len({row["account_id"] for row in first["mail"]}) == 2
    assert first["briefing"].kept_count == 2
    assert calls == [("ada@example.com", None), ("bob@example.com", None)]
    sources = settings.email_sources()
    service.set_cursor("email", "imap_uid", "99", sources[0].account_id)
    BriefingPipeline(service, sources, clock=now).run(operation="update")
    assert calls[-2:] == [("ada@example.com", "99"), ("bob@example.com", "42")]

    def partly_failed(source, cursors):
        if source._settings()["user"] == "bob@example.com":
            raise RuntimeError("offline")
        return fetch(source, cursors)

    monkeypatch.setattr(EmailSource, "fetch", partly_failed)
    partial = BriefingPipeline(service, settings.email_sources(), clock=now).run(operation="update")
    assert partial["briefing"].status == "partial"
    assert "bob@example.com" in partial["briefing"].error_message
    assert len(partial["mail"]) == 2
    assert service.get_revision(first["briefing"].id, 1)["mail"] == first["mail"]
