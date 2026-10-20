"""Codex app-server Provider — local JSON-RPC client; no auto-install / force."""

from __future__ import annotations

from typing import Any, Iterator

from domain.providers._local_runtime import (
    run_version_probe,
)
from domain.providers.base import ProviderAdapter, UnsupportedCapability


class CodexAppServerProvider(ProviderAdapter):
    provider_local_id = "codex-app-server"
    agent_id = "codex"
    access_mode = "app-server"
    binary_hints = ("codex",)

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
                # reattach/approvalBridge declared false until implemented (D24 honesty).
                "reattach": False,
                "continuation": False,
                "approvalBridge": False,
                "statusQuery": False,
                "structuredOutput": False,
                "artifacts": False,
                "usage": True,
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
                "reason": "codex binary not found on PATH",
                "capabilities": self.describe()["capabilities"],
                "agentId": self.agent_id,
                "accessMode": self.access_mode,
            }
        # Version probe only — must not start a durable task.
        version = run_version_probe([binary, "--version"])
        if not version.get("ok"):
            # Some builds use `codex version`
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
