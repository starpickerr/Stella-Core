"""Codex CLI (non-interactive exec) — sibling accessMode of app-server under agentId=codex."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Iterator

from domain.providers._jsonrpc_stdio import new_run_id, run_version_probe, sanitized_env, write_goal_file
from domain.providers.base import ProviderAdapter, UnsupportedCapability


class CodexCliProvider(ProviderAdapter):
    provider_local_id = "codex-cli"
    agent_id = "codex"
    access_mode = "cli"
    binary_hints = ("codex",)

    def __init__(self, *, binary_path: str | None = None, settings: dict | None = None):
        super().__init__(binary_path=binary_path, settings=settings)
        self._runs: dict[str, dict[str, Any]] = {}

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
            return {"status": "rejected", "error": {"code": "not_configured", "message": "codex missing"}}
        workspace = Path(task["workspacePath"])
        write_goal_file(workspace, task.get("goal") or "")
        run_ref = new_run_id("codex-cli")
        # Never pass --force / --yolo / bypass.
        argv = [binary, "exec", "--cwd", str(workspace), task.get("goal") or ""]
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=float((task.get("budget") or {}).get("maxWallTime") or 120),
                cwd=str(workspace),
                env=sanitized_env(),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "rejected", "error": {"code": "start_failed", "message": str(exc)}}
        out = workspace / "codex-result.txt"
        out.write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8")
        self._runs[run_ref] = {
            "workspace": str(workspace),
            "status": "succeeded" if result.returncode == 0 else "failed",
            "outputPath": str(out),
            "returncode": result.returncode,
        }
        return {"externalRunRef": run_ref, "status": "started"}

    def observe(self, external_run_ref: str) -> Iterator[dict[str, Any]]:
        run = self._runs.get(external_run_ref)
        if run is None:
            yield {"type": "terminal", "status": "failed", "error": {"code": "unknown_run"}}
            return
        yield {"type": "progress", "message": "codex exec finished"}
        yield {
            "type": "terminal",
            "status": run["status"],
            "outputPath": run.get("outputPath"),
            "summary": "codex exec complete",
        }

    def request_cancel(self, external_run_ref: str) -> dict[str, Any]:
        if external_run_ref not in self._runs:
            return {"status": "unknown"}
        return {"status": "unsupported"}

    def reattach(self, external_session_ref: str) -> dict[str, Any]:
        raise UnsupportedCapability("reattach")
