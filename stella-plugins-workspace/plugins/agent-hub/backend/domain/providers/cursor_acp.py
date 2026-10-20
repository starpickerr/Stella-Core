"""Cursor ACP Provider — ``agent acp`` / ``cursor-agent acp`` stdio JSON-RPC."""

from __future__ import annotations

from typing import Any, Iterator

from domain.providers._local_runtime import (
    run_version_probe,
)
from domain.providers.base import ProviderAdapter, UnsupportedCapability


class CursorAcpProvider(ProviderAdapter):
    provider_local_id = "cursor-acp"
    agent_id = "cursor"
    access_mode = "acp"
    binary_hints = ("agent", "cursor-agent", "cursor")

    def describe(self) -> dict[str, Any]:
        return {
            "providerId": f"stella.agent-hub/{self.provider_local_id}",
            "agentId": self.agent_id,
            "accessMode": self.access_mode,
            "contractVersion": "1",
            "taskKinds": [],
            "capabilities": {
                "streaming": False,
                "persistentSession": False,
                "reattach": False,
                "continuation": False,
                "approvalBridge": False,
                "statusQuery": False,
                "structuredOutput": False,
                "artifacts": False,
                "usage": False,
                "cost": False,
                "localOrRemote": "local",
            },
            "limits": {
                "filesystemRead": "workspace",
                "filesystemWrite": "workspace",
                "network": "unknown",
                "childProcesses": True,
                "settingsIsolation": "partial",
            },
        }

    def probe(self) -> dict[str, Any]:
        binary = self.resolve_binary()
        if not binary:
            return {
                "status": "not_configured",
                "installed": False,
                "authenticated": False,
                "reason": "Cursor ACP binary not found (agent / cursor-agent / cursor)",
                "capabilities": self.describe()["capabilities"],
                "agentId": self.agent_id,
                "accessMode": self.access_mode,
            }
        # Prefer --version / version without starting ACP session.
        version = run_version_probe([binary, "--version"])
        if not version.get("ok"):
            version = run_version_probe([binary, "version"])
        return {
            "status": "blocked",
            "installed": True,
            "authenticated": "unknown",
            "binary": binary,
            "versionProbe": version,
            "capabilities": self.describe()["capabilities"],
            "agentId": self.agent_id,
            "accessMode": self.access_mode,
            "reason": "Protocol task execution is not implemented; choose a CLI access mode.",
        }

    def start(self, task: dict[str, Any]) -> dict[str, Any]:
        return {"status": "rejected", "error": {"code": "unsupported_protocol_execution",
                "message": "Protocol task execution is not implemented; choose a CLI access mode."}}

    def observe(self, external_run_ref: str) -> Iterator[dict[str, Any]]:
        raise UnsupportedCapability("observe")

    def request_cancel(self, external_run_ref: str) -> dict[str, Any]:
        return {"status": "unsupported"}
