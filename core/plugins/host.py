"""Host-side worker session: spawn runner, handshake, authorize, invoke, dispose."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from core.plugins.authz import DEFAULT_AUTHZ, PluginAuthorizationStore
from core.plugins.contract import (
    ContractError,
    build_host_context,
    build_invoke_params,
    validate_operation_result,
)
from core.plugins.manifest import load_manifest
from core.plugins.protocol import FrameError, make_request, read_frame, write_frame
from core.plugins.registry import ContributionSnapshot, PluginRegistry


class PluginHostError(RuntimeError):
    pass


def _platform_tag() -> str:
    return f"{sys.platform}-{platform.machine()}"


RUNNER_ENV = "STELLA_PLUGIN_RUNNER"
RUNNER_BINARY_NAME = "stella-plugin-runner"
RUNNER_DEV_MODULE = "core.plugins.runner.cli"


def _runner_binary_candidates(anchor: Path) -> list[Path]:
    """Sibling layouts next to the frozen app executable (onedir or flat)."""
    exe = RUNNER_BINARY_NAME + (".exe" if sys.platform == "win32" else "")
    return [
        anchor / exe,
        anchor / RUNNER_BINARY_NAME / exe,
        anchor.parent / RUNNER_BINARY_NAME / exe,
    ]


def resolve_runner_command(
    *,
    python_executable: str | None = None,
    environ: Mapping[str, str] | None = None,
    frozen: bool | None = None,
    executable: str | None = None,
) -> list[str]:
    """Pick the worker command.

    Order: ``STELLA_PLUGIN_RUNNER`` -> sibling ``stella-plugin-runner`` binary
    next to the frozen app -> dev fallback ``python -m core.plugins.runner.cli``.
    A frozen app never falls back to ``-m`` (its interpreter is the app itself).
    """
    env = os.environ if environ is None else environ
    override = (env.get(RUNNER_ENV) or "").strip()
    if override:
        path = Path(override)
        if not path.is_file():
            raise PluginHostError(f"{RUNNER_ENV} does not point to a file: {override}")
        return [str(path)]
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    exe_path = Path(executable or sys.executable).resolve()
    if is_frozen:
        for cand in _runner_binary_candidates(exe_path.parent):
            if cand.is_file():
                return [str(cand)]
        raise PluginHostError(
            f"frozen app has no {RUNNER_BINARY_NAME} next to {exe_path} (set {RUNNER_ENV})"
        )
    return [python_executable or sys.executable, "-m", RUNNER_DEV_MODULE]


class PluginSession:
    def __init__(
        self,
        plugin_root: Path,
        *,
        source_label: str,
        registry: PluginRegistry,
        user_id: str = "local-default",
        python_executable: str | None = None,
        authz: PluginAuthorizationStore | None = None,
        runner_command: list[str] | None = None,
    ) -> None:
        self.plugin_root = Path(plugin_root).resolve()
        self.source_label = source_label
        self.registry = registry
        self.user_id = user_id
        self.authz = authz or DEFAULT_AUTHZ
        self.manifest = load_manifest(self.plugin_root)
        self.plugin_id = self.manifest["id"]
        self.package_digest = _digest_tree(self.plugin_root)
        self.generation = 0
        self.instance_id = str(uuid.uuid4())
        self._python = python_executable or sys.executable
        self._runner_command = runner_command
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.RLock()
        self._inflight: set[str] = set()
        self._service_permissions: dict[str, frozenset[str]] = {}

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._proc is not None:
                raise PluginHostError("session already started")
            env = os.environ.copy()
            env["STELLA_PLUGIN_ROOT"] = str(self.plugin_root)
            env["STELLA_PLUGIN_ID"] = self.plugin_id
            # Frozen/dedicated runner must not depend on repo checkout imports
            # unless explicitly opted in for transitional packages.
            if env.get("STELLA_ALLOW_REPO_IMPORT") not in {"1", "true", "yes"}:
                env.pop("STELLA_REPO_ROOT", None)
            cmd = self._runner_command or resolve_runner_command(python_executable=self._python)
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(Path(env.get("STELLA_RUNNER_CWD") or Path.cwd())),
                env=env,
            )
            self.generation += 1
            init = self._rpc(
                "runtime.initialize",
                {
                    "pluginId": self.plugin_id,
                    "packageDigest": self.package_digest,
                    "userId": self.user_id,
                    "instanceId": self.instance_id,
                    "generation": self.generation,
                    "hostApi": "1.0.0",
                    "runtimeAbi": "cp312",
                    "platform": _platform_tag(),
                    "manifest": self.manifest,
                    "sourceLabel": self.source_label,
                },
            )
            prepared = self._rpc(
                "runtime.prepare",
                {
                    "pluginId": self.plugin_id,
                    "generation": self.generation,
                },
            )
            contributions = prepared.get("contributions") or prepared.get("contributes") or {}
            services_desc = prepared.get("services") or []
            service_ids: list[str] = []
            self._service_permissions = {}
            if isinstance(services_desc, list) and services_desc and isinstance(services_desc[0], dict):
                for svc in services_desc:
                    contract = svc.get("contract")
                    if contract:
                        service_ids.append(contract)
                        perms: set[str] = set()
                        for method in svc.get("methods") or []:
                            perms.update(method.get("permissions") or [])
                        self._service_permissions[contract] = frozenset(perms)
            else:
                service_ids = list(contributions.get("services") or [])
            self.registry.publish(
                ContributionSnapshot(
                    plugin_id=self.plugin_id,
                    generation=self.generation,
                    source_label=self.source_label,
                    package_digest=self.package_digest,
                    contributes=dict(contributions),
                    services=tuple(service_ids),
                )
            )
            return {"initialize": init, "prepare": prepared}

    def invoke(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Compatibility wrapper — prefer invoke_contract."""
        services = self.registry.get(self.plugin_id)
        contract = (services.services[0] if services and services.services else f"{self.plugin_id}@1")
        payload = dict(params or {})
        data_handle = payload.pop("_dataHandle", None)
        return self.invoke_contract(
            contract=contract,
            method=method,
            input_payload=payload,
            origin="system",
            grant_ref="legacy-compat",
            permissions=(),
            skip_authz=True,
            data_handle=data_handle,
        )

    def invoke_contract(
        self,
        *,
        contract: str,
        method: str,
        input_payload: Mapping[str, Any],
        origin: str,
        grant_ref: str,
        permissions: Iterable[str] = (),
        purpose: str = "interactive",
        idempotency_key: str | None = None,
        timeout_ms: int = 30_000,
        skip_authz: bool = False,
        agent_id: str | None = None,
        session_id: str | None = None,
        data_handle: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.registry.require_generation(self.plugin_id, self.generation)
        required = set(permissions)
        required.update(self._service_permissions.get(contract) or ())
        if not skip_authz:
            self.authz.check(
                grant_ref=grant_ref,
                plugin_id=self.plugin_id,
                user_id=self.user_id,
                required_capabilities=required or {"plugin.invoke"},
                purpose=purpose,
                generation=self.generation,
                context_generation=self.generation,
            )
            # Overlay existing conversation/tool permission path when agent/tool origin.
            if origin in {"tool", "job"} and agent_id:
                denial = _conversation_permission_denial(
                    contract=contract,
                    method=method,
                    agent_id=agent_id,
                    session_id=session_id,
                )
                if denial:
                    raise PermissionError(denial)
        context = build_host_context(
            user_id=self.user_id,
            instance_id=self.instance_id,
            generation=self.generation,
            origin=origin,
            grant_ref=grant_ref,
            agent_id=agent_id,
            session_id=session_id,
        )
        invoke_params = build_invoke_params(
            contract=contract,
            method=method,
            input_payload=input_payload,
            context=context,
            deadline=datetime.now(timezone.utc) + timedelta(milliseconds=timeout_ms),
            idempotency_key=idempotency_key,
        )
        # Host-bound data handle — never trust plugin-supplied paths.
        if data_handle is not None:
            invoke_params = dict(invoke_params)
            invoke_params["_hostDataHandle"] = dict(data_handle)
        result = self._rpc("plugin.invoke", invoke_params)
        try:
            return validate_operation_result(result)
        except ContractError as exc:
            raise PluginHostError(str(exc)) from exc

    def dispose(self) -> None:
        with self._lock:
            try:
                if self._proc and self._proc.stdin and self._proc.poll() is None:
                    try:
                        self._rpc(
                            "runtime.drain",
                            {
                                "pluginId": self.plugin_id,
                                "generation": self.generation,
                                "timeoutMs": 2000,
                            },
                            allow_dead=False,
                        )
                    except (PluginHostError, FrameError, BrokenPipeError):
                        pass
                    try:
                        self._rpc(
                            "runtime.dispose",
                            {"pluginId": self.plugin_id, "generation": self.generation},
                            allow_dead=True,
                        )
                    except (PluginHostError, FrameError, BrokenPipeError):
                        pass
            finally:
                self.registry.revoke(self.plugin_id, self.generation)
                if self._proc is not None:
                    if self._proc.poll() is None:
                        self._proc.terminate()
                        try:
                            self._proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            self._proc.kill()
                            self._proc.wait(timeout=5)
                    self._proc = None

    def _rpc(
        self, method: str, params: dict[str, Any], *, allow_dead: bool = False
    ) -> dict[str, Any]:
        with self._lock:
            if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
                raise PluginHostError("worker not running")
            if self._proc.poll() is not None and not allow_dead:
                err = b""
                if self._proc.stderr:
                    try:
                        err = self._proc.stderr.read() or b""
                    except Exception:
                        err = b""
                raise PluginHostError(
                    f"worker exited with code {self._proc.returncode}: {err[-2000:]!r}"
                )
            request_id = str(uuid.uuid4())
            if request_id in self._inflight:
                raise PluginHostError("duplicate in-flight request id")
            self._inflight.add(request_id)
            try:
                write_frame(self._proc.stdin, make_request(method, params, request_id))
                response = read_frame(self._proc.stdout)
            finally:
                self._inflight.discard(request_id)
            if response.get("id") != request_id:
                raise PluginHostError("response id mismatch")
            if "error" in response:
                err = response["error"]
                raise PluginHostError(f"{err.get('code')}: {err.get('message')}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise PluginHostError("result must be an object")
            return result


def _conversation_permission_denial(
    *,
    contract: str,
    method: str,
    agent_id: str,
    session_id: str | None,
) -> str | None:
    try:
        from agent.runtime.tool_invocation import permission_denial
    except Exception:
        return None
    domain = contract.split("@", 1)[0].rsplit(".", 1)[-1]
    action = {
        "create_ledger": "add",
        "update_ledger": "update",
        "delete_ledger": "delete",
        "list_ledger": "list",
        "get_ledger": "get",
    }.get(method, method)
    return permission_denial(domain, {"action": action}, agent_id=agent_id, session_id=session_id)


def _digest_tree(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()
