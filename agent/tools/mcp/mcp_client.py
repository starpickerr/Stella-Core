"""
MCP (Model Context Protocol) client module.

Implements JSON-RPC 2.0 over stdio, SSE and Streamable HTTP transports
without any external MCP SDK dependency.
"""

import json
import contextvars
import os
import queue
import subprocess
import threading
import time
import socket
import urllib.request
import urllib.error
from typing import Optional
from contextlib import contextmanager

from common.log import logger


# Aliases accepted for the Streamable HTTP transport type
_STREAMABLE_HTTP_ALIASES = {"streamable-http", "streamable_http", "streamablehttp", "http"}
_CANCEL_SOCKET_TIMEOUT = 5
_HTTP_REQUEST = contextvars.ContextVar('mcp_http_request', default=None)


class _HttpRequest:
    """Own only this request's responses, including a late-opened response."""

    def __init__(self):
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.responses = set()

    def attach(self, response):
        with self.lock:
            if self.cancelled.is_set():
                try:
                    response.close()
                except (OSError, ValueError):
                    pass
                raise McpCancelledError('MCP request abandoned')
            self.responses.add(response)

    def detach(self, response):
        with self.lock:
            self.responses.discard(response)

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            responses = tuple(self.responses)

        def interrupt():
            for response in responses:
                # Closing a buffered HTTPResponse can wait for its reader's
                # lock. Interrupt the owned socket first, outside the waiter.
                stream = getattr(response, 'fp', None)
                raw = getattr(stream, 'raw', None)
                connection = getattr(raw, '_sock', None)
                if connection is not None:
                    try:
                        connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                try:
                    response.close()
                except (OSError, ValueError):
                    pass

        if responses:
            threading.Thread(target=interrupt, name='mcp-http-interrupt', daemon=True).start()


class McpCancelledError(Exception):
    """A caller cancelled one in-flight MCP request."""


def _check_cancelled(cancel_event):
    from core.plugins.caller import remaining_invocation_seconds
    from agent.protocol.cancel import AgentCancelledError
    try:
        remaining_invocation_seconds()
    except AgentCancelledError as exc:
        raise McpCancelledError('MCP call cancelled') from exc
    if cancel_event is not None and cancel_event.is_set():
        raise McpCancelledError("MCP call cancelled")
    request = _HTTP_REQUEST.get()
    if request is not None and request.cancelled.is_set():
        raise McpCancelledError('MCP request abandoned')


def _bounded_timeout(timeout):
    from core.plugins.caller import remaining_invocation_seconds
    from agent.protocol.cancel import AgentCancelledError
    try:
        remaining = remaining_invocation_seconds()
    except AgentCancelledError as exc:
        raise McpCancelledError('MCP call cancelled') from exc
    return min(timeout, remaining) if remaining is not None else timeout


def _http_wait(operation, cancel_event):
    """Bound open, headers and streaming reads by the original total budget."""
    request = _HttpRequest()
    replies = queue.Queue(maxsize=1)
    context = contextvars.copy_context()

    def run():
        token = _HTTP_REQUEST.set(request)
        try:
            _check_cancelled(cancel_event)
            replies.put((True, operation()))
        except BaseException as exc:
            replies.put((False, exc))
        finally:
            _HTTP_REQUEST.reset(token)

    threading.Thread(target=lambda: context.run(run), name='mcp-http-request', daemon=True).start()
    try:
        while True:
            _check_cancelled(cancel_event)
            try:
                succeeded, value = replies.get(timeout=_bounded_timeout(.05))
            except queue.Empty:
                continue
            _check_cancelled(cancel_event)
            if succeeded:
                return value
            raise value
    except BaseException:
        request.cancel()
        raise


