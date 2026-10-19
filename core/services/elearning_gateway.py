"""Core gateway that routes eLearning calls to the stella.elearning plugin worker.

Discover (course lists / connection tests), read (windowed fetch, file listing),
background (briefing fetch / checkpoints) and sync (file download) are separate
invoke purposes, so the host can grant or withdraw each independently.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Iterable

from core.plugins.authz import DEFAULT_AUTHZ
from core.plugins.host import PluginSession
from core.plugins.runtime_hub import DEFAULT_REGISTRY

CONTRACT = "stella.elearning@1"
PLUGIN_ID = "stella.elearning"

_SESSION: PluginSession | None = None
_GRANT_REF = "elearning-default-grant"
_CAPABILITIES = ("elearning.read", "elearning.write", "elearning.files", "plugin.invoke")
ALL_PURPOSES = ("interactive", "discover", "read", "background", "sync")
_PURPOSES: set[str] = set(ALL_PURPOSES)

# Positional parameter names per method; must match the plugin's SERVICE_DESCRIPTORS
# (tests/test_elearning_plugin_gateway.py enforces this).
ELEARNING_READ_METHODS: dict[str, tuple[str, ...]] = {
    "get_settings": (),
    "get_cursors": (),
    "list_courses": (),
    "fetch": ("since", "until", "course_ids", "offset", "limit"),
    "fetch_source": ("cursors", "since", "until"),
    "list_files": ("course_ids", "file_ids", "file_extensions", "offset", "limit"),
}
ELEARNING_WRITE_METHODS: dict[str, tuple[str, ...]] = {
    "save_settings": ("payload",),
    "delete_settings": (),
    "save_file_sync_settings": ("enabled", "root"),
    "test_connection": ("payload",),
    "set_cursors": ("cursors",),
    "drain_audit_events": (),
    "sync_files": ("course_ids", "file_ids", "file_extensions", "layout", "offset", "limit"),
}
ELEARNING_METHOD_PARAMS = {**ELEARNING_READ_METHODS, **ELEARNING_WRITE_METHODS}

METHOD_PURPOSE = {
    "get_settings": "interactive", "save_settings": "interactive", "delete_settings": "interactive",
    "save_file_sync_settings": "interactive", "drain_audit_events": "interactive",
    "list_courses": "discover", "test_connection": "discover",
    "fetch": "read", "list_files": "read",
    "fetch_source": "background", "get_cursors": "background", "set_cursors": "background",
    "sync_files": "sync",
}
_NETWORK_METHODS = {"list_courses", "test_connection", "fetch", "fetch_source", "list_files", "sync_files"}


def elearning_plugin_enabled() -> bool:
    return os.environ.get("STELLA_ELEARNING_PLUGIN", "").strip() in {"1", "true", "yes"}


def _plugin_root() -> Path:
    explicit = os.environ.get("STELLA_ELEARNING_PLUGIN_ROOT")
    if explicit:
        return Path(explicit)
    sibling = Path(__file__).resolve().parents[3] / "Stella-Plugins" / "plugins" / "elearning"
    workspace = Path(__file__).resolve().parents[2] / "stella-plugins-workspace" / "plugins" / "elearning"
    return sibling if sibling.is_dir() else workspace


def _issue_grant() -> None:
    DEFAULT_AUTHZ.issue(
        grant_ref=_GRANT_REF,
        plugin_id=PLUGIN_ID,
        user_id=os.environ.get("STELLA_PLUGIN_USER", "local-default"),
        capabilities=_CAPABILITIES,
        purposes=sorted(_PURPOSES),
    )


def set_elearning_purposes(purposes: Iterable[str]) -> None:
    """Replace the authorized purposes (e.g. withdraw ``background`` but keep ``read``)."""
    _PURPOSES.clear()
    _PURPOSES.update(purposes)
    if _SESSION is not None:
        _issue_grant()


def ensure_elearning_session() -> PluginSession:
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    user_id = os.environ.get("STELLA_PLUGIN_USER", "local-default")
    session = PluginSession(
        _plugin_root(),
        source_label="first-party-external",
        registry=DEFAULT_REGISTRY,
        user_id=user_id,
    )
    if os.environ.get("STELLA_ALLOW_REPO_IMPORT") in {"1", "true", "yes"}:
        os.environ.setdefault("STELLA_REPO_ROOT", str(Path(__file__).resolve().parents[2]))
    _issue_grant()
    session.start()
    _SESSION = session
    return session


def invoke_elearning(
    method: str,
    params: dict[str, Any],
    *,
    data_dir: Path,
    legacy_dir: Path | None = None,
    purpose: str | None = None,
) -> dict[str, Any]:
    if method not in ELEARNING_METHOD_PARAMS:
        raise ValueError(f"unknown elearning plugin method: {method}")
    session = ensure_elearning_session()
    write = method in ELEARNING_WRITE_METHODS
    handle: dict[str, Any] = {"dataDir": str(data_dir), "namespace": PLUGIN_ID}
    if legacy_dir is not None:
        handle["legacyDir"] = str(legacy_dir)
    payload = dict(params)
    idem = payload.pop("idempotencyKey", None)
    return session.invoke_contract(
        contract=CONTRACT,
        method=method,
        input_payload=payload,
        origin="system",
        grant_ref=_GRANT_REF,
        permissions=(),
        purpose=purpose or METHOD_PURPOSE[method],
        idempotency_key=idem or (uuid.uuid4().hex if write else None),
        timeout_ms=600_000 if method in _NETWORK_METHODS else 30_000,
        data_handle=handle,
    )


def shutdown_elearning_session() -> None:
    global _SESSION
    if _SESSION is not None:
        _SESSION.dispose()
        _SESSION = None
