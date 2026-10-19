"""G5: with the Email / eLearning / Bills plugins on, HTTP and tool paths must not import legacy modules."""

from __future__ import annotations

import importlib
import importlib.abc
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from channel.desktop import desktop_channel as web_channel

# Modules that own (or can construct) the legacy writers / crawlers for these domains.
LEGACY_PREFIXES = (
    "agent.briefing.settings",
    "agent.briefing.elearning",  # elearning_settings and the elearning package
    "agent.briefing.sources.email",
    "agent.briefing.sources.elearning",
    "agent.bills",
)


def _is_legacy(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") or
               (prefix == "agent.briefing.elearning" and name.startswith("agent.briefing.elearning_"))
               for prefix in LEGACY_PREFIXES)


class _Blocker(importlib.abc.MetaPathFinder):
    def __init__(self):
        self.hits: list[str] = []

    def find_spec(self, fullname, path=None, target=None):
        if _is_legacy(fullname):
            self.hits.append(fullname)
            raise ImportError(f"legacy module imported while plugin is on: {fullname}")
        return None


@pytest.fixture
def no_legacy(monkeypatch):
    """Forget already-imported legacy modules and fail any fresh import of them."""
    for name in [n for n in list(sys.modules) if _is_legacy(n)]:
        monkeypatch.delitem(sys.modules, name)
    for parent, attr in (("agent.briefing", "settings"), ("agent.briefing", "elearning_settings"),
                         ("agent.briefing", "elearning"), ("agent", "bills")):
        module = sys.modules.get(parent)
        if module is not None and hasattr(module, attr):
            monkeypatch.delattr(module, attr)
    blocker = _Blocker()
    sys.meta_path.insert(0, blocker)
    try:
        yield blocker
    finally:
        sys.meta_path.remove(blocker)
    assert blocker.hits == []


@pytest.fixture
def plugins_on(monkeypatch, tmp_path):
    monkeypatch.setenv("STELLA_EMAIL_PLUGIN", "1")
    monkeypatch.setenv("STELLA_ELEARNING_PLUGIN", "1")
    monkeypatch.setenv("STELLA_BILLS_PLUGIN", "1")
    monkeypatch.setenv("STELLA_DATA_DIR", str(tmp_path))


class _EmailFacade:
    calls: list = []

    def list_accounts(self):
        self.calls.append(("list_accounts",))
        return {"mailboxes": [{"id": "m1", "configured": True}], "configured": True, "missing": []}

    def save_account(self, payload):
        self.calls.append(("save_account", payload))
        return {"id": "m1", "user": payload.get("user")}

    def delete_account(self, account_id):
        self.calls.append(("delete_account", account_id))

    def test_connection(self, payload):
        self.calls.append(("test_connection", payload))
        return {"connected": True, "folders": ["INBOX"]}


class _ElearningFacade:
    calls: list = []

    def get_settings(self):
        self.calls.append(("get_settings",))
        return {"enabled": True, "username": "student"}

    def save_settings(self, payload):
        self.calls.append(("save_settings", payload))
        return {"enabled": bool(payload.get("enabled")), "username": payload.get("username")}

    def delete_settings(self):
        self.calls.append(("delete_settings",))
        return {"enabled": False, "username": ""}

    def save_file_sync_settings(self, enabled, root):
        self.calls.append(("save_file_sync_settings", enabled, root))
        return {"file_sync_enabled": enabled, "file_sync_root": root}

    def test_connection(self, payload):
        self.calls.append(("test_connection", payload))
        return [{"id": "43", "name": "Course"}]

    def list_courses(self):
        self.calls.append(("list_courses",))
        return [{"id": "43", "name": "Course"}]

    def fetch(self, **kwargs):
        self.calls.append(("fetch", kwargs))
        return {"source_items": [], "total": 0, "next_offset": None, "status": "completed", "errors": []}

    def list_files(self, **kwargs):
        self.calls.append(("list_files", kwargs))
        return {"status": "completed", "total": 0, "files": [], "errors": []}

    def sync_files(self, **kwargs):
        self.calls.append(("sync_files", kwargs))
        return {"status": "completed", "total": 0, "processed": 0, "errors": []}


