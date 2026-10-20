"""eLearning plugin entry — no Stella agent.* / common.* imports.

Host-provided capabilities arrive through ``_hostDataHandle`` (JSON only):
  dataDir     required directory for this user's eLearning settings/sessions/state
  legacyDir   optional pre-plugin briefing directory, adopted once when dataDir is empty

Network purposes (discover / read / background / sync) are authorized by the
host gateway through the invoke purpose; this entry only enforces the surface.
Policy audit events (directory changes, downloads) are queued in the data
directory and surfaced to the host with ``drain_audit_events``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from domain.errors import LoginRequired, SyncCancelled, SyncError
from domain.service import ElearningService

CONTRACT = "stella.elearning@1"

# name -> (effect, permission, idempotent, ordered parameter names)
METHODS: dict[str, tuple[str, str, bool, tuple[str, ...]]] = {
    "get_settings": ("query", "elearning.read", False, ()),
    "get_cursors": ("query", "elearning.read", False, ()),
    "list_courses": ("query", "elearning.read", False, ()),
    "fetch": ("query", "elearning.read", False, ("since", "until", "course_ids", "offset", "limit")),
    "fetch_source": ("query", "elearning.read", False, ("cursors", "since", "until")),
    "list_files": ("query", "elearning.read", False, ("course_ids", "file_ids", "file_extensions", "offset", "limit")),
    "save_settings": ("domainWrite", "elearning.write", True, ("payload",)),
    "delete_settings": ("domainWrite", "elearning.write", True, ()),
    "save_file_sync_settings": ("domainWrite", "elearning.write", True, ("root",)),
    "test_connection": ("domainWrite", "elearning.write", False, ("payload",)),
    "set_cursors": ("domainWrite", "elearning.write", True, ("cursors",)),
    "drain_audit_events": ("domainWrite", "elearning.write", False, ()),
    "sync_files": ("domainWrite", "elearning.files", False,
                   ("course_ids", "file_ids", "file_extensions", "layout", "offset", "limit")),
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
                "timeoutMs": 600000 if name in {"fetch", "fetch_source", "sync_files", "list_files",
                                                  "list_courses", "test_connection"} else 30000,
            }
            for name, (effect, perm, idem, params) in METHODS.items()
        ],
    }
]


def _service(invoke_params: dict[str, Any]) -> ElearningService:
    handle = invoke_params.get("_hostDataHandle") or {}
    data_dir = handle.get("dataDir")
    if not data_dir:
        raise RuntimeError("host data handle with dataDir required")
    try:
        from stella_host import cancellation_token
        cancel_event = cancellation_token()
    except ImportError:
        cancel_event = None
    return ElearningService(Path(data_dir), legacy_dir=handle.get("legacyDir"), cancel_event=cancel_event,
                            authorized_resources=handle.get('authorizedResources'), user_id=invoke_params['context']['userId'])


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
    except PermissionError as exc:
        return _fail('permission_denied', str(exc))
    except LoginRequired as exc:
        return _fail("login_required", str(exc))
    except SyncCancelled as exc:
        return _fail("cancelled", str(exc))
    except SyncError as exc:
        return _fail("upstream_error", str(exc))
    except KeyError as exc:
        return _fail("not_found", str(exc.args[0]) if exc.args else "not found")
    except (ValueError, TypeError) as exc:
        return _fail("invalid_argument", str(exc))
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