# System env vars a stdio MCP subprocess legitimately needs to run
# (node/python/npx toolchains). Everything else is dropped by default so
# API keys living in the agent's own environment don't leak into servers.
_STDIO_ENV_PASSTHROUGH = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "TZ", "TMPDIR", "NODE_PATH", "NVM_DIR", "PYTHONPATH", "PYTHONHOME",
    # Windows essentials
    "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "APPDATA",
    "LOCALAPPDATA", "USERPROFILE", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "PROGRAMDATA", "TEMP", "TMP", "HOMEDRIVE", "HOMEPATH",
)
# Sensitive name patterns never forwarded, even under inherit_full_env.
_STDIO_ENV_SENSITIVE = ("_KEY", "_SECRET", "_TOKEN", "_PASSWORD", "_PASSWD", "_CREDENTIAL")


def _oauth_redirect_uri() -> str:
    """Build the OAuth callback URI served by the desktop backend."""
    try:
        from config import conf
        base = (conf().get("mcp_oauth_redirect_base") or "").strip().rstrip("/")
        if not base:
            port = int(os.environ.get("STELLA_BACKEND_PORT") or 9876)
            base = f"http://127.0.0.1:{port}"
    except Exception:
        base = "http://127.0.0.1:9876"
    return f"{base}/mcp/oauth/callback"


