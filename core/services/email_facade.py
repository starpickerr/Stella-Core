"""Facade over the stella.email MCP for desktop settings and the briefing pipeline.

``EmailMcpFacade`` exposes the public account settings contract and aliases.
Data collection and consumer adaptation belong to Core Data Service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
