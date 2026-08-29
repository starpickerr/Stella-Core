"""Bills HTTP handlers in the Web channel."""

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

from agent.bills.service import BillsService
from agent.bills.store import BillStore

# Keep this unit test independent from the optional web.py dependency.
if "web" not in sys.modules:
    web_stub = types.ModuleType("web")
    web_stub.HTTPError = type("HTTPError", (Exception,), {})
    web_stub.cookies = lambda: {}
    web_stub.header = lambda *args, **kwargs: None
    web_stub.data = lambda: b"{}"
    web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
    web_stub.setcookie = lambda *args, **kwargs: None
    web_stub.seeother = lambda *args, **kwargs: Exception("seeother")
    web_stub.notfound = lambda *args, **kwargs: Exception("notfound")
    web_stub.badrequest = lambda *args, **kwargs: Exception("badrequest")
    web_stub.application = lambda *args, **kwargs: types.SimpleNamespace(wsgifunc=lambda: None)
    web_stub.httpserver = types.SimpleNamespace(
        LogMiddleware=type("LogMiddleware", (), {"log": lambda *args, **kwargs: None}),
        StaticMiddleware=lambda app: app,
        WSGIServer=lambda *args, **kwargs: types.SimpleNamespace(serve_forever=lambda: None),
    )
    sys.modules["web"] = web_stub

from channel.web import web_channel

ROOT = Path(__file__).parents[1]


def _service(tmp_path) -> BillsService:
    return BillsService(BillStore(tmp_path / "bills.db"))


def _lunch(**extra):
    payload = {
        "name": "午餐",
        "category": "消费",
        "entry_type": "expense",
        "amount_minor": 3200,
        "occurred_at": "2026-08-02T12:30:00+08:00",
    }
    payload.update(extra)
    return payload


def test_ledger_create_list_update_delete(tmp_path):
    svc = _service(tmp_path)

    with patch("channel.web.web_channel._require_auth") as require_auth, \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel.web.data", return_value=json.dumps(_lunch()).encode()), \
         patch("channel.web.web_channel._bills_service", return_value=svc):
        created = json.loads(web_channel.BillsLedgerHandler().POST())

    require_auth.assert_called_once_with()
    assert created["status"] == "success"
    entry_id = created["entry"]["id"]
    assert created["entry"]["name"] == "午餐"
    assert created["entry"]["amount_minor"] == 3200

    with patch("channel.web.web_channel._require_auth"), \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel.web.input",
               return_value=types.SimpleNamespace(year="2026", month="8")), \
         patch("channel.web.web_channel._bills_service", return_value=svc):
        listed = json.loads(web_channel.BillsLedgerHandler().GET())

    assert listed["status"] == "success"
    assert [row["id"] for row in listed["entries"]] == [entry_id]

    with patch("channel.web.web_channel._require_auth"), \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel.web.data",
               return_value=json.dumps({"id": entry_id, "amount_minor": 5000}).encode()), \
         patch("channel.web.web_channel._bills_service", return_value=svc):
        updated = json.loads(web_channel.BillsLedgerUpdateHandler().POST())

    assert updated["status"] == "success"
    assert updated["entry"]["amount_minor"] == 5000

    with patch("channel.web.web_channel._require_auth"), \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel.web.data",
               return_value=json.dumps({"id": entry_id}).encode()), \
         patch("channel.web.web_channel._bills_service", return_value=svc):
        deleted = json.loads(web_channel.BillsLedgerDeleteHandler().POST())

    assert deleted == {"status": "success"}
    assert svc.list_ledger(2026, 8) == []


def test_ledger_get_requires_year_and_month(tmp_path):
    svc = _service(tmp_path)
    with patch("channel.web.web_channel._require_auth"), \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel.web.input",
               return_value=types.SimpleNamespace(year="", month="")), \
         patch("channel.web.web_channel._bills_service", return_value=svc):
        response = json.loads(web_channel.BillsLedgerHandler().GET())

    assert response["status"] == "error"
    assert "year and month" in response["message"]


