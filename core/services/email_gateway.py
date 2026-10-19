"""Core gateway that routes Email calls to the stella.email plugin worker.

The plugin owns IMAP credentials, folders and cursors. Callers (desktop
settings, briefing pipeline) go through this gateway and never read secrets.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Iterable

from core.plugins.authz import DEFAULT_AUTHZ
from core.plugins.caller import issue_compatibility_grant, managed_plugin_route, plugin_user_id, serialized_gateway, user_grant_ref
from core.plugins.host import PluginSession
from core.plugins.runtime_hub import DEFAULT_REGISTRY

CONTRACT = "stella.email@1"
PLUGIN_ID = "stella.email"

_SESSION: PluginSession | None = None
_GRANT_REF = "email-default-grant"
_CAPABILITIES = ("email.read", "email.write", "email.connect", "email.fetch", "plugin.invoke")
_PURPOSES: set[str] = {"interactive", "read", "background"}

# Positional parameter names per method; must match the plugin's SERVICE_DESCRIPTORS
# (tests/test_email_plugin_gateway.py enforces this).
EMAIL_READ_METHODS: dict[str, tuple[str, ...]] = {
    "list_accounts": (),
    "get_account": ("account_id",),
    "list_sources": (),
    "get_cursors": ("account_id",),
    "test_connection": ("payload",),
    "list_folders": ("account_id", "payload"),
    "fetch_messages": ("account_id", "since", "until", "cursors", "refresh_existing_content", "lookback_days"),
}
EMAIL_WRITE_METHODS: dict[str, tuple[str, ...]] = {
    "save_account": ("payload",),
    "delete_account": ("account_id",),
    "set_cursors": ("account_id", "cursors"),
    "reset_cursors": ("account_id",),
}
EMAIL_METHOD_PARAMS = {**EMAIL_READ_METHODS, **EMAIL_WRITE_METHODS}

# Default purpose per method. Settings and connection checks are user actions;
# message/cursor access defaults to "read" and a scheduled briefing passes "background".
_PURPOSE = {
    "list_accounts": "interactive", "get_account": "interactive",
    "test_connection": "interactive", "list_folders": "interactive",
    "save_account": "interactive", "delete_account": "interactive",
    "list_sources": "read", "get_cursors": "read", "set_cursors": "read", "reset_cursors": "read",
    "fetch_messages": "read",
}
_NETWORK_METHODS = {"test_connection", "list_folders", "fetch_messages"}


def email_plugin_enabled() -> bool:
    return managed_plugin_route("stella.email", os.environ.get("STELLA_EMAIL_PLUGIN", ""))


def _plugin_root() -> Path:
    from core.plugins.roots import resolve_plugin_package_root

    return resolve_plugin_package_root(
        plugin_id=PLUGIN_ID,
        env_var="STELLA_EMAIL_PLUGIN_ROOT",
        folder_name="email",
    )


def _issue_grant(*, replace_existing: bool = True) -> None:
    issue_compatibility_grant(DEFAULT_AUTHZ,
        grant_ref=user_grant_ref(_GRANT_REF),
        plugin_id=PLUGIN_ID,
        user_id=plugin_user_id(),
        capabilities=_CAPABILITIES,
        purposes=sorted(_PURPOSES),
        replace_existing=replace_existing,
    )


@serialized_gateway
def set_email_purposes(purposes: Iterable[str]) -> None:
    """Replace the purposes the default grant authorizes (e.g. drop ``background``)."""
    _issue_grant(replace_existing=False)
    DEFAULT_AUTHZ.set_purposes(user_grant_ref(_GRANT_REF), purposes)


@serialized_gateway
def ensure_email_session() -> PluginSession:
    global _SESSION
    if _SESSION is not None and (_SESSION.user_id != plugin_user_id() or not _SESSION.is_running):
        shutdown_email_session()
    if _SESSION is not None:
        return _SESSION
    user_id = plugin_user_id()
    session = PluginSession(
        _plugin_root(),
        source_label="first-party-external",
        registry=DEFAULT_REGISTRY,
        user_id=user_id,
        authz=DEFAULT_AUTHZ,
    )
    if os.environ.get("STELLA_ALLOW_REPO_IMPORT") in {"1", "true", "yes"}:
        os.environ.setdefault("STELLA_REPO_ROOT", str(Path(__file__).resolve().parents[2]))
    _issue_grant(replace_existing=False)
    session.start()
    _SESSION = session
    return session


@serialized_gateway
def invoke_email(
    method: str,
    params: dict[str, Any],
    *,
    db_path: Path,
    legacy_mailbox_path: Path | None = None,
    purpose: str | None = None,
) -> dict[str, Any]:
    if method not in EMAIL_METHOD_PARAMS:
        raise ValueError(f"unknown email plugin method: {method}")
    session = ensure_email_session()
    write = method in EMAIL_WRITE_METHODS
    handle: dict[str, Any] = {"dbPath": str(db_path), "namespace": PLUGIN_ID}
    if legacy_mailbox_path is not None:
        handle["legacyMailboxPath"] = str(legacy_mailbox_path)
    payload = dict(params)
    idem = payload.pop("idempotencyKey", None)
    return session.invoke_contract(
        contract=CONTRACT,
        method=method,
        input_payload=payload,
        origin="system",
        grant_ref=user_grant_ref(_GRANT_REF),
        permissions=(),
        purpose=purpose or _PURPOSE[method],
        idempotency_key=idem or (uuid.uuid4().hex if write else None),
        timeout_ms=300_000 if method in _NETWORK_METHODS else 30_000,
        data_handle=handle,
    )


@serialized_gateway
def shutdown_email_session() -> None:
    global _SESSION
    if _SESSION is not None:
        _SESSION.dispose()
        _SESSION = None