class McpClient:
    """Single MCP Server client supporting stdio, SSE and Streamable HTTP transports."""

    def __init__(self, config: dict):
        """
        config examples:
          stdio:           {"name": "filesystem", "type": "stdio", "command": "npx", "args": [...]}
          SSE:             {"name": "my-api",    "type": "sse",   "url": "http://localhost:8000/sse"}
          streamable-http: {"name": "pubmed",    "type": "streamable-http", "url": "https://x/mcp"}
        """
        self._lifecycle_lock = threading.RLock()
        self._closed = False
        self._remote_responses = set()
        self.on_authorized = None
        self.config = config
        self.name: str = config.get("name", "unknown")
        raw_transport: str = config.get("type", "stdio")
        # Per-server timeout for tool calls (default 120s, suitable for data queries)
        self._timeout: int = int(config.get("timeout", 120))
        # Normalize streamable-http aliases to a single internal key
        self.transport: str = (
            "streamable-http"
            if raw_transport.lower() in _STREAMABLE_HTTP_ALIASES
            else raw_transport
        )

        # stdio state
        self._proc: Optional[subprocess.Popen] = None
        self._read_queue: queue.Queue = queue.Queue()

        # SSE state
        self._sse_url: Optional[str] = None
        self._post_url: Optional[str] = None  # endpoint for sending messages (resolved from SSE)

        # Streamable HTTP state
        self._http_url: Optional[str] = None
        self._http_headers: dict = {}  # extra headers from user config (e.g. Authorization)
        self._http_session_id: Optional[str] = None  # Mcp-Session-Id assigned by the server

        # OAuth state (streamable-http only). Lazily created when the server
        # responds with 401 and the user has not supplied a static token.
        self._oauth = None  # OAuthHandler instance
        # Set to True once a 401 could not be satisfied and the user must
        # complete the browser authorization. Callers can surface this state.
        self.needs_auth: bool = False

        # Shared state
        self._next_id = 1
        self._id_lock = threading.Lock()
        # _call_lock serializes all requests on the single stdio pipe.
        # SSE and streamable-http use independent HTTP requests, so they
        # do not acquire this lock (see _send_request).
        self._call_lock = threading.Lock()
        # _http_lock protects _http_session_id initialization across
        # concurrent streamable-http requests.
        self._http_lock = threading.Lock()
        self._initialized = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Connect and perform the MCP handshake. Returns True on success."""
        if self._closed:
            return False
        try:
            if self.transport == "stdio":
                return self._init_stdio()
            elif self.transport == "sse":
                return self._init_sse()
            elif self.transport == "streamable-http":
                return self._init_streamable_http()
            else:
                logger.warning(f"[MCP:{self.name}] Unknown transport type: {self.transport!r}")
                return False
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] Initialization failed: {e}")
            return False

    def list_tools(self) -> list:
        """Return the tool list from this server.

        Each item is a dict: {"name": str, "description": str, "inputSchema": dict}
        """
        try:
            resp = self._send_request("tools/list", {})
            tools = resp.get("result", {}).get("tools", [])
            return [
                {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "inputSchema": t.get("inputSchema", {}),
                }
                for t in tools
            ]
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] list_tools failed: {e}")
            return []

    def call_tool_result(self, name: str, arguments: dict, cancel_event=None, *, meta=None) -> dict:
        params = {"name": name, "arguments": arguments}
        if meta is not None:
            params["_meta"] = meta
        response = (self._send_request("tools/call", params) if cancel_event is None else
                    self._send_request("tools/call", params, cancel_event=cancel_event))
        if response.get('error'):
            raise RuntimeError((response['error'] or {}).get('message','MCP request failed'))
        result=response.get('result',{})
        if result.get('isError'):
            raise RuntimeError('\n'.join(item.get('text','') for item in result.get('content',[]) if item.get('type')=='text') or 'MCP tool failed')
        return result

    def call_tool(self, name: str, arguments: dict, cancel_event=None) -> str:
        result=self.call_tool_result(name,arguments,cancel_event=cancel_event)
        return "\n".join(item.get('text','') for item in result.get('content',[]) if item.get('type')=='text')

    def shutdown(self):
        """A closed generation cannot reconnect or spawn another process."""
        with self._lifecycle_lock:
            self._closed = True
            for response in tuple(self._remote_responses):
                response.close()
            self._remote_responses.clear()
            self._shutdown_connection()

    def _ensure_open(self):
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError('MCP connection is closed')

    @contextmanager
    def _remote_response(self, request, timeout):
        self._ensure_open()
        response = urllib.request.urlopen(request, timeout=_bounded_timeout(timeout))
        control = _HTTP_REQUEST.get()
        if control is not None:
            control.attach(response)
        with self._lifecycle_lock:
            abandoned = self._closed
            # Capture the session before publishing the response, so shutdown
            # cannot miss an id assigned by an in-flight initialize request.
            session_id = response.headers.get('Mcp-Session-Id')
            if self.transport == 'streamable-http' and session_id:
                with self._http_lock:
                    if not self._http_session_id:
                        self._http_session_id = session_id
            if not abandoned:
                self._remote_responses.add(response)
        if abandoned:
            response.close()
            self.shutdown()
            raise RuntimeError('MCP connection closed while request was in flight')
        try:
            yield response
        finally:
            if control is not None:
                control.detach(response)
            with self._lifecycle_lock:
                self._remote_responses.discard(response)
            response.close()

    def _shutdown_connection(self):
        if self._proc is not None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            logger.debug(f"[MCP:{self.name}] stdio process terminated")

        # Best-effort streamable-http session termination
        if self.transport == "streamable-http" and self._http_session_id and self._http_url:
            try:
                req = urllib.request.Request(
                    self._http_url,
                    method="DELETE",
                    headers={"Mcp-Session-Id": self._http_session_id, **self._http_headers},
                )
                with urllib.request.urlopen(req, timeout=5):
                    pass
            except Exception:
                pass
            self._http_session_id = None

        self._initialized = False

    # ------------------------------------------------------------------
    # stdio transport
    # ------------------------------------------------------------------

    def _init_stdio(self) -> bool:
        command = self.config.get("command")
        if not command:
            logger.warning(f"[MCP:{self.name}] stdio config missing 'command'")
            return False

        if not self._command_allowed(command):
            return False

        args = self.config.get("args", [])
        env = self._build_stdio_env(self.config.get("env", None))

        with self._lifecycle_lock:
            if self._closed:
                return False
            process = self._proc = subprocess.Popen(
                [command] + list(args),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
            )
        logger.debug(f"[MCP:{self.name}] stdio process started (pid={process.pid})")

        threading.Thread(
            target=self._drain_stderr, args=(process.stderr,), daemon=True, name=f"mcp-stderr-{self.name}"
        ).start()
        threading.Thread(
            target=self._drain_stdout, args=(process.stdout,), daemon=True, name=f"mcp-stdout-{self.name}"
        ).start()

        return self._handshake()

    def _command_allowed(self, command: str) -> bool:
        """Check the executable against an optional command allowlist.

        Disabled by default (empty allowlist = allow everything) to keep
        existing mcp.json configs working. Set config.json's
        ``mcp_stdio_command_allowlist`` (e.g. ["npx", "node", "python", "uvx"])
        to restrict which executables MCP stdio servers may launch.
        """
        try:
            from config import conf
            allowlist = conf().get("mcp_stdio_command_allowlist") or []
        except Exception:
            allowlist = []
        if not allowlist:
            return True
        base = os.path.basename(str(command)).lower()
        if base.endswith(".exe"):
            base = base[:-4]
        if base in {str(c).lower() for c in allowlist}:
            return True
        logger.warning(
            f"[MCP:{self.name}] command '{command}' not in "
            f"mcp_stdio_command_allowlist, refusing to start"
        )
        return False

    def _build_stdio_env(self, extra_env) -> dict:
        """Build the environment for a stdio MCP subprocess.

        By default only safe system vars plus the user's explicit ``env``
        block are passed through, so API keys in the agent's own environment
        are not leaked to the subprocess. Set the per-server config
        ``inherit_full_env: true`` to restore full inheritance (obviously
        sensitive names are still stripped).
        """
        extra_env = extra_env or {}
        if self.config.get("inherit_full_env"):
            env = {
                k: v for k, v in os.environ.items()
                if not any(p in k.upper() for p in _STDIO_ENV_SENSITIVE)
            }
        else:
            env = {k: os.environ[k] for k in _STDIO_ENV_PASSTHROUGH if k in os.environ}
        # User-declared env is explicit authorization, always applied last.
        env.update({str(k): str(v) for k, v in extra_env.items()})
        return env

    def _url_allowed(self, url: str) -> bool:
        """SSRF guard for remote (SSE / streamable-http) MCP endpoints.

        Delegates to the shared ``validate_url_safe`` helper, which is a no-op
        unless ``web_security_ssrf_protection`` is enabled, so local/LAN MCP
        servers keep working by default.
        """
        try:
            from agent.tools.utils.url_safety import validate_url_safe
            validate_url_safe(url)
            return True
        except ValueError as e:
            logger.warning(f"[MCP:{self.name}] url blocked: {e}")
            return False

    def _drain_stderr(self, stream):
        try:
            for line in stream:
                line = line.strip()
                if line:
                    logger.warning(f"[MCP:{self.name}] stderr: {line}")
        except (OSError, ValueError):
            pass  # Shutdown may close a process stream while it is being read.

    def _drain_stdout(self, stream):
        """Background thread: read lines from stdout and put them into the queue."""
        try:
            for line in stream:
                self._read_queue.put(line)
        except Exception:
            pass
        finally:
            try:
                self._read_queue.put("")
            except Exception:
                pass

    def _readline_with_timeout(self, timeout: Optional[int] = None, cancel_event=None) -> str:
        """Read one line from stdio stdout with a hard timeout (cross-platform).

        Uses the per-server timeout from mcp.json config when no explicit
        timeout is provided.
        """
        effective = _bounded_timeout(timeout if timeout is not None else self._timeout)
        deadline = time.monotonic() + effective
        while True:
            _check_cancelled(cancel_event)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"[MCP:{self.name}] stdio read timed out after {effective}s")
            try:
                line = self._read_queue.get(timeout=min(remaining, .05))
                break
            except queue.Empty:
                continue
        if not line:
            raise IOError(f"[MCP:{self.name}] stdio process closed unexpectedly")
        return line

    def _stdio_send(self, message: dict, cancel_event=None) -> dict:
        """Send a JSON-RPC message over stdio and read the response."""
        _check_cancelled(cancel_event)
        raw = json.dumps(message) + "\n"
        self._proc.stdin.write(raw)
        self._proc.stdin.flush()

        expected_id = message.get("id")
        while True:
            try:
                line = self._readline_with_timeout(cancel_event=cancel_event)
            except (McpCancelledError, PermissionError, TimeoutError):
                try:
                    self._send_notification("notifications/cancelled", {
                        "requestId": expected_id, "reason": "User cancelled"
                    })
                except Exception:
                    pass
                raise
            if not line:
                raise IOError(f"[MCP:{self.name}] stdio process closed unexpectedly")
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" not in data:
                logger.debug(f"[MCP:{self.name}] notification skipped: {data.get('method', '?')}")
                continue
            # Verify response id matches request id to avoid consuming a stale
            # response left over from a previously failed/timed-out request.
            if data.get("id") != expected_id:
                logger.warning(
                    f"[MCP:{self.name}] Stale response id={data.get('id')} "
                    f"(expected {expected_id}), skipping"
                )
                continue
            return data

    # ------------------------------------------------------------------
    # SSE transport
    # ------------------------------------------------------------------

    def _init_sse(self) -> bool:
        url = self.config.get("url")
        if not url:
            logger.warning(f"[MCP:{self.name}] SSE config missing 'url'")
            return False

        if not self._url_allowed(url):
            return False

        self._sse_url = url

        # Read the first SSE event to discover the POST endpoint
        try:
            self._post_url = self._sse_discover_endpoint()
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] SSE endpoint discovery failed: {e}")
            return False

        return self._handshake()

    def _sse_discover_endpoint(self) -> str:
        """Open SSE stream and read the 'endpoint' event to learn the POST URL."""
        req = urllib.request.Request(
            self._sse_url,
            headers={"Accept": "text/event-stream"},
        )
        endpoint = None
        with self._remote_response(req, timeout=10) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\n\r")
                if line.startswith("data:"):
                    data = line[len("data:"):].strip()
                    # Some servers send JSON with a "uri" or plain path
                    if data.startswith("{"):
                        parsed = json.loads(data)
                        endpoint = parsed.get("uri") or parsed.get("url") or parsed.get("endpoint")
                    elif data.startswith("http"):
                        # Plain absolute URL
                        endpoint = data
                    else:
                        # Relative path: resolve against SSE base
                        from urllib.parse import urljoin
                        endpoint = urljoin(self._sse_url, data)
                    break
        if not endpoint:
            raise ValueError(f"[MCP:{self.name}] No endpoint event received from SSE stream")
        # Re-validate the server-supplied POST endpoint to block redirects
        # into internal addresses (SSRF guard; no-op when protection is off).
        from agent.tools.utils.url_safety import validate_url_safe
        validate_url_safe(endpoint)
        return endpoint

    def _sse_send(self, message: dict, cancel_event=None) -> dict:
        """POST a JSON-RPC message to the server and return the response."""
        _check_cancelled(cancel_event)
        body = json.dumps(message).encode("utf-8")
        req = urllib.request.Request(
            self._post_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self._remote_response(req, timeout=_CANCEL_SOCKET_TIMEOUT if cancel_event is not None else 30) as resp:
            _check_cancelled(cancel_event)
            raw = resp.read().decode("utf-8")
            _check_cancelled(cancel_event)
            return json.loads(raw)

    # ------------------------------------------------------------------
    # Streamable HTTP transport (MCP spec 2025-03-26)
    # ------------------------------------------------------------------

    def _init_streamable_http(self) -> bool:
        url = self.config.get("url")
        if not url:
            logger.warning(f"[MCP:{self.name}] streamable-http config missing 'url'")
            return False

        if not self._url_allowed(url):
            return False

        self._http_url = url
        # Allow user-provided headers (e.g. {"Authorization": "Bearer xxx"})
        extra_headers = self.config.get("headers") or {}
        if isinstance(extra_headers, dict):
            self._http_headers = {str(k): str(v) for k, v in extra_headers.items()}

        # Restore any previously stored OAuth credentials for this server so a
        # restart reuses the token instead of forcing re-authorization.
        self._maybe_load_oauth()

        return self._handshake()

    # ------------------------------------------------------------------
    # OAuth helpers (streamable-http only)
    # ------------------------------------------------------------------

    def _has_static_auth(self) -> bool:
        """True when the user supplied their own Authorization header."""
        return any(k.lower() == "authorization" for k in self._http_headers)

    def _maybe_load_oauth(self) -> None:
        """Attach an OAuthHandler when stored credentials exist for this server."""
        if self._has_static_auth():
            return
        try:
            from agent.tools.mcp.mcp_oauth import OAuthHandler, load_server_record
        except Exception:
            return
        rec = load_server_record(self.name)
        # Only create a handler when we have something to reuse; otherwise it
        # is created lazily on the first 401.
        if rec.get("access_token") or rec.get("client_id"):
            self._oauth = OAuthHandler(
                server_name=self.name,
                resource_url=self._http_url,
                redirect_uri=_oauth_redirect_uri(),
                scope=self.config.get("scope", ""),
                on_authorized=self.on_authorized,
            )

    def _current_bearer(self) -> Optional[str]:
        """Return a valid access token, refreshing if needed."""
        if self._oauth is None:
            return None
        return self._oauth.get_valid_access_token()

    def _begin_oauth(self, www_authenticate: str = "") -> None:
        """Kick off the OAuth flow after a 401: discover, register, prompt user."""
        self._ensure_open()
        if self._has_static_auth():
            return
        try:
            from agent.tools.mcp.mcp_oauth import OAuthHandler
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] OAuth module unavailable: {e}")
            return

        if self._oauth is None:
            self._oauth = OAuthHandler(
                server_name=self.name,
                resource_url=self._http_url,
                redirect_uri=_oauth_redirect_uri(),
                scope=self.config.get("scope", ""),
                on_authorized=self.on_authorized,
            )

        if not self._oauth.ensure_registered(www_authenticate):
            logger.warning(
                f"[MCP:{self.name}] OAuth discovery/registration failed; "
                f"cannot authorize automatically"
            )
            return

        self._ensure_open()
        self._oauth.on_authorized = self.on_authorized
        auth_url = self._oauth.build_authorization_url()
        if not auth_url:
            logger.warning(f"[MCP:{self.name}] Failed to build authorization URL")
            return

        self._ensure_open()
        self.needs_auth = True
        logger.warning(
            f"[MCP:{self.name}] ⚠️  Authorization required. Open this URL in a "
            f"browser to authorize, then this server will come online automatically:\n"
            f"    {auth_url}"
        )
        # On a machine with a local browser (desktop/dev), open it directly.
        if os.environ.get("STELLA_DESKTOP") == "1" or not os.environ.get("STELLA_HEADLESS"):
            try:
                import webbrowser
                webbrowser.open(auth_url)
            except Exception:
                pass

    def _streamable_http_send(self, message: dict, cancel_event=None) -> dict:
        """POST a JSON-RPC request and return the response (JSON or SSE-wrapped)."""
        return self._streamable_http_post(message, expect_response=True, cancel_event=cancel_event)

    def _handle_401(self, err, message: dict, expect_response: bool, retried: bool, cancel_event=None) -> dict:
        """Handle a 401: refresh the token and retry once, else begin OAuth."""
        www_auth = ""
        try:
            www_auth = err.headers.get("WWW-Authenticate", "") or ""
        except Exception:
            pass
        try:
            err.read()
        except Exception:
            pass

        # First try a silent refresh with the stored refresh token.
        _check_cancelled(cancel_event)
        if not retried and self._oauth is not None and self._oauth.refresh():
            _check_cancelled(cancel_event)
            logger.info(f"[MCP:{self.name}] Token refreshed after 401, retrying")
            return self._streamable_http_post(message, expect_response, _retried=True,
                                              cancel_event=cancel_event)

        # No usable token — start (or restart) the interactive OAuth flow.
        self._begin_oauth(www_auth)
        raise IOError(
            f"[MCP:{self.name}] streamable-http HTTP 401: authorization required "
            f"(complete the OAuth flow to enable this server)"
        )

    def _streamable_http_post(self, message: dict, expect_response: bool, _retried: bool = False,
                              cancel_event=None) -> dict:
        """
        POST a JSON-RPC message over Streamable HTTP.

        Per the spec, the response Content-Type can be either:
          - application/json   -> single JSON-RPC response in body
          - text/event-stream  -> SSE stream; we read until we get a matching response
        """
        _check_cancelled(cancel_event)
        body = json.dumps(message).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        # Read session id under lock to avoid racing with the
        # initialization write below during concurrent requests.
        with self._http_lock:
            sid = self._http_session_id
        if sid:
            headers["Mcp-Session-Id"] = sid
        headers.update(self._http_headers)
        # Inject OAuth bearer token when we have one (unless the user set a
        # static Authorization header, which takes precedence).
        if not self._has_static_auth():
            token = self._current_bearer()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(
            self._http_url,
            data=body,
            method="POST",
            headers=headers,
        )

        try:
            with self._remote_response(req, timeout=_CANCEL_SOCKET_TIMEOUT if cancel_event is not None else 30) as resp:
                _check_cancelled(cancel_event)
                status = resp.status if hasattr(resp, "status") else resp.getcode()

                # Notifications: server may reply with 202 Accepted and no body
                if not expect_response or status == 202:
                    try:
                        resp.read()
                    except Exception:
                        pass
                    return {}

                content_type = (resp.headers.get("Content-Type") or "").lower()
                expected_id = message.get("id")

                if "text/event-stream" in content_type:
                    return self._read_sse_response(resp, expected_id, cancel_event=cancel_event)

                raw = resp.read().decode("utf-8")
                _check_cancelled(cancel_event)
                if not raw:
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            # 401 is the spec-compliant "needs authorization" signal.
            self._ensure_open()
            if e.code == 401 and not self._has_static_auth():
                return self._handle_401(e, message, expect_response, _retried, cancel_event=cancel_event)
            # Surface the server-provided error body for easier debugging
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            raise IOError(
                f"[MCP:{self.name}] streamable-http HTTP {e.code}: {detail[:200]}"
            )

    def _read_sse_response(self, resp, expected_id, cancel_event=None) -> dict:
        """Read an SSE stream and return the first JSON-RPC response with matching id."""
        data_buf: list = []
        for raw_line in resp:
            _check_cancelled(cancel_event)
            line = raw_line.decode("utf-8").rstrip("\n\r")
            if line == "":
                # End of an SSE event, attempt to parse accumulated data
                if data_buf:
                    payload = "\n".join(data_buf)
                    data_buf = []
                    try:
                        msg = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    # Skip notifications / mismatched ids
                    if "id" not in msg:
                        continue
                    if expected_id is None or msg.get("id") == expected_id:
                        return msg
                continue
            if line.startswith(":"):
                continue  # SSE comment / keepalive
            if line.startswith("data:"):
                data_buf.append(line[len("data:"):].lstrip())
            # Ignore 'event:' / 'id:' lines; we only care about JSON-RPC payloads

        raise IOError(f"[MCP:{self.name}] streamable-http SSE stream closed before response")

    # ------------------------------------------------------------------
    # Common JSON-RPC helpers
    # ------------------------------------------------------------------

    def _next_request_id(self) -> int:
        with self._id_lock:
            rid = self._next_id
            self._next_id += 1
        return rid

    def _build_request(self, method: str, params: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": method,
            "params": params,
        }

    def _build_notification(self, method: str, params: dict) -> dict:
        return {"jsonrpc": "2.0", "method": method, "params": params}

    def _send_request(self, method: str, params: dict, cancel_event=None) -> dict:
        """Send a request and return the full response dict."""
        _check_cancelled(cancel_event)
        self._ensure_open()
        if not self._initialized and method != "initialize":
            raise RuntimeError(f"[MCP:{self.name}] Client not initialized")

        message = self._build_request(method, params)

        from core.plugins.caller import current_invocation_deadline
        from core.plugins.cancellation import current_cancellation_events
        controlled_http = (self.transport in {'sse', 'streamable-http'} and _HTTP_REQUEST.get() is None
                           and (cancel_event is not None or current_invocation_deadline() is not None
                                or current_cancellation_events()))
        if controlled_http:
            send = self._sse_send if self.transport == 'sse' else self._streamable_http_send
            return _http_wait(lambda: send(message, cancel_event=cancel_event), cancel_event)

        # stdio transport uses a single pipe and must be serialized.
        # SSE and streamable-http use independent HTTP requests and
        # can safely run concurrently across sessions.
        if self.transport == "stdio":
            while not self._call_lock.acquire(timeout=_bounded_timeout(0.05)):
                _check_cancelled(cancel_event)
            try:
                _check_cancelled(cancel_event)
                self._ensure_open()
                result = (self._stdio_send(message) if cancel_event is None else
                          self._stdio_send(message, cancel_event=cancel_event))
            finally:
                self._call_lock.release()
        elif self.transport == "sse":
            result = (self._sse_send(message) if cancel_event is None else
                      self._sse_send(message, cancel_event=cancel_event))
        elif self.transport == "streamable-http":
            result = (self._streamable_http_send(message) if cancel_event is None else
                      self._streamable_http_send(message, cancel_event=cancel_event))
        else:
            raise ValueError(f"[MCP:{self.name}] Unsupported transport: {self.transport}")
        _check_cancelled(cancel_event)
        return result

    def _send_notification(self, method: str, params: dict):
        """Fire-and-forget notification (no response expected)."""
        self._ensure_open()
        notification = self._build_notification(method, params)
        raw = json.dumps(notification) + "\n"

        if self.transport == "stdio":
            self._proc.stdin.write(raw)
            self._proc.stdin.flush()
        elif self.transport == "sse":
            body = raw.encode("utf-8")
            req = urllib.request.Request(
                self._post_url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with self._remote_response(req, timeout=10):
                    pass
            except Exception:
                pass  # notifications are fire-and-forget
        elif self.transport == "streamable-http":
            try:
                self._streamable_http_post(notification, expect_response=False)
            except Exception:
                pass  # notifications are fire-and-forget

    def _handshake(self) -> bool:
        """Perform the MCP initialize / notifications/initialized handshake."""
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "Stella", "version": "1.0"},
        }
        # Admission and publication are coordinated with shutdown.
        with self._lifecycle_lock:
            if self._closed:
                return False
            self._initialized = True
        try:
            resp = self._send_request("initialize", init_params)
        except Exception as e:
            self._initialized = False
            logger.warning(f"[MCP:{self.name}] Handshake initialize failed: {e}")
            return False

        if "error" in resp:
            self._initialized = False
            logger.warning(f"[MCP:{self.name}] Handshake error")
            return False

        with self._lifecycle_lock:
            if self._closed:
                self._initialized = False
                return False
        self._send_notification("notifications/initialized", {})
        with self._lifecycle_lock:
            if self._closed:
                self._initialized = False
                return False
        logger.debug(f"[MCP:{self.name}] Handshake complete")
        return True


class McpClientRegistry:
    """Clients owned by one ToolManager, never shared across workspaces/users."""

    def __init__(self):
        self._clients: dict[str, McpClient] = {}
        self._registry_lock = threading.Lock()

    def start_all(self, configs: list) -> None:
        """Initialize McpClient for each config entry; skip failures with a warning."""
        if not configs:
            return

        for cfg in configs:
            name = cfg.get("name", "<unnamed>")
            client = McpClient(cfg)
            ok = client.initialize()
            if ok:
                with self._registry_lock:
                    self._clients[name] = client
                logger.info(f"[MCP] Server '{name}' initialized successfully")
            else:
                logger.warning(f"[MCP] Server '{name}' failed to initialize — skipping")

    def get(self, server_name: str) -> Optional[McpClient]:
        """Return the initialized client for server_name, or None."""
        with self._registry_lock:
            return self._clients.get(server_name)

    def all_clients(self) -> dict:
        """Return a copy of the {name: McpClient} mapping."""
        with self._registry_lock:
            return dict(self._clients)

    def shutdown_all(self) -> None:
        """Shut down all managed clients."""
        with self._registry_lock:
            clients = list(self._clients.values())
            self._clients.clear()

        for client in clients:
            try:
                client.shutdown()
            except Exception as e:
                logger.warning(f"[MCP] Error shutting down '{client.name}': {e}")

        logger.info("[MCP] All servers shut down")
