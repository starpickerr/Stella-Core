"""Cursor CLI print/headless mode — sibling of ACP under agentId=cursor.

Never passes --force / --yolo (D24 + security: no silent approval bypass).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Iterator

from domain.providers._jsonrpc_stdio import new_run_id, run_version_probe, sanitized_env, write_goal_file
from domain.providers.base import ProviderAdapter, UnsupportedCapability


class CursorCliProvider(ProviderAdapter):
    provider_local_id = "cursor-cli"
    agent_id = "cursor"
    access_mode = "cli"
    binary_hints = ("agent", "cursor-agent", "cursor")

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
            return {"status": "rejected", "error": {"code": "not_configured", "message": "cursor cli missing"}}
        workspace = Path(task["workspacePath"])
        write_goal_file(workspace, task.get("goal") or "")
        run_ref = new_run_id("cursor-cli")
        argv = self._print_argv(binary, task.get("goal") or "")
        # Guard against accidental force flags in settings.
        if any(flag in {"--force", "--yolo", "-f"} for flag in argv):
            return {
                "status": "rejected",
                "error": {"code": "unsafe_flags", "message": "cursor-cli forbids --force/--yolo"},
            }
        wall = float((task.get("budget") or {}).get("maxWallTime") or 180)
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=wall,
                cwd=str(workspace),
                env=sanitized_env(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._runs[run_ref] = {
                "status": "outcome_unknown",
                "workspace": str(workspace),
                "error": "wall_time_exceeded",
            }
            return {"externalRunRef": run_ref, "status": "started"}
        except OSError as exc:
            return {"status": "rejected", "error": {"code": "start_failed", "message": str(exc)}}
        out = workspace / "cursor-cli-result.txt"
        out.write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8")
        self._runs[run_ref] = {
            "status": "succeeded" if result.returncode == 0 else "failed",
            "workspace": str(workspace),
            "outputPath": str(out),
            "returncode": result.returncode,
        }
        return {"externalRunRef": run_ref, "status": "started"}

    def observe(self, external_run_ref: str) -> Iterator[dict[str, Any]]:
        run = self._runs.get(external_run_ref)
        if run is None:
            yield {"type": "terminal", "status": "failed", "error": {"code": "unknown_run"}}
            return
        yield {"type": "progress", "message": "cursor cli finished"}
        yield {
            "type": "terminal",
            "status": run.get("status") or "outcome_unknown",
            "outputPath": run.get("outputPath"),
            "summary": "cursor cli observe complete",
            "error": {"code": run["error"]} if run.get("error") else None,
        }

    def request_cancel(self, external_run_ref: str) -> dict[str, Any]:
        if external_run_ref not in self._runs:
            return {"status": "unknown"}
        return {"status": "unsupported"}

    def reattach(self, external_session_ref: str) -> dict[str, Any]:
        raise UnsupportedCapability("reattach")
