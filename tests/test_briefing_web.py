"""Authenticated briefing handlers with a real isolated SQLite service."""
from datetime import datetime, timezone
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.usefixtures("deterministic_briefing_generator")
from agent.briefing.pipeline import BriefingPipeline
from agent.briefing.service import BriefingService
from agent.briefing.sources.base import FetchedItem
from briefing_fakes import StaticSource
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
    assert ran["briefing"]["mail_snapshot_available"] is True
    assert ran["mail"][0]["title"] == "请确认合同"
    assert ran["mail"][0]["category"] == "selected"
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


def test_markdown_rule_api_and_default_template(api):
    text = "# 排除\n排除发件地址以 @promo.example 结尾的邮件。\n# 输出\n只写有价值的行动建议。"
    created = call(web_channel.BriefingRulesHandler, body={"text": text})
    assert created["status"] == "success"
    assert created["rule"]["text"] == text
    listed = call(web_channel.BriefingRulesHandler, "GET")
    assert "## 筛选原则" in listed["default_text"]
    assert listed["rules"][0]["text"] == text
    edited = call(web_channel.BriefingRuleUpdateHandler, body={"id": created["rule"]["id"], "text": "保留课程通知。", "enabled": False})
    assert edited["rule"]["text"] == "保留课程通知。" and not edited["rule"]["enabled"]
    assert call(web_channel.BriefingRulesHandler, body={"text": " "})["status"] == "error"


def test_source_selection_is_passed_to_pipeline_and_source_discovery_is_authenticated(api):
    _, auth = api
    source = SimpleNamespace(name="elearning", account_id="school", display_name="eLearning")
    with patch("agent.briefing.sources.registry.configured_sources", return_value=[source]):
        result = call(web_channel.BriefingSourcesHandler, "GET")
    assert result["sources"] == [{"id": "elearning:school", "source": "elearning", "account_id": "school", "name": "eLearning"}]
    with patch.object(web_channel, "_briefing_pipeline") as factory:
        factory.return_value.run.return_value = {"briefing": {"id": "briefing"}}
        result = call(web_channel.BriefingRunHandler, body={"operation": "update", "sources": ["elearning:school"]})
        assert result["status"] == "success"
        assert factory.return_value.run.call_args.kwargs["sources"] == ["elearning:school"]
    assert auth.call_count == 2


def test_elearning_settings_api_masks_credentials_and_loads_courses_only_on_test(api, tmp_path):
    from agent.briefing import elearning_settings
    with patch.object(elearning_settings, "settings_path", return_value=tmp_path / "elearning.json"):
        created = call(web_channel.BriefingElearningHandler, body={"enabled": True, "base_url": "https://elearning.fudan.edu.cn",
            "username": "student", "password": "campus-secret", "courses": ["42"]})
        assert created["status"] == "success" and created["settings"]["configured"]
        assert "campus-secret" not in json.dumps(created)
        updated = call(web_channel.BriefingElearningHandler, body={"password": "********", "enabled": False})
        assert updated["settings"]["enabled"] is False
        with patch.object(elearning_settings, "check_connection", return_value=[{"id": "42", "name": "课程"}]) as check:
            tested = call(web_channel.BriefingElearningTestHandler, body={"username": "student"})
            assert tested["connected"] and tested["courses"][0]["id"] == "42"
            check.assert_called_once_with({"username": "student"})
        removed = call(web_channel.BriefingElearningHandler, body={"action": "delete"})
        assert not removed["settings"]["configured"]
        assert call(web_channel.BriefingElearningHandler, body={"action": "unknown"})["status"] == "error"


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
    assert result["settings"]["mailboxes"][0]["password_set"] is True
    assert result["settings"]["mailboxes"][0]["password_masked"] == "********"
    monkeypatch.delenv("IMAP_PASSWORD")
    assert call(web_channel.BriefingSettingsHandler, "GET")["settings"]["mailboxes"][0]["missing"] == ["IMAP_PASSWORD"]


