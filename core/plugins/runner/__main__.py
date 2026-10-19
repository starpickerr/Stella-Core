"""stella-plugin-runner: JSON-RPC frames on stdin/stdout; logs on stderr only."""

from __future__ import annotations

import importlib.util
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.plugins.contract import validate_invoke_params, validate_operation_result
from core.plugins.protocol import (
    FrameError,
    make_error,
    make_result,
    read_frame,
    write_frame,
)

PLUGIN_API = "1.0.0"
ABI = "cp312"


class WorkerState:
    def __init__(self) -> None:
        self.initialized = False
        self.prepared = False
        self.disposed = False
        self.draining = False
        self.plugin_id: str | None = None
        self.generation: int | None = None
        self.manifest: dict[str, Any] | None = None
        self.handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None
        self.module: Any = None
        self.root: Path | None = None
        self.in_flight: set[str] = set()


STATE = WorkerState()


def _log(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _load_entry(manifest: dict[str, Any], root: Path) -> tuple[Callable[[dict[str, Any]], dict[str, Any]], Any]:
    runtime = manifest.get("runtime") or {}
    entry = runtime.get("entry")
    if not entry:
        raise RuntimeError("manifest missing runtime.entry")
    path = (root / entry).resolve()
    if not str(path).startswith(str(root.resolve())):
        raise RuntimeError("entry escapes plugin root")
    spec = importlib.util.spec_from_file_location("stella_plugin_entry", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load entry: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if callable(getattr(module, "handle_invoke", None)):
        return module.handle_invoke, module  # type: ignore[return-value]

    legacy = getattr(module, "handle", None)
    if not callable(legacy):
        raise RuntimeError("plugin entry must export handle_invoke or handle")

    def _adapt(invoke_params: dict[str, Any]) -> dict[str, Any]:
        payload = dict(invoke_params.get("input") or {})
        host_handle = invoke_params.get("_hostDataHandle")
        if host_handle:
            payload["_dataHandle"] = host_handle
        return legacy(str(invoke_params.get("method") or ""), payload)

    return _adapt, module


def _default_services(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    services = []
    for contract in (manifest.get("contributes") or {}).get("services") or []:
        services.append(
            {
                "contract": contract,
                "methods": [
                    {
                        "name": "ping",
                        "inputSchema": {"type": "object"},
                        "outputSchema": {"type": "object"},
                        "effect": "query",
                        "permissions": ["sample.ping"],
                        "resourceScope": ["user"],
                        "idempotency": False,
                        "timeoutMs": 5000,
                    }
                ],
            }
        )
    return services


def _handle(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("jsonrpc") != "2.0":
        return make_error(request.get("id"), -32600, "invalid jsonrpc")
    request_id = request.get("id")
    if not isinstance(request_id, str) or not request_id:
        return make_error(None, -32600, "id must be non-empty string")
    method = request.get("method")
    params = request.get("params") or {}
    if not isinstance(params, dict):
        return make_error(request_id, -32602, "params must be object")

    try:
        if method == "runtime.initialize":
            if STATE.disposed:
                raise RuntimeError("worker disposed")
            for key in (
                "pluginId",
                "packageDigest",
                "userId",
                "instanceId",
                "generation",
                "hostApi",
                "runtimeAbi",
                "platform",
            ):
                if key not in params:
                    raise RuntimeError(f"initialize missing {key}")
            STATE.plugin_id = params["pluginId"]
            STATE.generation = int(params["generation"])
            STATE.manifest = params.get("manifest") or {}
            root = Path(__import__("os").environ["STELLA_PLUGIN_ROOT"])
            STATE.root = root
            STATE.handler, STATE.module = _load_entry(STATE.manifest, root)
            STATE.initialized = True
            return make_result(
                request_id,
                {
                    "apiVersion": PLUGIN_API,
                    "abi": params["runtimeAbi"],
                    "pluginId": STATE.plugin_id,
                    "generation": STATE.generation,
                    "capabilities": [
                        "runtime.initialize",
                        "runtime.prepare",
                        "plugin.invoke",
                        "runtime.drain",
                        "runtime.dispose",
                    ],
                },
            )
        if method == "runtime.prepare":
            if not STATE.initialized:
                raise RuntimeError("not initialized")
            if int(params.get("generation", -1)) != STATE.generation:
                raise PermissionError("generation mismatch")
            STATE.prepared = True
            manifest = STATE.manifest or {}
            services = getattr(STATE.module, "SERVICE_DESCRIPTORS", None)
            if not isinstance(services, list):
                services = _default_services(manifest)
            return make_result(
                request_id,
                {
                    "services": services,
                    "contributions": manifest.get("contributes") or {},
                },
            )
        if method == "plugin.invoke":
            if STATE.draining:
                raise RuntimeError("worker draining")
            if not STATE.prepared or STATE.handler is None:
                raise RuntimeError("not prepared")
            invoke_params = validate_invoke_params(params)
            ctx = invoke_params["context"]
            if int(ctx.get("generation", -1)) != STATE.generation:
                raise PermissionError("stale generation")
            if ctx.get("instanceId") and STATE.plugin_id and False:
                pass
            # Reject plugin-supplied identity overrides sneaking into input.
            if "userId" in invoke_params["input"] or "grantRef" in invoke_params["input"]:
                raise PermissionError("input must not override host identity fields")
            deadline = datetime.fromisoformat(invoke_params["deadline"].replace("Z", "+00:00"))
            if deadline < datetime.now(timezone.utc):
                raise PermissionError("deadline expired")
            # Attach host data handle after validation (not part of public InvokeParams schema).
            call_params = dict(invoke_params)
            if "_hostDataHandle" in params:
                call_params["_hostDataHandle"] = params["_hostDataHandle"]
            STATE.in_flight.add(request_id)
            try:
                result = STATE.handler(call_params)
            finally:
                STATE.in_flight.discard(request_id)
            if not isinstance(result, dict):
                raise RuntimeError("handler must return OperationResult object")
            return make_result(request_id, validate_operation_result(result))
        if method == "runtime.drain":
            STATE.draining = True
            return make_result(
                request_id,
                {
                    "drained": True,
                    "inFlight": sorted(STATE.in_flight),
                    "generation": STATE.generation,
                },
            )
        if method == "runtime.dispose":
            STATE.disposed = True
            STATE.prepared = False
            STATE.handler = None
            return make_result(request_id, {"disposed": True, "generation": STATE.generation})
        return make_error(request_id, -32601, f"method not found: {method}")
    except PermissionError as exc:
        return make_error(request_id, -32001, str(exc))
    except Exception as exc:
        _log(traceback.format_exc())
        return make_error(request_id, -32000, str(exc))


class _StdoutToStderr:
    encoding = "utf-8"
    errors = "replace"
    name = "<plugin-stdout-redirect>"

    def write(self, data) -> int:
        if isinstance(data, bytes):
            return sys.__stderr__.buffer.write(data)
        return sys.__stderr__.write(data)

    def flush(self) -> None:
        sys.__stderr__.flush()

    def fileno(self) -> int:
        return sys.__stderr__.fileno()

    def isatty(self) -> bool:
        return False

    @property
    def buffer(self):
        return sys.__stderr__.buffer


def main() -> int:
    stdin = sys.stdin.buffer
    protocol_out = sys.stdout.buffer
    sys.stdout = _StdoutToStderr()  # type: ignore[assignment]
    while True:
        try:
            request = read_frame(stdin)
        except FrameError as exc:
            _log(f"frame error: {exc}")
            write_frame(protocol_out, make_error(None, -32700, str(exc)))
            return 1
        except Exception:
            break
        response = _handle(request)
        write_frame(protocol_out, response)
        if STATE.disposed:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
