"""Host-side worker session: spawn runner, handshake, authorize, invoke, dispose."""

from __future__ import annotations

import os
import platform
import queue
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from contextlib import nullcontext
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
from core.plugins.protocol import FrameError, make_request, make_result, make_error, read_frame, write_frame
from core.plugins.registry import ContributionSnapshot, PluginRegistry


class PluginHostError(RuntimeError):
    pass


class PluginOutcomeUnknown(PluginHostError):
    """Transport failed after dispatch; a mutation may already have committed."""

    side_effects = "unknown"


def _platform_tag() -> str:
    return f"{sys.platform}-{platform.machine()}"


CONFIG_METHODS = frozenset({'save_account', 'delete_account', 'save_settings', 'delete_settings',
                            'save_file_sync_settings', 'update_preferences'})

RUNNER_ENV = "STELLA_PLUGIN_RUNNER"
RUNNER_BINARY_NAME = "stella-plugin-runner"
RUNNER_DEV_MODULE = "core.plugins.runner.cli"


def _runner_binary_candidates(anchor: Path) -> list[Path]:
    """Sibling layouts next to the frozen app executable (onedir or flat).

    Electron packs backend as ``Resources/backend/stella-backend/`` and the
    runner as ``Resources/backend/stella-plugin-runner/`` (see desktop/package.json).
    """
    exe = RUNNER_BINARY_NAME + (".exe" if sys.platform == "win32" else "")
    return [
        anchor / exe,
        anchor / RUNNER_BINARY_NAME / exe,
        anchor.parent / RUNNER_BINARY_NAME / exe,
        anchor.parent.parent / "backend" / RUNNER_BINARY_NAME / exe,
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


def _managed_boundary(function):
    @wraps(function)
    def call(self, **kwargs):
        from core.plugins.management import default_store
        from core.plugins.caller import managed_data_lease, managed_plugin, invocation_lock
        from core.plugins.locks import package_lock

        store = default_store()
        if not managed_plugin(self.plugin_id, self.user_id):
            return function(self, **kwargs)
        with managed_data_lease(self.plugin_id, user_id=self.user_id):
            from core.plugins.package_ops import PackageStore

            current = PackageStore(store.root).current_package(self.plugin_id)
            if not current or current['digest'] != self.package_digest:
                self.dispose()
                raise PermissionError('worker package selection changed; restart the session')
            with invocation_lock(self._lock):
                policy = (package_lock(store.root, self.plugin_id + ':policy', exclusive=True)
                          if kwargs.get('method') in CONFIG_METHODS else nullcontext())
                with policy:
                    return function(self, **kwargs)
    return call


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
        maintenance: bool = False,
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
        self.maintenance = maintenance
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.RLock()
        self._inflight: set[str] = set()
        self._stderr_thread: threading.Thread | None = None
        self._stderr_bytes = 0
        self._service_permissions: dict[str, frozenset[str]] = {}
        self._method_permissions: dict[tuple[str, str], frozenset[str]] = {}
        self._method_effects: dict[tuple[str, str], str] = {}

    @property
    def is_running(self) -> bool:
        from core.plugins.caller import invocation_lock

        with invocation_lock(self._lock):
            from core.plugins.caller import managed_plugin
            from core.plugins.management import default_store
            from core.plugins.package_ops import PackageStore

            if managed_plugin(self.plugin_id, self.user_id):
                try:
                    current = PackageStore(default_store().root).current_package(self.plugin_id)
                    if not current or current['digest'] != self.package_digest:
                        return False
                except (ValueError, OSError, KeyError):
                    return False
            snapshot = self.registry.get(self.plugin_id)
            return (self._proc is not None and self._proc.poll() is None and
                    snapshot is not None and snapshot.generation == self.generation)

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._proc is not None:
                raise PluginHostError("session already started")
            try:
                return self._start()
            except Exception:
                self.dispose()
                raise

    def _start(self) -> dict[str, Any]:
        with self._lock:
            if self._proc is not None:
                raise PluginHostError("session already started")
            # Runtime mechanics cross the process boundary; Core credentials,
            # management tokens and import injection variables never do.
            allowed = {
                "PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT", "WINDIR",
                "LANG", "LC_ALL", "LC_CTYPE", "TEMP", "TMP", "TMPDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
                "STELLA_DATA_DIR", "STELLA_DESKTOP", "PYTHONDONTWRITEBYTECODE", "PLAYWRIGHT_BROWSERS_PATH",
            }
            if self.plugin_id == "stella.email":
                allowed.update({"IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD", "IMAP_PORT", "IMAP_FOLDER"})
            env = {key: value for key, value in os.environ.items() if key in allowed}
            if os.environ.get("STELLA_ALLOW_REPO_IMPORT") in {"1", "true", "yes"}:
                env["STELLA_ALLOW_REPO_IMPORT"] = "1"
                if "STELLA_REPO_ROOT" in os.environ:
                    env["STELLA_REPO_ROOT"] = os.environ["STELLA_REPO_ROOT"]
            if self.maintenance:
                env["STELLA_PLUGIN_MAINTENANCE"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
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
                cwd=str(Path(os.environ.get("STELLA_RUNNER_CWD") or Path.cwd())),
                env=env,
            )
            process = self._proc
            self._stderr_bytes = 0
            self._stderr_thread = threading.Thread(target=self._drain_stderr, args=(process,), daemon=True)
            self._stderr_thread.start()
            self.generation = self.registry.next_generation(self.plugin_id)
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
            self._method_permissions = {}
            self._method_effects = {}
            if isinstance(services_desc, list) and services_desc and isinstance(services_desc[0], dict):
                for svc in services_desc:
                    contract = svc.get("contract")
                    if contract:
                        service_ids.append(contract)
                        perms: set[str] = set()
                        for method in svc.get("methods") or []:
                            perms.update(method.get("permissions") or [])
                            self._method_permissions[(contract, method["name"])] = frozenset(method.get("permissions") or [])
                            self._method_effects[(contract, method["name"])] = method.get("effect", "unknown")
                        self._service_permissions[contract] = frozenset(perms)
            else:
                service_ids = list(contributions.get("services") or [])
            snapshot = ContributionSnapshot(
                    plugin_id=self.plugin_id,
                    generation=self.generation,
                    source_label=self.source_label,
                    package_digest=self.package_digest,
                    contributes=dict(contributions),
                    services=tuple(service_ids),
                    user_id=self.user_id,
                )
            if not self.maintenance:
                self.registry.publish(snapshot)
            return {"initialize": init, "prepare": prepared}

    def migrate(self, *, operation_id: str, migration_id: str, from_schema: int, to_schema: int,
                data_handle: Mapping[str, Any], mode: str) -> dict[str, Any]:
        if not self.maintenance:
            raise PermissionError("migration requires maintenance session")
        handle = {**dict(data_handle), "userId": self.user_id, "instanceId": self.instance_id,
                  "generation": self.generation}
        return self._rpc("runtime.migrate", {
            "operationId": operation_id, "migrationId": migration_id, "mode": mode,
            "fromSchema": from_schema, "toSchema": to_schema,
            "dataHandle": f"maintenance:{operation_id}:{migration_id}",
            "deadline": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
            "_hostDataHandle": handle,
        }, timeout_ms=60_000)

    def invoke(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Compatibility wrapper for samples/tests — production callers use ``invoke_contract``.

        Auto-issues a per-plugin compat grant covering declared capabilities so
        authz stays enforceable (R05); a revoked grant still blocks.
        """
        services = self.registry.get(self.plugin_id)
        contract = (services.services[0] if services and services.services else f"{self.plugin_id}@1")
        payload = dict(params or {})
        data_handle = payload.pop("_dataHandle", None)
        grant_ref = f"legacy-compat:{self.plugin_id}:{self.user_id}"
        caps = {"plugin.invoke"}
        for row in self.manifest.get("permissions") or ():
            if isinstance(row, dict) and row.get("capability"):
                caps.add(str(row["capability"]))
        caps.update(self._service_permissions.get(contract) or ())
        if self.authz.get(grant_ref) is None:
            self.authz.issue(
                grant_ref=grant_ref,
                plugin_id=self.plugin_id,
                user_id=self.user_id,
                capabilities=caps,
                purposes=["interactive", "system", "any"],
            )
        return self.invoke_contract(
            contract=contract,
            method=method,
            input_payload=payload,
            origin="system",
            grant_ref=grant_ref,
            permissions=tuple(caps),
            purpose="interactive",
            skip_authz=False,
            data_handle=data_handle,
        )

    @_managed_boundary
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
        from common.runtime_identity import current_identity

        identity = current_identity()
        if identity.user_id and identity.user_id != self.user_id:
            raise PermissionError("plugin session user identity mismatch")
        # A compatibility gateway cannot erase the real tool/job caller.
        from core.plugins.caller import current_caller_origin, current_delegation

        if origin == "system":
            origin = current_caller_origin() or ("job" if identity.task_id else
                                                 "tool" if identity.session_id else "system")
        delegation = current_delegation()
        if delegation:
            origin = delegation['origin']
            remaining = (delegation['deadline'] - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                raise PermissionError('delegated invocation deadline expired')
            timeout_ms = min(timeout_ms, max(1, int(remaining * 1000)))
        agent_id = identity.agent_id or agent_id
        session_id = identity.session_id or session_id
        self.registry.require_generation(self.plugin_id, self.generation)
        declared = self._method_permissions.get((contract, method))
        if declared is None:
            raise PermissionError(f"method not declared: {contract}.{method}")
        required = set(permissions)
        required.update(declared)
        from core.plugins.management import default_store
        from core.plugins.caller import current_consumer_plugin, managed_plugin

        managed = managed_plugin(self.plugin_id, self.user_id)
        if managed and skip_authz:
            raise PermissionError('managed authorization cannot be bypassed')
        resource_refs = None
        if not skip_authz:
            if managed:
                from core.plugins.resources import invocation_resources

                from core.plugins.locks import package_lock

                policy = (nullcontext() if method in CONFIG_METHODS else
                          package_lock(default_store().root, self.plugin_id + ':policy', exclusive=True))
                with policy:
                    purpose = 'background' if origin == 'job' or purpose == 'background' else 'interactive'
                    scope = dict(grant_ref=grant_ref, plugin_id=self.plugin_id, user_id=self.user_id,
                                 consumer_plugin_id=current_consumer_plugin() or self.plugin_id,
                                 required_capabilities=required or {'plugin.invoke'}, method=method, purpose=purpose)
                    # No body read is permitted merely to discover the authorization scope.
                    self.authz.check_scoped(**scope, resources=[])

                    def metadata(name, values):
                        context = build_host_context(user_id=self.user_id, instance_id=self.instance_id,
                            generation=self.generation, origin=origin, grant_ref=grant_ref)
                        params = build_invoke_params(contract=contract, method=name, input_payload=values, context=context,
                            deadline=datetime.now(timezone.utc) + timedelta(seconds=10))
                        params['_hostDataHandle'] = dict(data_handle or {})
                        result = validate_operation_result(self._rpc('plugin.invoke', params, timeout_ms=10_000, allow_callbacks=False))
                        if result['status'] != 'succeeded' or not isinstance(result.get('value'), dict):
                            raise PermissionError('source metadata is unavailable')
                        return result['value']

                    resource_refs = invocation_resources(self.plugin_id, method, input_payload, self.user_id, metadata)
                    self.authz.check_scoped(**scope, resources=resource_refs)
            else:
                self.authz.check(
                    grant_ref=grant_ref, plugin_id=self.plugin_id, user_id=self.user_id,
                    required_capabilities=required or {'plugin.invoke'}, purpose=purpose,
                    generation=self.generation, context_generation=self.generation,
                )
            # Overlay existing conversation/tool permission path when agent/tool origin.
            if origin in {"tool", "job"}:
                denial = _conversation_permission_denial(
                    contract=contract,
                    method=method,
                    agent_id=agent_id,
                    session_id=session_id,
                    input_payload=input_payload,
                    noninteractive=origin == "job",
                    effect=self._method_effects[(contract, method)],
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
            run_id=identity.run_id, job_id=identity.task_id,
        )
        if delegation:
            context.update(callerPluginId=delegation['callerPluginId'], delegationChain=delegation['chain'],
                           callerPrincipal=delegation['context']['callerPrincipal'],
                           traceId=delegation['context']['traceId'], origin='plugin')
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
            if resource_refs is not None:
                invoke_params["_hostDataHandle"]["authorizedResources"] = resource_refs
        if managed and method in CONFIG_METHODS:
            # A timed-out mutation may have committed, so invalidate before dispatch.
            default_store().bump_source_revision(self.plugin_id, self.user_id)
        result = self._rpc("plugin.invoke", invoke_params, timeout_ms=timeout_ms)
        try:
            return validate_operation_result(result)
        except ContractError as exc:
            raise PluginHostError(str(exc)) from exc

    def dispose(self) -> None:
        # An invocation owns the transport lock, so waiting on it without a
        # bound would make disable/dispose wait for a long network deadline.
        if not self._lock.acquire(timeout=2):
            self.registry.revoke(self.plugin_id, self.generation)
            process = self._proc
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            if not self._lock.acquire(timeout=4):
                raise PluginHostError("worker stopped but transport cleanup is still pending")
        try:
            self._dispose_locked()
        finally:
            self._lock.release()

    def _dispose_locked(self) -> None:
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
                            timeout_ms=2000,
                        )
                    except (PluginHostError, FrameError, BrokenPipeError):
                        pass
                    try:
                        self._rpc(
                            "runtime.dispose",
                            {"pluginId": self.plugin_id, "generation": self.generation},
                            allow_dead=True,
                            timeout_ms=2000,
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
                    for stream in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                        if stream:
                            stream.close()
                    self._proc = None
                if self._stderr_thread:
                    self._stderr_thread.join(timeout=1)

    def _drain_stderr(self, process) -> None:
        # Consume continuously. Never put arbitrary plugin output (credentials or
        # giant lines) in host exceptions/logs; diagnostics record byte counts.
        if process.stderr is None:
            return
        try:
            while chunk := process.stderr.read(4096):
                self._stderr_bytes += len(chunk)
        except (OSError, ValueError):
            return

    def _abort_transport(self, process, thread) -> None:
        self.registry.revoke(self.plugin_id, self.generation)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        thread.join(timeout=1)
        if self._stderr_thread:
            self._stderr_thread.join(timeout=1)
        if not thread.is_alive():
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
        self._proc = None
        from common.log import logger

        logger.error("[PluginRuntime] Transport stopped plugin=%s generation=%s stderr_bytes=%s",
                     self.plugin_id, self.generation, self._stderr_bytes)

    def _rpc(
        self, method: str, params: dict[str, Any], *, allow_dead: bool = False, timeout_ms: int = 30_000,
        allow_callbacks: bool = True
    ) -> dict[str, Any]:
        with self._lock:
            if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
                raise PluginHostError("worker not running")
            if self._proc.poll() is not None and not allow_dead:
                self.registry.revoke(self.plugin_id, self.generation)
                raise PluginHostError(f"worker exited with code {self._proc.returncode}")
            request_id = str(uuid.uuid4())
            if request_id in self._inflight:
                raise PluginHostError("duplicate in-flight request id")
            self._inflight.add(request_id)
            process = self._proc
            responses = queue.Queue(maxsize=1)
            deadline = time.monotonic() + max(timeout_ms, 1) / 1000
            outgoing = make_request(method, params, request_id)
            seen_callbacks = set()
            thread = None

            def exchange(frame):
                try:
                    write_frame(process.stdin, frame)
                    responses.put((read_frame(process.stdout), None))
                except Exception as exc:
                    responses.put((None, exc))

            try:
                while True:
                    if time.monotonic() >= deadline:
                        raise queue.Empty
                    thread = threading.Thread(target=exchange, args=(outgoing,), daemon=True)
                    thread.start()
                    response, error = responses.get(timeout=max(.001, deadline - time.monotonic()))
                    if error is not None:
                        self._abort_transport(process, thread)
                        if method == 'plugin.invoke':
                            raise PluginOutcomeUnknown('plugin transport failed; operation outcome unknown') from error
                        raise PluginHostError('plugin transport failed') from error
                    if 'method' in response:
                        callback_id = response.get('id')
                        try:
                            if (not allow_callbacks or method != 'plugin.invoke' or response['method'] != 'core.invoke' or
                                    not isinstance(callback_id, str) or callback_id in seen_callbacks):
                                raise PermissionError('callback is not bound to an active invocation')
                            seen_callbacks.add(callback_id)
                            from core.plugins.core_invoke import dispatch

                            # Execute on the original caller thread. Thread-local identity,
                            # policy and delegation must not be recreated from plugin input.
                            result = dispatch(self, response.get('params'), params)
                            outgoing = make_result(callback_id, result)
                        except PermissionError as exc:
                            outgoing = make_error(callback_id, -32001, str(exc))
                        except PluginOutcomeUnknown:
                            outgoing = make_result(callback_id, {'status': 'unknown', 'sideEffects': 'unknown'})
                        except Exception:
                            outgoing = make_error(callback_id, -32000, 'Core service invocation failed')
                        continue
                    if response.get('id') != request_id:
                        raise PluginHostError('response id mismatch')
                    if 'error' in response:
                        err = response['error']
                        if method == 'plugin.invoke' and err.get('code') == -32000:
                            raise PluginOutcomeUnknown('plugin failed during invocation; operation outcome unknown')
                        raise PluginHostError(f"{err.get('code')}: {err.get('message')}")
                    result = response.get('result')
                    if not isinstance(result, dict):
                        raise PluginHostError('result must be an object')
                    return result
            except queue.Empty as exc:
                self._abort_transport(process, thread)
                if method == 'plugin.invoke':
                    raise PluginOutcomeUnknown('plugin timed out; operation outcome unknown') from exc
                raise PluginHostError(f'plugin transport timed out during {method}') from exc
            finally:
                self._inflight.discard(request_id)


def _conversation_permission_denial(
    *,
    contract: str,
    method: str,
    agent_id: str | None,
    session_id: str | None,
    input_payload: Mapping[str, Any] | None = None,
    noninteractive: bool = False,
    effect: str | None = None,
) -> str | None:
    try:
        from agent.runtime.tool_invocation import permission_denial
    except Exception:
        return "Plugin conversation permission adapter unavailable"
    domain = contract.split("@", 1)[0].rsplit(".", 1)[-1]
    domain = {"tasks": "todos", "automation": "scheduler"}.get(domain, domain)
    actions = {
        "bills": {"create_ledger": "add", "update_ledger": "update", "delete_ledger": "delete",
                  "list_ledger": "list", "get_ledger": "get"},
        "todos": {"create_todo": "create", "update_todo": "update", "delete_todo": "delete",
                  "complete_todo": "complete", "complete_checklist_item": "complete",
                  "change_todo_status": "status", "move_todo": "move",
                  "list_todos": "list", "get_todo": "get"},
        "calendar": {"create_event": "create", "update_event": "update", "delete_event": "delete",
                     "list_events": "list", "get_event": "get"},
        "briefing": {"update_action": "decide", "start_briefing": "run", "complete_briefing": "run",
                     "update_item_status": "item_status", "create_rule": "add_rule",
                     "create_action_rule": "add_rule", "delete_action_rule": "delete_rule",
                     "update_preferences": "set_preferences"},
        "scheduler": {"create_task": "create", "update_task": "create", "delete_task": "delete",
                      "set_enabled": "enable"},
    }
    action = actions.get(domain, {}).get(method)
    if domain == "email":
        # Email sources historically enter through the briefing tool. Keep its
        # conversation policy while the plugin grant checks account capability.
        email_actions = {"list_accounts": "sources", "get_account": "sources", "list_sources": "sources",
                         "get_cursors": "sources", "fetch_messages": "mail",
                         "set_cursors": "run", "reset_cursors": "run"}
        action = email_actions.get(method)
        if action is None:
            return "Email connection management is not exposed as an Agent tool"
        domain = "briefing"
    if action is None and effect not in {None, "query"}:
        # Unknown mutations must never fall through the gateway's read default.
        action = {"todos": "update", "calendar": "update", "bills": "update",
                  "briefing": "run", "scheduler": "create", "elearning": "sync_files"}.get(domain)
        if action is None:
            return "No conversation permission mapping for plugin mutation"
    action = action or method
    arguments = dict(input_payload or {})
    arguments["action"] = action
    return permission_denial(domain, arguments, agent_id=agent_id, session_id=session_id,
                             noninteractive=noninteractive)


def _digest_tree(root: Path) -> str:
    from core.plugins.package_ops import _sha256_tree

    return _sha256_tree(root)