@pytest.fixture
def facades(monkeypatch):
    email, elearning = _EmailFacade(), _ElearningFacade()
    email.calls, elearning.calls = [], []
    monkeypatch.setattr("core.services.email_facade.EmailPluginFacade", lambda *a, **k: email)
    monkeypatch.setattr("core.services.elearning_facade.ElearningPluginFacade", lambda *a, **k: elearning)
    return SimpleNamespace(email=email, elearning=elearning)


@pytest.fixture
def desktop(monkeypatch):
    monkeypatch.setattr(web_channel, "_require_auth", lambda *a, **k: None)
    monkeypatch.setattr(web_channel.web, "header", lambda *a, **k: None)


def call(handler, method="POST", body=None, params=None):
    with patch.object(web_channel.web, "data", return_value=json.dumps(body or {}).encode()), \
         patch.object(web_channel.web, "input", return_value=SimpleNamespace(**(params or {}))):
        return json.loads(getattr(handler(), method)())


# ---- desktop HTTP: email -------------------------------------------------

def test_email_settings_handlers_use_email_port(plugins_on, facades, desktop, no_legacy):
    got = call(web_channel.BriefingSettingsHandler, "GET")
    assert got == {"status": "success", "settings": {
        "mailboxes": [{"id": "m1", "configured": True}], "configured": True, "missing": []}}

    saved = call(web_channel.BriefingSettingsHandler, body={"user": "ada@example.com"})
    assert saved["status"] == "success"
    assert saved["mailbox"] == {"id": "m1", "user": "ada@example.com"}
    assert saved["settings"]["configured"] is True

    deleted = call(web_channel.BriefingSettingsHandler, body={"action": "delete", "id": "m1"})
    assert deleted["status"] == "success" and "mailbox" not in deleted

    tested = call(web_channel.BriefingSettingsTestHandler, body={"host": "imap.example.com"})
    assert tested == {"status": "success", "connected": True, "folders": ["INBOX"]}

    assert [c[0] for c in facades.email.calls] == [
        "list_accounts", "save_account", "list_accounts", "delete_account", "list_accounts",
        "test_connection"]
    assert no_legacy.hits == []


def test_email_delete_requires_id_when_plugin_on(plugins_on, facades, desktop, no_legacy):
    result = call(web_channel.BriefingSettingsHandler, body={"action": "delete"})
    assert result["status"] == "error"
    assert ("delete_account", None) not in facades.email.calls


# ---- desktop HTTP: eLearning ---------------------------------------------

def test_elearning_settings_handlers_use_elearning_port(plugins_on, facades, desktop, no_legacy):
    got = call(web_channel.BriefingElearningHandler, "GET")
    assert got == {"status": "success", "settings": {"enabled": True, "username": "student"}}

    saved = call(web_channel.BriefingElearningHandler, body={"enabled": True, "username": "student"})
    assert saved["settings"] == {"enabled": True, "username": "student"}

    forbidden = call(web_channel.BriefingElearningHandler, body={"file_sync_root": "/tmp"})
    assert forbidden["status"] == "error"

    removed = call(web_channel.BriefingElearningHandler, body={"action": "delete"})
    assert removed == {"status": "success", "settings": {"enabled": False, "username": ""}}

    assert call(web_channel.BriefingElearningHandler, body={"action": "bogus"})["status"] == "error"

    tested = call(web_channel.BriefingElearningTestHandler, body={"username": "student"})
    assert tested == {"status": "success", "connected": True, "courses": [{"id": "43", "name": "Course"}]}

    sync_get = call(web_channel.ElearningFileSyncSettingsHandler, "GET")
    assert sync_get["settings"]["username"] == "student"
    sync_set = call(web_channel.ElearningFileSyncSettingsHandler,
                    body={"file_sync_enabled": True, "file_sync_root": "/tmp/x"})
    assert sync_set["settings"] == {"file_sync_enabled": True, "file_sync_root": "/tmp/x"}
    assert call(web_channel.ElearningFileSyncSettingsHandler, body={"file_sync_enabled": True})["status"] == "error"

    assert ("save_file_sync_settings", True, "/tmp/x") in facades.elearning.calls
    assert ("delete_settings",) in facades.elearning.calls
    assert no_legacy.hits == []


