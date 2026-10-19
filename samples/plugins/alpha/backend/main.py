"""Sample alpha plugin entry — no business data access."""

from __future__ import annotations

from typing import Any


def handle(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "ping":
        return {
            "status": "succeeded",
            "sideEffects": "none",
            "value": {"pong": True, "plugin": "alpha", "echo": params.get("echo")},
        }
    return {
        "status": "failed",
        "sideEffects": "none",
        "error": {"code": "not_found", "message": f"unknown method: {method}"},
    }
