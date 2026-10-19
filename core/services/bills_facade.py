"""Compatibility facade: same method surface as BillsService, routed to plugin RPC."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from core.services import bills_gateway


def _db_path() -> Path:
    # Path only: instantiating agent.bills.store would apply the legacy schema.sql,
    # which frozen builds no longer ship and which the plugin owns.
    from common.state_dir import bills_db

    return Path(bills_db())


class BillsPluginFacade:
    """Drop-in for Application._Port when STELLA_BILLS_PLUGIN is enabled."""

    def list_ledger(self, year: int, month: int) -> list:
        return self._value("list_ledger", {"year": year, "month": month})

    def list_ledger_between(self, start: str, end: str) -> list:
        return self._value("list_ledger_between", {"start": start, "end": end})

    def get_ledger(self, entry_id: str) -> Optional[dict]:
        return self._value("get_ledger", {"id": entry_id})

    def create_ledger(self, payload: dict) -> dict:
        body = dict(payload)
        body.setdefault("idempotencyKey", body.get("id") or body.get("name"))
        return self._value("create_ledger", body, write=True)

    def update_ledger(self, entry_id: str, payload: dict) -> dict:
        return self._value(
            "update_ledger",
            {"id": entry_id, "patch": payload, "idempotencyKey": entry_id},
            write=True,
        )

    def delete_ledger(self, entry_id: str) -> None:
        self._value(
            "delete_ledger",
            {"id": entry_id, "idempotencyKey": entry_id},
            write=True,
        )

    def list_statements(
        self, period_type: Optional[str] = None, year: Optional[int] = None
    ) -> list:
        return self._value(
            "list_statements",
            {"period_type": period_type, "year": year},
        )

    def get_statement(self, statement_id: str) -> Optional[dict]:
        return self._value("get_statement", {"id": statement_id})

    def _value(self, method: str, params: dict[str, Any], *, write: bool = False) -> Any:
        result = bills_gateway.invoke_bills(method, params, db_path=_db_path())
        status = result.get("status")
        if status == "failed":
            err = result.get("error") or {}
            code = err.get("code")
            message = err.get("message") or "bills plugin call failed"
            if code == "not_found":
                raise KeyError(message)
            raise ValueError(message)
        if status != "succeeded":
            raise RuntimeError(f"bills plugin returned {status}")
        return result.get("value")