def test_ledger_create_rejects_invalid_payload(tmp_path):
    svc = _service(tmp_path)
    with patch("channel.web.web_channel._require_auth"), \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel.web.data",
               return_value=json.dumps({"name": "", "amount_minor": 100}).encode()), \
         patch("channel.web.web_channel._bills_service", return_value=svc):
        response = json.loads(web_channel.BillsLedgerHandler().POST())

    assert response["status"] == "error"
    assert "name" in response["message"]


def test_statements_list_and_detail(tmp_path):
    svc = _service(tmp_path)
    svc.create_ledger(_lunch())
    svc.create_ledger(
        {
            "name": "月薪",
            "category": "工资",
            "entry_type": "income",
            "amount_minor": 1200000,
            "occurred_at": "2026-08-01T09:00:00+08:00",
        }
    )

    with patch("channel.web.web_channel._require_auth"), \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel.web.input",
               return_value=types.SimpleNamespace(period_type="monthly", year="2026")), \
         patch("channel.web.web_channel._bills_service", return_value=svc):
        listed = json.loads(web_channel.BillsStatementsHandler().GET())

    assert listed["status"] == "success"
    assert len(listed["statements"]) == 1
    statement_id = listed["statements"][0]["id"]
    assert listed["statements"][0]["income_minor"] == 1200000
    assert listed["statements"][0]["expense_minor"] == 3200

    with patch("channel.web.web_channel._require_auth"), \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel._bills_service", return_value=svc):
        detail = json.loads(web_channel.BillsStatementDetailHandler().GET(statement_id))

    assert detail["status"] == "success"
    assert detail["statement"]["id"] == statement_id
    names = {(item["category"], item["name"], item["entry_type"])
             for item in detail["statement"]["items"]}
    assert ("消费", "午餐", "expense") in names
    assert ("工资", "月薪", "income") in names


def test_statement_detail_not_found(tmp_path):
    svc = _service(tmp_path)
    with patch("channel.web.web_channel._require_auth"), \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel._bills_service", return_value=svc):
        response = json.loads(
            web_channel.BillsStatementDetailHandler().GET("stmt-missing")
        )

    assert response["status"] == "error"
    assert "not found" in response["message"]


def test_update_and_delete_require_id(tmp_path):
    svc = _service(tmp_path)
    with patch("channel.web.web_channel._require_auth"), \
         patch("channel.web.web_channel.web.header"), \
         patch("channel.web.web_channel.web.data", return_value=b"{}"), \
         patch("channel.web.web_channel._bills_service", return_value=svc):
        updated = json.loads(web_channel.BillsLedgerUpdateHandler().POST())
        deleted = json.loads(web_channel.BillsLedgerDeleteHandler().POST())

    assert updated == {"status": "error", "message": "id required"}
    assert deleted == {"status": "error", "message": "id required"}


def test_bills_routes_are_wired_in_web_and_desktop():
    web_source = (ROOT / "channel/web/web_channel.py").read_text(encoding="utf-8")
    desktop_client = (ROOT / "desktop/src/renderer/src/api/client.ts").read_text(
        encoding="utf-8"
    )

    assert "'/api/bills/ledger', 'BillsLedgerHandler'" in web_source
    assert "'/api/bills/ledger/update', 'BillsLedgerUpdateHandler'" in web_source
    assert "'/api/bills/ledger/delete', 'BillsLedgerDeleteHandler'" in web_source
    assert "'/api/bills/statements', 'BillsStatementsHandler'" in web_source
    assert "'/api/bills/statements/(.*)', 'BillsStatementDetailHandler'" in web_source

    assert "async getLedgerEntries(" in desktop_client
    assert "'/api/bills/ledger'" in desktop_client
    assert "'/api/bills/ledger/update'" in desktop_client
    assert "'/api/bills/ledger/delete'" in desktop_client
    assert "async getPeriodStatements(" in desktop_client
    assert "async getPeriodStatement(" in desktop_client
    assert "/api/bills/statements" in desktop_client
