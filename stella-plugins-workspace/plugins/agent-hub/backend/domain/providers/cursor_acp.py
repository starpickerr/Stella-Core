"""Cursor ACP Provider — ``agent acp`` / ``cursor-agent acp`` stdio JSON-RPC."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from domain.providers._jsonrpc_stdio import (
    StdioJsonRpcSession,
    new_run_id,
    run_version_probe,
    write_goal_file,
)
from domain.providers.base import ProviderAdapter


class CursorAcpProvider(ProviderAdapter):
    provider_local_id = "cursor-acp"
    agent_id = "cursor"
    access_mode = "acp"
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
                "streaming": True,
                "persistentSession": True,
                "reattach": False,
                "continuation": False,
                "approvalBridge": False,
                "statusQuery": True,
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

    def _acp_argv(self, binary: str) -> list[str] | None:
        name = Path(binary).name.lower()
        if name in {"agent", "cursor-agent"}:
            return [binary, "acp"]
        if name == "cursor":
            # Some installs expose `cursor agent acp`
            return [binary, "agent", "acp"]
        return [binary, "acp"]

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
            return {"status": "rejected", "error": {"code": "not_configured", "message": "cursor acp missing"}}
        argv = self._acp_argv(binary)
        if not argv:
            return {"status": "rejected", "error": {"code": "not_configured", "message": "no acp argv"}}
        workspace = Path(task["workspacePath"])
        write_goal_file(workspace, task.get("goal") or "")
        run_ref = new_run_id("cursor")
        session = StdioJsonRpcSession(argv, cwd=str(workspace))
        try:
            session.start()
            try:
                session.request("initialize", {"protocolVersion": 1}, timeout=10)
            except (RuntimeError, TimeoutError, OSError, ValueError):
                pass
            try:
                created = session.request("session/new", {"cwd": str(workspace)}, timeout=15)
                session_id = created.get("sessionId") or created.get("id") or run_ref
            except (RuntimeError, TimeoutError, OSError, ValueError) as exc:
                session.close()
                return {"status": "rejected", "error": {"code": "start_failed", "message": str(exc)}}
            try:
                session.request(
                    "session/prompt",
                    {"sessionId": session_id, "prompt": task.get("goal") or ""},
                    timeout=20,
                )
            except (RuntimeError, TimeoutError, OSError, ValueError):
                # Prompt may stream via notifications; keep session for observe/cancel.
                pass
            self._runs[run_ref] = {
                "session": session,
                "sessionId": session_id,
                "workspace": str(workspace),
                "status": "running",
            }
            return {
                "externalRunRef": run_ref,
                "externalSessionRef": str(session_id),
                "status": "started",
            }
        except (OSError, RuntimeError, TimeoutError) as exc:
            session.close()
            return {"status": "rejected", "error": {"code": "start_failed", "message": str(exc)}}

    def observe(self, external_run_ref: str) -> Iterator[dict[str, Any]]:
        run = self._runs.get(external_run_ref)
        if run is None:
            yield {"type": "terminal", "status": "failed", "error": {"code": "unknown_run"}}
            return
        yield {"type": "progress", "message": "cursor acp running"}
        session: StdioJsonRpcSession | None = run.get("session")
        status = "outcome_unknown"
        if session is not None:
            try:
                # ACP has no universal poll; closing after observe leaves unknown unless terminal notice arrived.
                status = "running"
            finally:
                # Keep session open for cancel; caller drives terminal via cancel/reconcile.
                pass
        # For H1 single-shot observe we close and report unknown if no terminal event.
        if session is not None and self.settings.get("closeOnObserve", True):
            session.close()
            run["session"] = None
            status = "outcome_unknown"
        yield {"type": "terminal", "status": status, "summary": "cursor observe complete"}

    def request_cancel(self, external_run_ref: str) -> dict[str, Any]:
        run = self._runs.get(external_run_ref)
        if run is None:
            return {"status": "unknown"}
        session = run.get("session")
        if session is None:
            return {"status": "unsupported"}
        try:
            session.request(
                "session/cancel",
                {"sessionId": run.get("sessionId")},
                timeout=10,
            )
            session.close()
            run["session"] = None
            return {"status": "acknowledged"}
        except (RuntimeError, TimeoutError, OSError, ValueError):
            session.close()
            run["session"] = None
            return {"status": "acknowledged"}

    def reattach(self, external_session_ref: str) -> dict[str, Any]:
        return {"status": "unsupported", "externalSessionRef": external_session_ref}