# ---- source registry used by BriefingRun / Sources handlers --------------

def test_source_registry_uses_plugin_sources_without_legacy_settings(plugins_on, monkeypatch, no_legacy):
    sentinel = [object()]
    monkeypatch.setattr("core.services.email_facade.email_sources", lambda *a, **k: list(sentinel))
    monkeypatch.setattr("core.services.elearning_facade.elearning_sources", lambda *a, **k: [])
    sys.modules.pop("agent.briefing.sources.registry", None)
    registry = importlib.import_module("agent.briefing.sources.registry")
    monkeypatch.setattr(registry, "apple_calendar_connected", lambda: False)
    assert registry.configured_sources() == sentinel
    assert no_legacy.hits == []


def test_source_registry_uses_legacy_sources_when_plugins_off(monkeypatch):
    monkeypatch.delenv("STELLA_EMAIL_PLUGIN", raising=False)
    monkeypatch.delenv("STELLA_ELEARNING_PLUGIN", raising=False)
    from agent.briefing.sources import registry

    monkeypatch.setattr(registry, "apple_calendar_connected", lambda: False)
    monkeypatch.setattr(registry.settings, "email_sources", lambda: ["legacy-mail"])
    monkeypatch.setattr(registry.elearning_settings, "elearning_sources", lambda: ["legacy-el"])
    assert registry.configured_sources() == ["legacy-mail", "legacy-el"]


# ---- desktop HTTP: legacy path still used when plugins are off -----------

def test_settings_handlers_keep_legacy_modules_when_plugins_off(monkeypatch, desktop):
    monkeypatch.delenv("STELLA_EMAIL_PLUGIN", raising=False)
    monkeypatch.delenv("STELLA_ELEARNING_PLUGIN", raising=False)
    seen = []
    monkeypatch.setattr("agent.briefing.settings.public_mailboxes",
                        lambda *a, **k: seen.append("mail") or {"mailboxes": [], "configured": False, "missing": []})
    monkeypatch.setattr("agent.briefing.elearning_settings.public_settings",
                        lambda *a, **k: seen.append("elearning") or {"enabled": False})
    assert call(web_channel.BriefingSettingsHandler, "GET")["settings"]["mailboxes"] == []
    assert call(web_channel.BriefingElearningHandler, "GET")["settings"] == {"enabled": False}
    assert seen == ["mail", "elearning"]


# ---- eLearning tool ------------------------------------------------------

def test_elearning_tool_routes_every_action_through_port(plugins_on, facades, no_legacy):
    from agent.tools.elearning.elearning_tool import ElearningTool

    tool = ElearningTool()
    courses = tool.execute({"action": "courses"})
    assert courses.status == "success"
    assert json.loads(courses.result) == {"courses": [{"id": "43", "name": "Course"}]}

    fetched = tool.execute({"action": "fetch", "since": "2026-01-01T00:00:00Z", "limit": 5})
    assert json.loads(fetched.result)["source_items"] == []
    listed = tool.execute({"action": "list_files", "file_extensions": ["pdf"], "limit": 50})
    assert json.loads(listed.result)["files"] == []
    synced = tool.execute({"action": "sync_files", "layout": "courseware", "course_ids": ["43"]})
    assert json.loads(synced.result)["status"] == "completed"

    assert facades.elearning.calls == [
        ("list_courses",),
        ("fetch", {"since": "2026-01-01T00:00:00Z", "limit": 5}),
        ("list_files", {"file_extensions": ["pdf"], "limit": 50}),
        ("sync_files", {"course_ids": ["43"], "layout": "courseware"}),
    ]
    assert no_legacy.hits == []