def test_settings_save_preserves_password_on_blank_update(api):
    created = call(web_channel.BriefingSettingsHandler, body={"host": "imap.example.com", "user": "ada@example.com", "password": "secret"})
    assert created["status"] == "success"
    assert created["settings"]["configured"] is True
    assert "secret" not in json.dumps(created)
    updated = call(web_channel.BriefingSettingsHandler, body={"password": "", "folder": "Work"})
    assert updated["settings"]["mailboxes"][0]["folder"] == "Work"
    assert updated["settings"]["mailboxes"][0]["password_set"] is True


def test_mailbox_crud_and_masked_passwords(api):
    first = call(web_channel.BriefingSettingsHandler, body={"action": "add", "host": "imap.example.com", "user": "ada@example.com", "password": "first-secret"})
    second = call(web_channel.BriefingSettingsHandler, body={"action": "add", "host": "imap.example.com", "user": "bob@example.com", "password": "second-secret"})
    assert len(second["settings"]["mailboxes"]) == 2
    mailbox_id = first["mailbox"]["id"]
    updated = call(web_channel.BriefingSettingsHandler, body={"id": mailbox_id, "password": "********", "folder": "Work"})
    assert updated["mailbox"]["folder"] == "Work"
    assert updated["mailbox"]["password_masked"] == "********"
    assert "first-secret" not in json.dumps(updated)
    assert "second-secret" not in json.dumps(updated)
    disabled = call(web_channel.BriefingSettingsHandler, body={"id": mailbox_id, "enabled": False})
    assert not disabled["mailbox"]["enabled"] and disabled["mailbox"]["password_set"]
    with patch("agent.briefing.elearning_settings.elearning_sources", return_value=[]):
        enabled_sources = call(web_channel.BriefingSourcesHandler, "GET")["sources"]
    assert len(enabled_sources) == 1 and "bob@example.com" in enabled_sources[0]["name"]
    deleted = call(web_channel.BriefingSettingsHandler, body={"action": "delete", "id": mailbox_id})
    assert deleted["settings"]["mailboxes"] == [second["mailbox"]]
    assert call(web_channel.BriefingSettingsHandler, body={"action": "delete", "id": mailbox_id})["status"] == "error"


def test_revision_endpoint_is_authenticated_and_snapshot_is_immutable(api):
    _, auth = api
    first = call(web_channel.BriefingRunHandler, body={"briefing_date": "2026-09-09", "operation": "create"})
    call(web_channel.BriefingItemStatusHandler, body={"id": first["items"][0]["id"], "status": "done"})
    second = call(web_channel.BriefingRunHandler, body={"briefing_date": "2026-09-09", "operation": "update"})
    snapshot = call(web_channel.BriefingRevisionHandler, "GET", args=(first["briefing"]["id"], "1"))
    assert snapshot["items"][0]["status"] == "undo"
    assert snapshot["mail"] == first["mail"]
    assert second["items"][0]["status"] == "done"
    assert len(snapshot["revisions"]) == 2
    assert call(web_channel.BriefingRevisionHandler, "GET", args=(first["briefing"]["id"], "99"))["status"] == "error"
    assert auth.call_count == 5


def test_connection_endpoint_reports_success_and_configuration_errors(api):
    _, auth = api
    with patch("agent.briefing.settings.check_mailbox_connection") as check:
        check.return_value = {"connected": True, "folder_accessible": False,
                              "folders": [{"name": "INBOX", "label": "INBOX"}], "message": "select denied"}
        result = call(web_channel.BriefingSettingsTestHandler, body={"host": "imap.gmail.com", "password": ""})
        assert result["status"] == "success" and result["connected"] is True
        assert result["folders"] == [{"name": "INBOX", "label": "INBOX"}]
        assert result["message"] == "select denied"
        check.assert_called_once_with({"host": "imap.gmail.com", "password": ""})
        check.side_effect = ValueError("无法解析 IMAP 服务器")
        result = call(web_channel.BriefingSettingsTestHandler)
        assert result == {"status": "error", "message": "无法解析 IMAP 服务器"}
    assert auth.call_count == 2
