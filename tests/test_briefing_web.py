"""Authenticated briefing handlers with a real isolated SQLite service."""
from datetime import datetime, timezone
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from agent.briefing.pipeline import BriefingPipeline
from agent.briefing.service import BriefingService
from agent.briefing.sources.base import FetchedItem
from agent.briefing.sources.static import StaticSource
from agent.briefing.store import BriefingStore
from channel.web import web_channel


@pytest.fixture(autouse=True)
def fixed_briefing_clock(monkeypatch):
    monkeypatch.setattr(
        "agent.briefing.pipeline._now",
        lambda: datetime(2026, 9, 9, 8, tzinfo=timezone.utc),
    )


@pytest.fixture
def api(tmp_path):
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    source = StaticSource([FetchedItem(
        source="email", source_id="<hello@x>", title="请确认合同", sender="Ada",
        sender_email="ada@example.com", occurred_at="2026-09-08T22:00:00Z",
    )])
    with ExitStack() as stack:
        stack.enter_context(patch.object(web_channel, "_briefing_service", return_value=service))
        stack.enter_context(patch.object(web_channel, "_briefing_pipeline", return_value=BriefingPipeline(service, [source])))
        stack.enter_context(patch("agent.briefing.settings.mailbox_path", return_value=tmp_path / "mailbox.json"))
        auth = stack.enter_context(patch.object(web_channel, "_require_auth"))
        stack.enter_context(patch.object(web_channel.web, "header"))
        yield service, auth


def call(handler, method="POST", body=None, params=None, args=()):
    with patch.object(web_channel.web, "data", return_value=json.dumps(body or {}).encode()), \
         patch.object(web_channel.web, "input", return_value=SimpleNamespace(**(params or {}))):
        return json.loads(getattr(handler(), method)(*args))


def test_run_list_detail_and_mark(api):
    service, auth = api
    ran = call(web_channel.BriefingRunHandler, body={"briefing_date": "2026-09-09"})
    assert ran["status"] == "success"
    assert ran["briefing"]["status"] == "completed"
    assert ran["items"][0]["title"] == "请确认合同"
    listed = call(web_channel.BriefingsHandler, "GET", params={"kind": "morning", "status": ""})
    assert len(listed["briefings"]) == 1
    detail = call(web_channel.BriefingDetailHandler, "GET", args=(ran["briefing"]["id"],))
    assert detail == ran
    marked = call(web_channel.BriefingItemStatusHandler, body={"id": ran["items"][0]["id"], "status": "done"})
    assert marked["item"]["status"] == "done"
    assert auth.call_count == 4


def test_rule_crud(api):
    _, auth = api
    created = call(web_channel.BriefingRulesHandler, body={"action": "exclude", "match_field": "sender", "match_value": "Ada"})
    rule = created["rule"]
    assert rule["enabled"] is True
    listed = call(web_channel.BriefingRulesHandler, "GET")
    assert listed["rules"] == [rule]
    updated = call(web_channel.BriefingRuleUpdateHandler, body={"id": rule["id"], "enabled": False})
    assert updated["rule"]["enabled"] is False
    assert call(web_channel.BriefingRuleDeleteHandler, body={"id": rule["id"]}) == {"status": "success"}
    assert call(web_channel.BriefingRulesHandler, "GET")["rules"] == []
    assert auth.call_count == 5


@pytest.mark.parametrize("handler,body", [
    (web_channel.BriefingRunHandler, {"briefing_date": "invalid"}),
    (web_channel.BriefingRulesHandler, {"match_value": ""}),
    (web_channel.BriefingItemStatusHandler, {"id": "missing", "status": "done"}),
    (web_channel.BriefingItemStatusHandler, {"id": "missing", "status": "bad"}),
    (web_channel.BriefingRuleUpdateHandler, {}),
    (web_channel.BriefingRuleDeleteHandler, {}),
])
def test_validation(api, handler, body):
    assert call(handler, body=body)["status"] == "error"


def test_missing_detail_and_invalid_filter(api):
    assert call(web_channel.BriefingDetailHandler, "GET", args=("missing",))["status"] == "error"
    assert call(web_channel.BriefingsHandler, "GET", params={"kind": "bad", "status": ""})["status"] == "error"


@pytest.mark.parametrize("body", [b"[1]", b"invalid", b"null"])
def test_invalid_json(api, body):
    with patch.object(web_channel.web, "data", return_value=body):
        assert json.loads(web_channel.BriefingRunHandler().POST())["status"] == "error"


def test_auth_failure_precedes_all_operations(api):
    with patch.object(web_channel, "_require_auth", side_effect=RuntimeError("unauthorized")), \
         patch.object(web_channel, "_briefing_service") as service:
        with pytest.raises(RuntimeError, match="unauthorized"):
            web_channel.BriefingRunHandler().POST()
        service.assert_not_called()


def test_settings_do_not_expose_credentials(api, monkeypatch):
    monkeypatch.setenv("IMAP_HOST", "private.example.com")
    monkeypatch.setenv("IMAP_USER", "private-user")
    monkeypatch.setenv("IMAP_PASSWORD", "secret-password")
    monkeypatch.delenv("IMAP_PORT", raising=False)
    result = call(web_channel.BriefingSettingsHandler, "GET")
    assert result["settings"]["configured"] is True
    assert "secret-password" not in json.dumps(result)
    assert result["settings"]["password_set"] is True
    monkeypatch.delenv("IMAP_PASSWORD")
    assert call(web_channel.BriefingSettingsHandler, "GET")["settings"]["missing"] == ["IMAP_PASSWORD"]


def test_settings_save_preserves_password_on_blank_update(api):
    created = call(web_channel.BriefingSettingsHandler, body={"host": "imap.example.com", "user": "ada@example.com", "password": "secret"})
    assert created["status"] == "success"
    assert created["settings"]["configured"] is True
    assert "secret" not in json.dumps(created)
    updated = call(web_channel.BriefingSettingsHandler, body={"password": "", "folder": "Work"})
    assert updated["settings"]["folder"] == "Work"
    assert updated["settings"]["password_set"] is True


def test_revision_endpoint_is_authenticated_and_snapshot_is_immutable(api):
    _, auth = api
    first = call(web_channel.BriefingRunHandler, body={"briefing_date": "2026-09-09", "operation": "create"})
    call(web_channel.BriefingItemStatusHandler, body={"id": first["items"][0]["id"], "status": "done"})
    second = call(web_channel.BriefingRunHandler, body={"briefing_date": "2026-09-09", "operation": "update"})
    snapshot = call(web_channel.BriefingRevisionHandler, "GET", args=(first["briefing"]["id"], "1"))
    assert snapshot["items"][0]["status"] == "undo"
    assert second["items"][0]["status"] == "done"
    assert len(snapshot["revisions"]) == 2
    assert call(web_channel.BriefingRevisionHandler, "GET", args=(first["briefing"]["id"], "99"))["status"] == "error"
    assert auth.call_count == 5