def test_elearning_tool_plugin_errors_become_tool_failures(plugins_on, facades, no_legacy):
    from agent.tools.elearning.elearning_tool import ElearningTool

    def failing(**_):
        raise ValueError("请先在 eLearning 设置中配置账号和登录凭据")

    facades.elearning.fetch = failing
    result = ElearningTool().execute({"action": "fetch"})
    assert result.status == "error"
    assert "请先在 eLearning 设置中配置账号和登录凭据" in str(result.result)
    assert ElearningTool().execute({"action": "nope"}).status == "error"
    assert ElearningTool().execute("bad").status == "error"
    assert no_legacy.hits == []


def test_elearning_tool_plugin_runtime_failure_is_generic(plugins_on, facades, no_legacy):
    from agent.tools.elearning.elearning_tool import ElearningTool

    def broken():
        raise RuntimeError("secret detail")

    facades.elearning.list_courses = broken
    result = ElearningTool().execute({"action": "courses"})
    assert result.status == "error"
    assert "secret detail" not in str(result.result)


def test_elearning_tool_uses_legacy_crawler_when_plugin_off(monkeypatch):
    monkeypatch.delenv("STELLA_ELEARNING_PLUGIN", raising=False)
    from agent.tools.elearning.elearning_tool import ElearningTool

    monkeypatch.setattr("application.Application.port",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("port used with plugin off")))
    monkeypatch.setattr("agent.briefing.elearning_settings.load_settings", lambda: {})
    result = ElearningTool().execute({"action": "courses"})
    assert result.status == "error"
    assert "请先在 eLearning 设置中配置账号和登录凭据" in str(result.result)


# ---- Bills tool and export ----------------------------------------------

def test_bills_tool_wall_time_does_not_import_agent_bills(plugins_on, no_legacy):
    from agent.tools.bills import bills_tool

    assert bills_tool._wall_time("2026-08-02T12:30:00+08:00") == "2026-08-02 12:30"
    assert bills_tool._wall_time("2026-08-02T04:30:00Z") == "2026-08-02 04:30"
    assert bills_tool._wall_time("garbage") == "garbage"
    assert no_legacy.hits == []


def test_bills_export_handler_renders_plugin_rows_without_agent_bills(plugins_on, desktop, monkeypatch, no_legacy):
    rows = [{"id": "b1", "occurred_at": "2026-08-02T12:30:00+08:00", "entry_type": "expense",
             "name": "午餐", "category": "消费", "amount_minor": 3250, "currency": "CNY",
             "note": "", "status": "posted"}]
    seen = {}

    class _Bills:
        def list_ledger_between(self, start, end):
            seen["range"] = (start, end)
            return rows

    monkeypatch.setattr(web_channel, "_bills_service", lambda: _Bills())
    headers = {}
    monkeypatch.setattr(web_channel.web, "header", lambda key, value: headers.__setitem__(key, value))
    with patch.object(web_channel.web, "input",
                      return_value=SimpleNamespace(start="2026-08-01", end="2026-08-31", lang="en")):
        data = web_channel.BillsLedgerExportHandler().GET()
    assert isinstance(data, bytes) and data[:2] == b"PK"
    assert seen["range"] == ("2026-08-01", "2026-08-31")
    assert headers["Content-Disposition"] == 'attachment; filename="bills-2026-08-01-2026-08-31.xlsx"'
    assert headers["Content-Length"] == str(len(data))
    assert no_legacy.hits == []


def test_legacy_bills_export_module_is_the_core_implementation():
    from agent.bills import export as legacy
    from core.services import bills_public

    assert legacy.build_ledger_xlsx is bills_public.build_ledger_xlsx
