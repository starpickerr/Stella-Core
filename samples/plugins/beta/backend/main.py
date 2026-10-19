"""Sample beta plugin — second source label path for P1a."""

from __future__ import annotations

from typing import Any


def handle(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "ping":
        return {
            "status": "succeeded",
            "sideEffects": "none",
            "value": {"pong": True, "plugin": "beta", "echo": params.get("echo")},
        }
    return {
        "status": "failed",
        "sideEffects": "none",
        "error": {"code": "not_found", "message": f"unknown method: {method}"},
    }
