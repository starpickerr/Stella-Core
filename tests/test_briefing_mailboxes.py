"""Generation entry points share configured Email sources and independent cursors."""
from datetime import datetime
from types import SimpleNamespace
import pytest
from agent.briefing.pipeline import BriefingPipeline
from tests.briefing_domain import BriefingService, BriefingStore
from agent.briefing.sources.base import FetchedItem, FetchResult
from tests.email_domain import EmailService, imap
from agent.tools.briefing.briefing_tool import BriefingTool
from channel.desktop.desktop_channel import _briefing_pipeline

EmailSource = imap.EmailSource
pytestmark = pytest.mark.usefixtures('deterministic_briefing_generator')


@pytest.fixture
def settings(tmp_path, monkeypatch):
    service = EmailService(tmp_path / 'email.db')
    def sources():
        return [service._source(service._account(row['mailbox_id'])) for row in service.list_sources()]
    monkeypatch.setattr('agent.briefing.sources.registry._email_sources', sources)
    return SimpleNamespace(save_mailbox=service.save_account, email_sources=sources)


def add(settings, user, password='secret'):
    return settings.save_mailbox(dict(action='add', host='imap.example.com', user=user, password=password))

def test_all_entry_points_use_all_accounts_and_re_read_edits(settings, tmp_path):
    add(settings, "ada@example.com", "ada-secret")
    second = add(settings, "bob@example.com", "bob-secret")
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    tool = BriefingTool()
    pipelines = [_briefing_pipeline(service), tool._get_pipeline(service)]
    for pipeline in pipelines:
        assert [source._settings()["user"] for source in pipeline.sources] == ["ada@example.com", "bob@example.com"]
    settings.save_mailbox({"id": second["id"], "password": "replacement"})
    assert tool._get_pipeline(service).sources[1]._settings()["password"] == "replacement"


def test_shared_message_ids_and_uids_remain_separate_and_failed_account_is_named(settings, tmp_path, monkeypatch):
    add(settings, "ada@example.com", "ada-secret")
    add(settings, "bob@example.com", "bob-secret")
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    def now():
        return datetime.fromisoformat("2026-09-09T08:00:00+08:00")
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
