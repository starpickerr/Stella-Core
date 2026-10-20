"""Cursor CLI print/headless mode — sibling of ACP under agentId=cursor.

Never passes --force / --yolo (D24 + security: no silent approval bypass).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from domain.providers._local_runtime import run_version_probe, write_goal_file
from domain.providers._cli_process import ManagedCliProvider


class CursorCliProvider(ManagedCliProvider):
    provider_local_id = "cursor-cli"
    agent_id = "cursor"
    access_mode = "cli"
    binary_hints = ("agent", "cursor-agent", "cursor")

    def describe(self) -> dict[str, Any]:
        return {
            "providerId": f"stella.agent-hub/{self.provider_local_id}",
            "agentId": self.agent_id,
            "accessMode": self.access_mode,
            "contractVersion": "1",
            "taskKinds": ["coding.task", "research.report", "general.delegate"],
            "capabilities": {
                "streaming": False,
                "persistentSession": False,
                "reattach": False,
                "continuation": False,
                "approvalBridge": False,
                "statusQuery": False,
                "structuredOutput": False,
                "artifacts": True,
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

    def _print_argv(self, binary: str, goal: str) -> list[str]:
        name = Path(binary).name.lower()
        # Print mode only — never --force / --yolo.
        if name == "cursor":
            return [binary, "agent", "-p", "--output-format", "text", goal]
        return [binary, "-p", "--output-format", "text", goal]

    def probe(self) -> dict[str, Any]:
        binary = self.resolve_binary()
        if not binary:
            return {
                "status": "not_configured",
                "installed": False,
                "authenticated": False,
                "reason": "Cursor CLI binary not found (agent / cursor-agent / cursor)",
                "capabilities": self.describe()["capabilities"],
                "agentId": self.agent_id,
                "accessMode": self.access_mode,
            }
        version = run_version_probe([binary, "--version"])
        if not version.get("ok"):
            version = run_version_probe([binary, "version"])
        return {
            "status": "ready" if version.get("ok") else "blocked",
            "installed": True,
            "authenticated": "unknown",
            "binary": binary,
            "versionProbe": version,
            "capabilities": self.describe()["capabilities"],
            "agentId": self.agent_id,
            "accessMode": self.access_mode,
            "reason": None if version.get("ok") else "cursor binary version probe failed",
        }

    def start(self, task: dict[str, Any]) -> dict[str, Any]:
        binary = self.resolve_binary()
        if not binary:
            return {"status": "rejected", "error": {"code": "not_configured", "message": "CLI binary missing"}}
        workspace = Path(task["workspacePath"])
        write_goal_file(workspace, task.get("goal") or "")
        return self._start_cli(self._print_argv(binary, task.get("goal") or ""), task, "cursor-result.txt")
