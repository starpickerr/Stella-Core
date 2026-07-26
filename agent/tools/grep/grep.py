"""
Grep tool - search file contents across the workspace (grep-like).

Backend strategy (4-tier, first available wins):
    1. ripgrep (rg)               - fastest; respects .gitignore natively
    2. grep -E                    - POSIX systems always have it
    3. PowerShell Select-String   - Windows without rg/grep (.NET regex)
    4. pure Python (os.walk + re) - last-resort fallback, always works

The external backends (1-3) keep search fast on every platform that ships a
real search tool; the pure-Python tier guarantees the tool still returns
results on a bare Windows box where none of them exist (that was the original
motivation for this tool). Only tier 1 honors .gitignore; the others fall back
to a fixed VCS/dependency directory denylist, and the result carries a notice
when that happens so the model knows the exclusion basis differs.
"""

import fnmatch
import os
import shutil
import subprocess
import sys
import time
from typing import Dict, Any, List, Tuple

import regex as re  # not stdlib re: .search() takes a real per-call timeout, stdlib re has none

from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.utils.truncate import truncate_line
from common.utils import expand_path

DEFAULT_MAX_RESULTS = 50
MAX_RESULTS_CAP = 500
MAX_FILE_BYTES = 2 * 1024 * 1024
SEARCH_TIMEOUT_SECONDS = 30
REGEX_MATCH_TIMEOUT_SECONDS = 1  # caps one regex.search() call in the python backend

_IS_WIN = sys.platform == "win32"

# Matches read.py's issue #2913 fix: /proc/<pid|self|thread-self>/environ
# mirrors any secrets loaded into the process environment from ~/.cow/.env.
_PROC_ENVIRON_RE = re.compile(r"^/proc/(\d+|self|thread-self)/environ$")

# VCS + dependency/build dirs excluded by the non-rg backends (rg uses
# .gitignore instead). Kept in sync with what rg would typically skip via a
# project's .gitignore, so cross-backend results stay comparable.
_SKIP_DIR_NAMES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".next",
    "target", "vendor", ".tox", "coverage", ".idea",
}

