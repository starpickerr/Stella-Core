"""Codex CLI (non-interactive exec) — sibling accessMode of app-server under agentId=codex."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from domain.providers._local_runtime import run_version_probe, write_goal_file
from domain.providers._cli_process import ManagedCliProvider


class CodexCliProvider(ManagedCliProvider):
    provider_local_id = "codex-cli"
    agent_id = "codex"
    access_mode = "cli"
    binary_hints = ("codex",)

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
            "reason": None if version.get("ok") else "codex version probe failed",
        }

    def start(self, task: dict[str, Any]) -> dict[str, Any]:
        binary = self.resolve_binary()
        if not binary:
            return {"status": "rejected", "error": {"code": "not_configured", "message": "CLI binary missing"}}
        workspace = Path(task["workspacePath"])
        write_goal_file(workspace, task.get("goal") or "")
        return self._start_cli([binary, "exec", "--skip-git-repo-check", "--cd", str(workspace), task.get("goal") or ""], task, "codex-result.txt")
