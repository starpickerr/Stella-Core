"""Business logic for the bills module.

The store talks to SQLite. This layer validates input, maps the UI/tool payload
onto ledger rows, and rebuilds monthly / yearly snapshots from posted entries.
There is no generic ``bill`` table — callers create ledger entries, and
period statements are derived.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from .store import BillStore, get_bill_store

_ENTRY_TYPES = {"income", "expense"}
_LEDGER_STATUSES = {"pending", "posted", "reversed"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_occurred_at(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("occurred_at is required")
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid occurred_at: {value}") from exc
    return dt


def _year_month(occurred_at: str) -> tuple[int, int]:
    dt = parse_occurred_at(occurred_at)
    return dt.year, dt.month


def _occurred_date(occurred_at: str) -> date:
    return parse_occurred_at(occurred_at).date()


def parse_date(value: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("date is required")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"invalid date: {value}") from exc


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    start = datetime(year, month, 1)
    if month == 12:
         end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def _year_bounds(year: int) -> tuple[str, str]:
    return datetime(year, 1, 1).isoformat(), datetime(year + 1, 1, 1).isoformat()


def _default_status(year: int, month: Optional[int] = None) -> str:
    now = datetime.now()
    if month is None:
        return "open" if year == now.year else "closed"
    if (year, month) >= (now.year, now.month):
        return "open"
    return "closed"


def _monthly_id(year: int, month: int, currency: str) -> str:
    return f"stmt-{year}-{month:02d}-{currency}"


def _yearly_id(year: int, currency: str) -> str:
    return f"stmt-{year}-{currency}"


class BillsService:
    def __init__(self, store: Optional[BillStore] = None):
        self.store = store if store is not None else get_bill_store()

    # ------------------------------------------------------------------
    # Ledger (明细)
    # ------------------------------------------------------------------

    def list_ledger(self, year: int, month: int) -> list:
        if month < 1 or month > 12:
            raise ValueError("month must be 1–12")
        return [
            row
            for row in self.store.list_ledgers()
            if _year_month(row["occurred_at"]) == (year, month)
        ]

    def list_ledger_between(self, start: str, end: str) -> list:
        start_d = parse_date(start)
        end_d = parse_date(end)
        if start_d > end_d:
            raise ValueError("start must be on or before end")
        return [
            row
            for row in self.store.list_ledgers()
            if start_d <= _occurred_date(row["occurred_at"]) <= end_d
        ]

    def get_ledger(self, entry_id: str) -> Optional[dict]:
        return self.store.get_ledger(entry_id)

    def create_ledger(self, payload: dict, *, idempotency_key: Optional[str] = None) -> dict:
        digest = _request_digest("create_ledger", payload)
        with self.store.transaction():
            existing_op = self._reuse_or_conflict(idempotency_key, "create_ledger", digest)
            if existing_op is not None:
                return existing_op
            entry = self._build_ledger(payload, existing=None)
            entry["revision"] = 1
            saved = self.store.insert_ledger(entry)
            self._refresh_periods(saved["occurred_at"], saved["currency"])
            self._save_receipt(idempotency_key, "create_ledger", digest, saved["id"])
            return saved

    def update_ledger(
        self,
        entry_id: str,
        payload: dict,
        *,
        expected_revision: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        digest = _request_digest(
            "update_ledger",
            {"id": entry_id, "patch": payload, "expectedRevision": expected_revision},
        )
        with self.store.transaction():
            existing_op = self._reuse_or_conflict(idempotency_key, "update_ledger", digest)
            if existing_op is not None:
                return existing_op
            existing = self.store.get_ledger(entry_id)
            if existing is None:
                raise KeyError(f"ledger entry not found: {entry_id}")
            current_rev = int(existing.get("revision") or 1)
            if expected_revision is not None and int(expected_revision) != current_rev:
                raise ValueError(
                    f"revision conflict: expected {expected_revision}, have {current_rev}"
                )
            entry = self._build_ledger(payload, existing=existing)
            entry["revision"] = current_rev + 1
            saved = self.store.update_ledger(entry)
            self._refresh_periods(
                saved["occurred_at"],
                saved["currency"],
                also=existing["occurred_at"],
                also_currency=existing["currency"],
            )
            self._save_receipt(idempotency_key, "update_ledger", digest, saved["id"])
            return saved

    def delete_ledger(
        self,
        entry_id: str,
        *,
        expected_revision: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> None:
        digest = _request_digest(
            "delete_ledger",
            {"id": entry_id, "expectedRevision": expected_revision},
        )
        with self.store.transaction():
            if idempotency_key:
                prior = self.store.get_operation_receipt(idempotency_key)
                if prior is not None:
                    if prior["request_digest"] != digest:
                        raise ValueError("idempotency conflict: different payload for key")
                    return
            existing = self.store.get_ledger(entry_id)
            if existing is None:
                raise KeyError(f"ledger entry not found: {entry_id}")
            current_rev = int(existing.get("revision") or 1)
            if expected_revision is not None and int(expected_revision) != current_rev:
                raise ValueError(
                    f"revision conflict: expected {expected_revision}, have {current_rev}"
                )
            self.store.delete_ledger(entry_id)
            self._refresh_periods(existing["occurred_at"], existing["currency"])
            self._save_receipt(idempotency_key, "delete_ledger", digest, entry_id)

    def get_operation(self, operation_id: str) -> Optional[dict]:
        return self.store.get_operation_receipt(operation_id)

    def _reuse_or_conflict(
        self, idempotency_key: Optional[str], method: str, digest: str
    ) -> Optional[dict]:
        if not idempotency_key:
            return None
        prior = self.store.get_operation_receipt(idempotency_key)
        if prior is None:
            return None
        if prior["request_digest"] != digest:
            raise ValueError("idempotency conflict: different payload for key")
        if prior.get("result_id"):
            row = self.store.get_ledger(prior["result_id"])
            if row is not None:
                return row
        return {"id": prior.get("result_id"), "operationId": idempotency_key}

    def _save_receipt(
        self,
        idempotency_key: Optional[str],
        method: str,
        digest: str,
        result_id: str,
    ) -> None:
        if not idempotency_key:
            return
        now = _now_iso()
        self.store.put_operation_receipt(
            {
                "operation_id": idempotency_key,
                "method": method,
                "request_digest": digest,
                "status": "succeeded",
                "result_id": result_id,
                "error_code": None,
                "created_at": now,
                "updated_at": now,
            }
        )
    # ------------------------------------------------------------------
    # Period statements (月 / 年账单)
    # ------------------------------------------------------------------

    def list_statements(
        self, period_type: Optional[str] = None, year: Optional[int] = None
    ) -> list:
        if period_type not in (None, "monthly", "yearly"):
            raise ValueError("period_type must be monthly or yearly")
        return self.store.list_statements(period_type, year)

    def get_statement(self, statement_id: str) -> Optional[dict]:
        statement = self.store.get_statement(statement_id)
        if statement is None:
            return None
        statement["items"] = self.store.list_statement_items(statement_id)
        return statement

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_ledger(self, payload: dict, existing: Optional[dict]) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("ledger payload must be an object")

        name = str(payload.get("name", existing["name"] if existing else "")).strip()
        if not name:
            raise ValueError("name is required")

        amount_minor = payload.get("amount_minor", existing["amount_minor"] if existing else None)
        try:
            amount_minor = int(amount_minor)
        except (TypeError, ValueError):
            raise ValueError("amount_minor must be an integer") from None
        if amount_minor <= 0:
            raise ValueError("amount_minor must be positive")

        entry_type = payload.get("entry_type", existing["entry_type"] if existing else None)
        if entry_type not in _ENTRY_TYPES:
            raise ValueError("entry_type must be income or expense")

        occurred_at = payload.get("occurred_at", existing["occurred_at"] if existing else None)
        parse_occurred_at(occurred_at)

        status = payload.get("status", existing["status"] if existing else "posted")
        if status not in _LEDGER_STATUSES:
            raise ValueError("status must be pending, posted, or reversed")

        now = _now_iso()
        category = str(payload.get("category", existing["category"] if existing else "") or "")
        txn_type = str(
            payload.get(
                "txn_type",
                existing["txn_type"] if existing else category,
            )
            or ""
        )
        return {
            "id": existing["id"] if existing else str(uuid.uuid4()),
            "amount_minor": amount_minor,
            "currency": str(
                payload.get("currency", existing["currency"] if existing else "CNY") or "CNY"
            ),
            "category": category,
            "name": name,
            "note": str(payload.get("note", existing["note"] if existing else "") or ""),
            "entry_type": entry_type,
            "txn_type": txn_type,
            "counterparty": str(
                payload.get("counterparty", existing["counterparty"] if existing else "") or ""
            ),
            "occurred_at": occurred_at,
            "status": status,
            "account_id": payload.get(
                "account_id", existing.get("account_id") if existing else None
            ),
            "planned_payment_id": payload.get(
                "planned_payment_id",
                existing.get("planned_payment_id") if existing else None,
            ),
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
            "revision": int(existing.get("revision") or 1) if existing else 1,
        }

    def _refresh_periods(
        self,
        occurred_at: str,
        currency: str,
        also: Optional[str] = None,
        also_currency: Optional[str] = None,
    ) -> None:
        seen = set()
        targets = [(occurred_at, currency)]
        if also:
            targets.append((also, also_currency or currency))
        for iso, cur in targets:
            year, month = _year_month(iso)
            key = (year, month, cur)
            if key in seen:
                continue
            seen.add(key)
            self._rebuild_month(year, month, cur)
            self._rebuild_year(year, cur)

    def _rebuild_month(self, year: int, month: int, currency: str) -> None:
        rows = [
            row
            for row in self.store.list_ledgers()
            if row["status"] == "posted"
            and row["currency"] == currency
            and _year_month(row["occurred_at"]) == (year, month)
        ]
        existing = self.store.get_statement_by_period("monthly", year, month, currency)
        if not rows:
            if existing:
                self.store.delete_statement(existing["id"])
            return
        start_at, end_at = _month_bounds(year, month)
        self._write_statement(
            existing=existing,
            statement_id=_monthly_id(year, month, currency) if existing is None else existing["id"],
            period_type="monthly",
            year=year,
            month=month,
            start_at=start_at,
            end_at=end_at,
            currency=currency,
            rows=rows,
            status=_default_status(year, month) if existing is None else existing["status"],
        )

    def _rebuild_year(self, year: int, currency: str) -> None:
        rows = [
            row
            for row in self.store.list_ledgers()
            if row["status"] == "posted"
            and row["currency"] == currency
            and _year_month(row["occurred_at"])[0] == year
        ]
        existing = self.store.get_statement_by_period("yearly", year, None, currency)
        if not rows:
            if existing:
                self.store.delete_statement(existing["id"])
            return
        start_at, end_at = _year_bounds(year)
        self._write_statement(
            existing=existing,
            statement_id=_yearly_id(year, currency) if existing is None else existing["id"],
            period_type="yearly",
            year=year,
            month=None,
            start_at=start_at,
            end_at=end_at,
            currency=currency,
            rows=rows,
            status=_default_status(year) if existing is None else existing["status"],
        )

    def _write_statement(
        self,
        *,
        existing: Optional[dict],
        statement_id: str,
        period_type: str,
        year: int,
        month: Optional[int],
        start_at: str,
        end_at: str,
        currency: str,
        rows: list,
        status: str,
    ) -> None:
        now = _now_iso()
        income = sum(row["amount_minor"] for row in rows if row["entry_type"] == "income")
        expense = sum(row["amount_minor"] for row in rows if row["entry_type"] == "expense")
        self.store.upsert_statement(
            {
                "id": statement_id,
                "period_type": period_type,
                "year": year,
                "month": month,
                "start_at": start_at,
                "end_at": end_at,
                "currency": currency,
                "income_minor": income,
                "expense_minor": expense,
                "net_minor": income - expense,
                "status": status,
                "note": existing["note"] if existing else "",
                "generated_at": now,
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
            }
        )
        buckets: dict[tuple, dict] = {}
        for row in rows:
            key = (row["category"], row["name"], row["entry_type"])
            bucket = buckets.setdefault(
                key,
                {
                    "id": str(uuid.uuid4()),
                    "category": row["category"],
                    "name": row["name"],
                    "entry_type": row["entry_type"],
                    "amount_minor": 0,
                    "entry_count": 0,
                },
            )
            bucket["amount_minor"] += row["amount_minor"]
            bucket["entry_count"] += 1
        self.store.replace_statement_items(statement_id, list(buckets.values()))

def _request_digest(method: str, payload: dict) -> str:
    encoded = json.dumps({"method": method, "payload": payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

