"""Codex app-server Provider — local JSON-RPC client; no auto-install / force."""

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


class CodexAppServerProvider(ProviderAdapter):
    provider_local_id = "codex-app-server"
    agent_id = "codex"
    access_mode = "app-server"
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
                "streaming": True,
                "persistentSession": True,
                # reattach/approvalBridge declared false until implemented (D24 honesty).
                "reattach": False,
                "continuation": False,
                "approvalBridge": False,
                "statusQuery": True,
                "structuredOutput": False,
                "artifacts": True,
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
        run_ref = new_run_id("codex")
        # D24: app-server mode only — no silent fallback to CLI exec.
        argv = [binary, "app-server"]
        session = StdioJsonRpcSession(argv, cwd=str(workspace))
        try:
            session.start()
            try:
                session.request("initialize", {"capabilities": {}}, timeout=10)
            except (RuntimeError, TimeoutError, OSError, ValueError):
                pass
            try:
                result = session.request(
                    "thread/start",
                    {"prompt": task.get("goal") or "", "cwd": str(workspace)},
                    timeout=20,
                )
                thread_id = result.get("threadId") or result.get("id") or run_ref
            except (RuntimeError, TimeoutError, OSError, ValueError) as exc:
                session.close()
                return {
                    "status": "rejected",
                    "error": {
                        "code": "access_mode_failed",
                        "message": f"codex app-server thread/start failed: {exc}",
                        "hint": "enable providerLocalId=codex-cli for non-interactive exec",
                    },
                }
            self._runs[run_ref] = {
                "session": session,
                "threadId": thread_id,
                "workspace": str(workspace),
                "status": "running",
                "mode": "app-server",
            }
            return {
                "externalRunRef": run_ref,
                "externalSessionRef": str(thread_id),
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
        session: StdioJsonRpcSession | None = run.get("session")
        yield {"type": "progress", "message": "codex app-server running"}
        # Poll thread status once; adapters must not invent success.
        status = "outcome_unknown"
        if session is not None:
            try:
                result = session.request(
                    "thread/read",
                    {"threadId": run.get("threadId")},
                    timeout=15,
                )
                status = "running"
                yield {"type": "progress", "message": "thread read", "safePayload": {"keys": list(result)}}
            except (RuntimeError, TimeoutError, OSError, ValueError):
                status = "outcome_unknown"
            finally:
                session.close()
                run["session"] = None
        yield {"type": "terminal", "status": status, "summary": "observe complete"}

    def request_cancel(self, external_run_ref: str) -> dict[str, Any]:
        run = self._runs.get(external_run_ref)
        if run is None:
            return {"status": "unknown"}
        session = run.get("session")
        if session is None:
            return {"status": "unsupported"}
        try:
            session.request("turn/interrupt", {"threadId": run.get("threadId")}, timeout=10)
            session.close()
            run["session"] = None
            return {"status": "acknowledged"}
        except (RuntimeError, TimeoutError, OSError, ValueError):
            session.close()
            run["session"] = None
            return {"status": "acknowledged"}

    def reattach(self, external_session_ref: str) -> dict[str, Any]:
        binary = self.resolve_binary()
        if not binary:
            return {"status": "rejected", "error": {"code": "not_configured"}}
        # Capability advertised; concrete resume depends on CLI version.
        return {"status": "unsupported", "externalSessionRef": external_session_ref}
