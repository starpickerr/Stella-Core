"""OS-enforced boundaries for shell commands and their child processes."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from agent.permission.security_policy import rule


class SandboxUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessPlan:
    argv: list[str] | str
    shell: bool
    temp_dir: str | None
    status: str


def capability() -> dict:
    """Probe actual launch ability, not just whether a binary is on PATH."""
    if sys.platform == "darwin":
        executable = shutil.which("sandbox-exec")
        probe = [executable, "-p", "(version 1) (allow default)", "/usr/bin/true"] if executable else None
    elif sys.platform.startswith("linux"):
        executable = shutil.which("bwrap")
        probe = ([executable, "--die-with-parent", "--ro-bind", "/", "/", "--proc", "/proc",
                  "--dev-bind", "/dev", "/dev", "--", "/bin/true"] if executable else None)
    else:
        return {"status": "unavailable", "reason": "Process isolation is not supported on this platform."}
    if not probe:
        return {"status": "unavailable", "reason": "The process sandbox dependency is missing."}
    try:
        result = subprocess.run(probe, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "reason": "The process sandbox could not start."}
    if result.returncode:
        return {"status": "unavailable", "reason": "The process sandbox is installed but cannot run here."}
    return {"status": "enabled", "reason": "Shell child processes run inside an OS sandbox."}


def _seatbelt_literal(path: str) -> str:
    # Seatbelt reads UTF-8 path literals but does not decode JSON's \u escapes.
    # Escaping a Chinese workspace name makes an otherwise allowed directory
    # appear read-only to every shell child process.
    return json.dumps(os.path.realpath(os.path.expanduser(path)), ensure_ascii=False)


def _protected_paths() -> tuple[list[str], list[str]]:
    from common.state_dir import mcp_config_file, shared_root, state_root, user_root
    from config import get_data_root
    files = [str(Path(get_data_root()) / "config.json"), str(Path.home() / ".stella" / ".env"),
             str(mcp_config_file()), str(user_root() / "briefing" / "elearning.json"),
             str(shared_root() / ".env"), str(shared_root() / "session_prefs.json"),
             str(shared_root() / "projects.json")]
    folders = [str(user_root() / "briefing" / "elearning-sessions")]
    # Treat Agent instructions and executable skills as control data.
    files.extend(str(state_root() / name) for name in ("AGENT.md", "RULE.md", "BOOTSTRAP.md"))
    folders.append(str(shared_root() / "skills"))
    return files, folders


def prepare(command: str, cwd: str, roots: list[str], policy: dict, env: dict,
            *, approved_target: str | None = None) -> ProcessPlan:
    """Build one command plan; a constrained launch fails closed if isolation fails."""
    constrained = rule(policy, "workspace_outside") != "allow"
    state = capability()
    if state["status"] != "enabled":
        raise SandboxUnavailable(state["reason"])

    temp_dir = tempfile.mkdtemp(prefix="stella-shell-")
    env.update({"TMPDIR": temp_dir, "TMP": temp_dir, "TEMP": temp_dir,
                "XDG_CACHE_HOME": temp_dir})
    write_roots = list(dict.fromkeys(os.path.realpath(path) for path in [*roots, temp_dir]))
    files, folders = _protected_paths()
    protected = " ".join(f"(deny file-read* file-write* (literal {_seatbelt_literal(path)}))"
                         for path in files)
    protected += " " + " ".join(f"(deny file-read* file-write* (subpath {_seatbelt_literal(path)}))"
                                  for path in folders)
    if sys.platform == "darwin":
        permissions = ""
        if constrained:
            permissions = "(deny file-write*) " + " ".join(
                f"(allow file-write* (subpath {_seatbelt_literal(path)}))" for path in write_roots)
            if approved_target:
                permissions += f" (allow file-write* (literal {_seatbelt_literal(approved_target)}))"
        profile = f"(version 1) (allow default) {permissions} {protected}"
        argv = [shutil.which("sandbox-exec"), "-p", profile, "/bin/sh", "-c", command]
    else:
        executable = shutil.which("bwrap")
        if constrained:
            argv = [executable, "--die-with-parent", "--ro-bind", "/", "/", "--proc", "/proc",
                    "--dev-bind", "/dev", "/dev"]
            for path in write_roots:
                argv.extend(["--bind", path, path])
            if approved_target:
                target = os.path.realpath(approved_target)
                if not os.path.exists(target):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    raise SandboxUnavailable("This Linux sandbox cannot grant one new outside file; authorize its directory explicitly.")
                argv.extend(["--bind", target, target])
            argv.extend(["--chdir", cwd, "--", "/bin/sh", "-c", command])
        else:
            argv = [executable, "--die-with-parent", "--bind", "/", "/", "--proc", "/proc",
                    "--dev-bind", "/dev", "/dev", "--chdir", cwd, "--", "/bin/sh", "-c", command]
        # Hide control data inside the mount namespace even in full-access
        # mode. The tool gate also rejects direct requests for these paths,
        # but a script must not be able to read them indirectly.
        sandbox_options = []
        for path in files:
            if os.path.isfile(path):
                sandbox_options.extend(["--ro-bind", "/dev/null", os.path.realpath(path)])
        for path in folders:
            if os.path.isdir(path):
                sandbox_options.extend(["--tmpfs", os.path.realpath(path)])
        argv[argv.index("--"):argv.index("--")] = sandbox_options
    return ProcessPlan(argv, False, temp_dir, "enabled")


def current_policy_and_roots(cwd: str) -> tuple[dict, list[str]]:
    from agent.runtime.tool_invocation import _current_authorization
    from common.runtime_identity import current_identity
    identity = current_identity()
    _, context, _ = _current_authorization(None, identity.agent_id, identity.session_id, cwd, False)
    policy = context["policy"]
    roots = list(context["scope"].write_roots)
    roots.extend(policy.get("extra_roots") or [])
    return policy, roots
