"""Facade over the stella.email MCP for desktop settings and the briefing pipeline.

``EmailMcpFacade`` exposes the public contract and mailbox method aliases. ``EmailMcpSource``
implements the briefing ``Source`` protocol so the pipeline can fetch without
ever holding IMAP credentials.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from core.services import email_gateway


def _paths() -> tuple[Path, Path]:
    from common.state_dir import briefing_db

    briefing = briefing_db(ensure=False)
    return briefing.parent.parent / "email" / "email.db", briefing.with_name("mailbox.json")


def _unwrap(result: dict[str, Any]) -> Any:
    status = result.get("status")
    if status == "failed":
        err = result.get("error") or {}
        message = err.get("message") or "email MCP call failed"
        if err.get("code") == "not_found":
            raise KeyError(message)
        raise ValueError(message)
    if status != "succeeded":
        raise RuntimeError(f"email MCP returned {status}")
    return result.get("value")


class EmailMcpFacade:
    """Drop-in for Application._Port over the managed email MCP connection."""

    def __init__(self, *, purpose: str | None = None):
        self._purpose = purpose

    def __getattr__(self, name: str):
        names = email_gateway.EMAIL_METHOD_PARAMS.get(name)
        if names is None:
            raise AttributeError(name)

        def call(*args: Any, **kwargs: Any) -> Any:
            if len(args) > len(names):
                raise TypeError(f"{name}() takes at most {len(names)} arguments")
            params = dict(zip(names, args))
            for key, value in kwargs.items():
                if key not in names:
                    raise TypeError(f"{name}() got an unexpected keyword argument {key!r}")
                if key in params:
                    raise TypeError(f"{name}() got multiple values for argument {key!r}")
                params[key] = value
            return self._value(name, params)

        call.__name__ = name
        return call

    def _value(self, method: str, params: dict[str, Any]) -> Any:
        return _unwrap(email_gateway.invoke_email(method, params, purpose=self._purpose))

    # ---- mailbox method aliases ------------------------
    def public_mailboxes(self) -> dict:
        return self.list_accounts()

    def save_mailbox(self, payload: dict) -> dict:
        return self.save_account(payload)

    def delete_mailbox(self, account_id: str) -> None:
        self.delete_account(account_id)

    def check_mailbox_connection(self, payload: dict) -> dict:
        return self.test_connection(payload)


class EmailMcpSource:
    """Briefing ``Source`` backed by one MCP-owned mailbox (no secrets held)."""

    name = "email"

    def __init__(self, *, mailbox_id: str, account_id: str, display_name: str = "email",
                 purpose: str = "background", facade: EmailMcpFacade | None = None):
        self.mailbox_id = mailbox_id
        self.account_id = account_id
        self.display_name = display_name
        self._facade = facade or EmailMcpFacade(purpose=purpose)

    def fetch(self, cursors: Dict[str, str]):
        from core.services.source_types import FetchedItem, FetchResult

        cursors = dict(cursors)
        extra = {key: cursors.pop(key) for key in ("since", "until") if key in cursors}
        refresh = cursors.pop("refresh_existing_content", None) == "1"
        result = self._facade.fetch_messages(
            self.mailbox_id, cursors=cursors, refresh_existing_content=refresh, **extra)
        items = [FetchedItem(**item) for item in result["items"]]
        return FetchResult(items=items, cursors=result["cursors"], errors=result["errors"])


def email_sources(purpose: str = "background") -> list[EmailMcpSource]:
    facade = EmailMcpFacade(purpose=purpose)
    return [
        EmailMcpSource(mailbox_id=row["mailbox_id"], account_id=row["account_id"],
                          display_name=row["name"], purpose=purpose, facade=facade)
        for row in facade.list_sources()
    ]