class Grep(BaseTool):
    """Tool for searching file contents by pattern across a directory tree."""

    name: str = "grep"
    description: str = (
        "Search file contents for a regex pattern across a directory tree, "
        "returning matching lines with their file path and line number. "
        "Prefer this tool for searching file contents. Supports full regex syntax; "
        "use file_glob to limit which files are searched and output_mode to choose "
        "the result shape."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for in file contents."
            },
            "path": {
                "type": "string",
                "description": "File or directory to search in (default: workspace root). Relative paths are based on the workspace directory."
            },
            "file_glob": {
                "type": "string",
                "description": "Glob to filter which files are searched, e.g. '*.py' or '*.{ts,tsx}' (default: all files)."
            },
            "output_mode": {
                "type": "string",
                "enum": ["content", "files", "count"],
                "description": "content = matching lines with line numbers (default); files = only file paths that contain a match; count = number of matches per file."
            },
            "ignore_case": {
                "type": "boolean",
                "description": "Case-insensitive match (default false)."
            },
            "no_ignore": {
                "type": "boolean",
                "description": "When true, also search files normally ignored via .gitignore. Default false. (Only affects the ripgrep backend; other backends never consult .gitignore.)"
            },
            "max_results": {
                "type": "integer",
                "description": f"Maximum number of results to return (default: {DEFAULT_MAX_RESULTS}, capped at {MAX_RESULTS_CAP})."
            }
        },
        "required": ["pattern"]
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        self.timeout = self.config.get("timeout", SEARCH_TIMEOUT_SECONDS)
        # Resolved once (assumes ~/.cow is stable for this session), not per-check.
        self._cow_dir = os.path.realpath(expand_path("~/.cow")).replace(os.sep, "/")

    # ------------------------------------------------------------------ execute
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """Execute a content search. See params for arguments.

        Returns a ToolResult whose payload shape depends on output_mode:
          content -> {matches: [{file, line, match}], match_count, notice?}
          files   -> {files: [path, ...], match_count, notice?}
          count   -> {counts: [{file, count}], match_count, notice?}
        """
        pattern = args.get("pattern", "")
        if not isinstance(pattern, str) or not pattern:
            return ToolResult.fail("Error: pattern parameter is required")

        path = args.get("path", ".") or "."
        file_glob = args.get("file_glob", "*") or "*"
        if not isinstance(file_glob, str):
            return ToolResult.fail(f"Error: file_glob must be a string, got: {file_glob!r}")

        output_mode = args.get("output_mode", "content") or "content"
        if output_mode not in ("content", "files", "count"):
            return ToolResult.fail(f"Error: output_mode must be content/files/count, got: {output_mode!r}")

        ignore_case = bool(args.get("ignore_case", False))
        no_ignore = bool(args.get("no_ignore", False))

        max_results = args.get("max_results", DEFAULT_MAX_RESULTS)
        if isinstance(max_results, float) and not max_results.is_integer():
            return ToolResult.fail(f"Error: max_results must be an integer, got: {max_results!r}")
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            return ToolResult.fail(f"Error: max_results must be an integer, got: {max_results!r}")
        if max_results <= 0:
            return ToolResult.fail("Error: max_results must be a positive integer")
        max_results = min(max_results, MAX_RESULTS_CAP)

        # Validate regex early so a bad pattern fails the same way on every
        # backend (external tools would otherwise emit their own error text).
        try:
            re.compile(pattern)
        except re.error as e:
            return ToolResult.fail(f"Error: invalid regex pattern: {e}")

        root = self._resolve_path(path)
        if self._is_credential_path(root):
            return ToolResult.fail(
                "Error: Access denied. API keys and credentials must be accessed through the env_config tool only."
            )
        if not os.path.exists(root):
            return ToolResult.fail(
                f"Error: path not found: {path}\nResolved to: {root}\n"
                f"Hint: Relative paths are based on workspace ({self.cwd}). For directories outside workspace, use absolute paths."
            )

        opts = _SearchOptions(
            pattern=pattern, root=root, file_glob=file_glob,
            output_mode=output_mode, ignore_case=ignore_case,
            no_ignore=no_ignore, max_results=max_results, deadline=time.monotonic() + self.timeout,
        )

        backend = self._pick_backend()
        try:
            outcome = backend(opts)
        except Exception as e:
            # Any backend failure falls through to python so the tool never
            # hard-fails just because an external binary misbehaved.
            if backend is not self._backend_python:
                outcome = self._backend_python(opts)
            else:
                return ToolResult.fail(f"Error searching files: {e}")

        return self._format(outcome, opts)

    # ------------------------------------------------------------- backend pick
    def _pick_backend(self):
        """Return the best available backend callable for this machine."""
        if shutil.which("rg"):
            return self._backend_rg
        if not _IS_WIN and shutil.which("grep"):
            return self._backend_grep
        if _IS_WIN and (shutil.which("powershell") or shutil.which("pwsh")):
            return self._backend_powershell
        return self._backend_python

    # ------------------------------------------------------------------ helpers
    def _resolve_path(self, path: str) -> str:
        """Resolve to absolute path (same convention as read/ls/write, no workspace jail)."""
        path = expand_path(path)
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(self.cwd, path))

    def _is_credential_path(self, absolute_path: str) -> bool:
        """Block ~/.cow (like ls.py) and /proc/*/environ (like read.py #2913)."""
        candidates = set()
        try:
            candidates.add(os.path.normpath(absolute_path).replace(os.sep, "/"))
            candidates.add(os.path.realpath(absolute_path).replace(os.sep, "/"))
        except OSError:
            candidates.add(absolute_path.replace(os.sep, "/"))
        for candidate in candidates:
            if _PROC_ENVIRON_RE.match(candidate):
                return True
        return any(c == self._cow_dir or c.startswith(self._cow_dir + "/") for c in candidates)

    def _rel(self, file_path: str, root: str) -> str:
        try:
            base = root if os.path.isdir(root) else os.path.dirname(root)
            return os.path.relpath(file_path, base)
        except ValueError:
            return file_path

    # ------------------------------------------------------------- rg backend
    def _backend_rg(self, opts: "_SearchOptions") -> "_BackendResult":
        cmd = ["rg", "--line-number", "--no-heading", "--with-filename", "--color", "never"]
        # Exclude the same VCS/dependency dirs the other backends hardcode, so a
        # repo WITHOUT a .gitignore still gives identical results across backends
        # (rg alone would otherwise only skip what .gitignore lists). Users who
        # genuinely need these dirs pass no_ignore=true.
        for d in _SKIP_DIR_NAMES:
            cmd += ["--glob", f"!{d}"]
        cmd += ["--max-columns", "1000"]
        if opts.ignore_case:
            cmd.append("-i")
        if opts.no_ignore:
            cmd.append("--no-ignore")
        if opts.file_glob and opts.file_glob != "*":
            cmd += ["--glob", opts.file_glob]
        if opts.output_mode == "files":
            cmd.append("-l")
        elif opts.output_mode == "count":
            cmd.append("-c")
        # `--` guards patterns that begin with a dash.
        cmd += ["-e", opts.pattern, "--", opts.root]
        rows, timed_out = self._run_external(cmd, opts)
        return _BackendResult(rows, timed_out, False, True)

    # ------------------------------------------------------------ grep backend
    def _backend_grep(self, opts: "_SearchOptions") -> "_BackendResult":
        # -H forces filename even for a single-file target; -r recurses; -E = ERE
        # (aligns alternation/quantifier syntax with rg). -n is added only in
        # content mode — mixing it with -c/-l corrupts their output.
        cmd = ["grep", "-rH", "-E"]
        for d in _SKIP_DIR_NAMES:
            cmd.append(f"--exclude-dir={d}")
        if opts.ignore_case:
            cmd.append("-i")
        if opts.file_glob and opts.file_glob != "*":
            cmd.append(f"--include={opts.file_glob}")
        if opts.output_mode == "files":
            cmd.append("-l")
        elif opts.output_mode == "count":
            cmd.append("-c")
        else:
            cmd.append("-n")
        cmd += ["-e", opts.pattern, opts.root]
        rows, timed_out = self._run_external(cmd, opts)
        return _BackendResult(rows, timed_out, False, True)

    # ------------------------------------------------ powershell backend (win)
    def _backend_powershell(self, opts: "_SearchOptions") -> "_BackendResult":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        # Build a Select-String pipeline. -AllMatches keeps it line-oriented;
        # .NET regex handles alternation/unicode that findstr cannot.
        ci = "-CaseSensitive" if not opts.ignore_case else ""
        script = (
            f"$ErrorActionPreference='SilentlyContinue';"
            f"Get-ChildItem -Path '{opts.root}' -Recurse -File "
            f"| Where-Object {{ $_.FullName -notmatch '\\\\({'|'.join(_SKIP_DIR_NAMES)})\\\\' }} "
            f"| Select-String -Pattern @'\n{opts.pattern}\n'@ {ci} "
            f"| ForEach-Object {{ \"$($_.Path):$($_.LineNumber):$($_.Line)\" }}"
        )
        cmd = [shell, "-NoProfile", "-NonInteractive", "-Command", script]
        rows, timed_out = self._run_external(cmd, opts)
        return _BackendResult(rows, timed_out, False, True)

    # ----------------------------------------------- external runner + parser
    def _run_external(self, cmd: List[str], opts: "_SearchOptions") -> Tuple[List[dict], bool]:
        remaining = max(0.1, opts.deadline - time.monotonic())
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=remaining,
            )
        except subprocess.TimeoutExpired:
            return [], True
        # Parse stdout regardless of exit code: rg/grep exit 1 on "no matches"
        # (empty stdout -> empty rows, which is correct). Diagnostic lines that a
        # real error (exit >1) may print to stdout are dropped in _parse_lines.
        stdout = proc.stdout or ""
        rows = self._parse_lines(stdout.splitlines(), opts)
        return rows, False

    def _parse_lines(self, lines: List[str], opts: "_SearchOptions") -> List[dict]:
        """Parse `path:line:content` (content) / `path` (files) / `path:count`
        (count) output shared by rg, grep and the PowerShell shim. Drops the
        backend's own diagnostic lines (rg:/grep: prefixes) so they never reach
        the model."""
        rows: List[dict] = []
        for line in lines:
            if not line or line.startswith(("rg:", "grep:")):
                continue
            if opts.output_mode == "files":
                p = line.strip()
                if p:
                    rows.append({"file": self._rel(p, opts.root)})
                continue
            if opts.output_mode == "count":
                # path:count — split from the right to tolerate ':' in paths.
                # grep -c emits a line for EVERY scanned file including :0, while
                # rg -c only lists files with matches; drop zeros so both align.
                head, sep, tail = line.rpartition(":")
                if sep and tail.isdigit() and int(tail) > 0:
                    rows.append({"file": self._rel(head, opts.root), "count": int(tail)})
                continue
            # content mode: path:line:content
            first = line.find(":")
            second = line.find(":", first + 1)
            if first == -1 or second == -1:
                continue
            file_part = line[:first]
            line_no = line[first + 1:second]
            content = line[second + 1:]
            if not line_no.isdigit():
                continue
            truncated, _ = truncate_line(content)
            rows.append({
                "file": self._rel(file_part, opts.root),
                "line": int(line_no),
                "match": truncated,
            })
        # Deterministic order across backends.
        if opts.output_mode == "content":
            rows.sort(key=lambda r: (r["file"], r["line"]))
        else:
            rows.sort(key=lambda r: r["file"])
        return rows[:opts.max_results]

    # ------------------------------------------------------- python fallback
    def _backend_python(self, opts: "_SearchOptions") -> "_BackendResult":
        flags = re.IGNORECASE if opts.ignore_case else 0
        compiled = re.compile(opts.pattern, flags)
        rows: List[dict] = []
        pattern_timeout = False
        skip_pruned = False
        root = opts.root

        walk_root = root if os.path.isdir(root) else os.path.dirname(root)
        single_file = None if os.path.isdir(root) else os.path.basename(root)

        for dirpath, dirnames, filenames in os.walk(walk_root):
            kept = []
            for d in dirnames:
                if d in _SKIP_DIR_NAMES:
                    skip_pruned = True
                    continue
                if self._is_credential_path(os.path.join(dirpath, d)):
                    continue
                kept.append(d)
            dirnames[:] = sorted(kept)

            for filename in sorted(filenames):
                if single_file and filename != single_file:
                    continue
                if len(rows) >= opts.max_results:
                    return _BackendResult(self._python_finalize(rows, opts), False, pattern_timeout, skip_pruned)
                if time.monotonic() >= opts.deadline:
                    return _BackendResult(self._python_finalize(rows, opts), True, pattern_timeout, skip_pruned)
                if opts.file_glob and opts.file_glob != "*" and not fnmatch.fnmatch(filename, opts.file_glob):
                    continue
                fp = os.path.join(dirpath, filename)
                if self._is_credential_path(fp):
                    continue
                file_rows, hit_deadline, hit_pattern_timeout = self._python_scan_file(fp, compiled, opts)
                rows.extend(file_rows)
                pattern_timeout = pattern_timeout or hit_pattern_timeout
                if hit_deadline:
                    return _BackendResult(self._python_finalize(rows, opts), True, pattern_timeout, skip_pruned)

        return _BackendResult(self._python_finalize(rows, opts), False, pattern_timeout, skip_pruned)

    def _python_scan_file(self, fp: str, compiled, opts: "_SearchOptions") -> Tuple[List[dict], bool, bool]:
        try:
            if os.path.getsize(fp) > MAX_FILE_BYTES:
                return [], False, False
        except OSError:
            return [], False, False
        try:
            with open(fp, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            return [], False, False

        out: List[dict] = []
        count = 0
        for line_no, raw in enumerate(content.split("\n"), start=1):
            line = raw[:-1] if raw.endswith("\r") else raw
            if time.monotonic() >= opts.deadline:
                return out, True, False
            try:
                matched = compiled.search(line, timeout=REGEX_MATCH_TIMEOUT_SECONDS)
            except TimeoutError:
                # Bail on this file's remaining lines but flag it so the caller
                # can warn the model results may be incomplete.
                return out, False, True
            if matched:
                count += 1
                if opts.output_mode == "content":
                    truncated, _ = truncate_line(line)
                    out.append({"file": self._rel(fp, opts.root), "line": line_no, "match": truncated})
                elif opts.output_mode == "files":
                    out.append({"file": self._rel(fp, opts.root)})
                    break
        if opts.output_mode == "count" and count:
            out.append({"file": self._rel(fp, opts.root), "count": count})
        return out, False, False

    @staticmethod
    def _python_finalize(rows: List[dict], opts: "_SearchOptions") -> List[dict]:
        if opts.output_mode == "content":
            rows.sort(key=lambda r: (r["file"], r["line"]))
        else:
            rows.sort(key=lambda r: r["file"])
        return rows[:opts.max_results]

    # ------------------------------------------------------------- formatting
    def _format(self, outcome: "_BackendResult", opts: "_SearchOptions") -> ToolResult:
        rows = outcome.rows
        notices: List[str] = []
        if opts.output_mode == "files":
            payload = {"files": [r["file"] for r in rows], "match_count": len(rows)}
        elif opts.output_mode == "count":
            payload = {"counts": rows, "match_count": sum(r.get("count", 0) for r in rows)}
        else:
            payload = {"matches": rows, "match_count": len(rows)}

        if len(rows) >= opts.max_results:
            if opts.max_results >= MAX_RESULTS_CAP:
                notices.append(f"{opts.max_results} result limit reached (hard maximum). Narrow `path` or `file_glob`.")
            else:
                notices.append(
                    f"{opts.max_results} result limit reached. "
                    f"Use max_results={min(opts.max_results * 2, MAX_RESULTS_CAP)} to see more."
                )
        if outcome.timed_out:
            notices.append(
                f"Search stopped after {self.timeout}s — results may be incomplete. "
                f"Narrow `path` or `file_glob`."
            )
        if outcome.pattern_timeout:
            notices.append(
                f"Pattern took longer than {REGEX_MATCH_TIMEOUT_SECONDS}s on a line in one or more "
                f"files — the rest of that file was not searched. Results may be incomplete. "
                f"Simplify `pattern` to avoid catastrophic backtracking."
            )
        if outcome.skip_pruned:
            notices.append(
                "Directories like .git/node_modules/dist/vendor were excluded by a fixed "
                "denylist (not .gitignore), so match_count omits their contents."
            )
        if notices:
            payload["notice"] = " ".join(notices)
        return ToolResult.success(payload)


class _BackendResult:
    """What a backend returns: rows plus the signals _format turns into notices."""
    __slots__ = ("rows", "timed_out", "pattern_timeout", "skip_pruned")

    def __init__(self, rows, timed_out=False, pattern_timeout=False, skip_pruned=False):
        self.rows = rows
        self.timed_out = timed_out
        self.pattern_timeout = pattern_timeout
        self.skip_pruned = skip_pruned


class _SearchOptions:
    """Plain container for a single search invocation's resolved options."""
    __slots__ = ("pattern", "root", "file_glob", "output_mode",
                 "ignore_case", "no_ignore", "max_results", "deadline")

    def __init__(self, pattern, root, file_glob, output_mode,
                 ignore_case, no_ignore, max_results, deadline):
        self.pattern = pattern
        self.root = root
        self.file_glob = file_glob
        self.output_mode = output_mode
        self.ignore_case = ignore_case
        self.no_ignore = no_ignore
        self.max_results = max_results
        self.deadline = deadline
