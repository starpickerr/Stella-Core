"""Email plugin entry — no Stella agent.* imports.

Host-provided capabilities arrive through ``_hostDataHandle`` (JSON only):
  dbPath             required SQLite path for this user's mailbox settings and cursors
  legacyMailboxPath  optional pre-plugin ``mailbox.json``; adopted once on first open

The plugin owns IMAP credentials. Query results only expose a masked password.
``fetch_messages`` returns *proposed* cursors; they advance only through an
explicit ``set_cursors`` so a failed consumer never moves a checkpoint.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from domain.service import EmailService

CONTRACT = "stella.email@1"

# name -> (effect, permission, idempotent, ordered parameter names)
METHODS: dict[str, tuple[str, str, bool, tuple[str, ...]]] = {
    "list_accounts": ("query", "email.read", False, ()),
    "get_account": ("query", "email.read", False, ("account_id",)),
    "list_sources": ("query", "email.read", False, ()),
    "get_cursors": ("query", "email.read", False, ("account_id",)),
    "test_connection": ("query", "email.connect", False, ("payload",)),
    "list_folders": ("query", "email.connect", False, ("account_id", "payload")),
    "fetch_messages": ("query", "email.fetch", False,
                       ("account_id", "since", "until", "cursors", "refresh_existing_content", "lookback_days")),
    "save_account": ("domainWrite", "email.write", True, ("payload",)),
    "delete_account": ("domainWrite", "email.write", True, ("account_id",)),
    "set_cursors": ("domainWrite", "email.write", True, ("account_id", "cursors")),
    "reset_cursors": ("domainWrite", "email.write", True, ("account_id",)),
}

SERVICE_DESCRIPTORS = [
    {
        "contract": CONTRACT,
        "methods": [
            {
                "name": name,
                "inputSchema": {
                    "type": "object",
                    "properties": {param: {} for param in params},
                    "additionalProperties": False,
                },
                "outputSchema": {},
                "effect": effect,
                "permissions": [perm],
                "resourceScope": ["user"],
                "idempotency": idem,
                "timeoutMs": 300000 if perm in {"email.connect", "email.fetch"} else 30000,
            }
            for name, (effect, perm, idem, params) in METHODS.items()
        ],
    }
]


def _service(invoke_params: dict[str, Any]) -> EmailService:
    handle = invoke_params.get("_hostDataHandle") or {}
    db_path = handle.get("dbPath")
    if not db_path:
        raise RuntimeError("host data handle with dbPath required")
    return EmailService(Path(db_path), legacy_mailbox_path=handle.get("legacyMailboxPath"))


def handle_invoke(invoke_params: dict[str, Any]) -> dict[str, Any]:
    method = invoke_params["method"]
    spec = METHODS.get(method)
    if spec is None:
        return _fail("not_found", f"unknown method: {method}")
    effect, _perm, _idem, allowed = spec
    params = dict(invoke_params.get("input") or {})
    unknown = sorted(set(params) - set(allowed))
    if unknown:
        return _fail("invalid_argument", f"unknown parameters for {method}: {', '.join(unknown)}")
    try:
        value = getattr(_service(invoke_params), method)(**params)
    except KeyError as exc:
        return _fail("not_found", str(exc.args[0]) if exc.args else "not found")
    except (ValueError, TypeError) as exc:
        return _fail("invalid_argument", str(exc))
    except (RuntimeError, OSError) as exc:
        return _fail("upstream_error", str(exc))
    if effect == "query":
        return _ok(value)
    return {
        "status": "succeeded",
        "sideEffects": "committed",
        "value": value,
        "operationId": invoke_params.get("idempotencyKey") or method,
    }


def _ok(value: Any) -> dict[str, Any]:
    return {"status": "succeeded", "sideEffects": "none", "value": value}


def _fail(code: str, message: str) -> dict[str, Any]:
    return {"status": "failed", "sideEffects": "none", "error": {"code": code, "message": message}}
