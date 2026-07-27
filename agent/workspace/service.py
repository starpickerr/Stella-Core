"""
Workspace file service - browse and search the agent workspace.

Backs the file manager tab and the `@` file reference picker in the web UI.
Read-only: it never mutates the workspace.
"""

import os
import time
from typing import Dict, List, Optional

from agent.protocol.artifact import classify_kind, is_previewable

# Directories that are large, noisy, or purely internal. Still listable when the
# user explicitly navigates into them, but skipped by recursive search.
SEARCH_SKIP_DIRS = {"tmp", "node_modules", "__pycache__", "venv", ".git", ".venv"}

# Agent bookkeeping. Reachable by search, but ranked below user-facing files so
# they don't crowd out real results in the `@` picker.
SEARCH_DEMOTE_DIRS = {"memory", "skills", "knowledge", "scheduler", "plans"}
SEARCH_DEMOTE_PENALTY = 25

MAX_ENTRIES = 500
MAX_SEARCH_WALK = 20000


class WorkspaceService:
    def __init__(self, workspace_root: str):
        self.root = os.path.realpath(os.path.expanduser(workspace_root))

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------
    def resolve(self, rel_path: str) -> str:
        """Resolve a workspace-relative path, rejecting anything that escapes."""
        rel_path = (rel_path or "").replace("\\", "/").strip("/")
        full = os.path.realpath(os.path.join(self.root, rel_path))
        if full != self.root and os.path.commonpath([full, self.root]) != self.root:
            raise ValueError(f"Path escapes the workspace: {rel_path}")
        return full

    def to_rel(self, abs_path: str) -> str:
        try:
            rel = os.path.relpath(abs_path, self.root)
        except ValueError:
            return abs_path
        return "" if rel == "." else rel.replace(os.sep, "/")

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------
    def list_dir(self, rel_path: str = "", show_hidden: bool = False) -> Dict:
        """List one directory level, directories first then files by mtime desc."""
        full = self.resolve(rel_path)
        if not os.path.isdir(full):
            raise FileNotFoundError(f"Not a directory: {rel_path}")

        dirs: List[Dict] = []
        files: List[Dict] = []
        truncated = False
        try:
            with os.scandir(full) as it:
                for entry in it:
                    if not show_hidden and entry.name.startswith("."):
                        continue
                    if len(dirs) + len(files) >= MAX_ENTRIES:
                        truncated = True
                        break
                    item = self._describe(entry)
                    if item is None:
                        continue
                    (dirs if item["is_dir"] else files).append(item)
        except PermissionError:
            raise ValueError(f"Permission denied: {rel_path}")

        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["mtime"], reverse=True)

        return {
            "path": self.to_rel(full),
            "root": self.root,
            "entries": dirs + files,
            "truncated": truncated,
        }

    def _describe(self, entry) -> Optional[Dict]:
        try:
            stat = entry.stat(follow_symlinks=False)
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            return None
        kind = "directory" if is_dir else classify_kind(entry.name)
        return {
            "name": entry.name,
            "path": self.to_rel(entry.path),
            "is_dir": is_dir,
            "kind": kind,
            "previewable": (not is_dir) and is_previewable(kind),
            "size": 0 if is_dir else stat.st_size,
            "mtime": stat.st_mtime,
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 30) -> Dict:
        """
        Subsequence match on the workspace-relative path, scored so that
        prefix matches on the entry name rank highest.

        Directories are included so a whole folder can be referenced (e.g. `@`
        a project dir); a matching folder naturally outranks the files inside it
        because those only match on the path, not the name.
        """
        query = (query or "").strip().lower()
        results: List[Dict] = []
        walked = 0

        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in SEARCH_SKIP_DIRS
            ]
            for name in dirnames + filenames:
                is_dir = name in dirnames
                if name.startswith("."):
                    continue
                walked += 1
                if walked > MAX_SEARCH_WALK:
                    break
                entry = self._match(query, os.path.join(dirpath, name), name, is_dir)
                if entry:
                    results.append(entry)
            if walked > MAX_SEARCH_WALK:
                break

        results.sort(key=lambda x: (-x["_score"], -x["mtime"]))
        for r in results:
            r.pop("_score", None)
        return {"query": query, "results": results[:limit]}

    def _match(self, query: str, full: str, name: str, is_dir: bool) -> Optional[Dict]:
        """Score one entry against the query. None means it doesn't match."""
        rel = self.to_rel(full)
        score = self._score(query, name.lower(), rel.lower())
        if score < 0:
            return None

        parts = rel.split("/")
        # For a directory its own name counts, so `memory/` ranks low itself.
        if SEARCH_DEMOTE_DIRS.intersection(parts if is_dir else parts[:-1]):
            score -= SEARCH_DEMOTE_PENALTY

        kind = "directory" if is_dir else classify_kind(name)
        if kind == "file":
            # Unrecognized extension (or none at all): rarely what someone
            # means to reference, so keep it below real documents.
            score -= SEARCH_DEMOTE_PENALTY

        try:
            stat = os.stat(full)
        except OSError:
            return None

        return {
            "name": name,
            "path": rel,
            "is_dir": is_dir,
            "kind": kind,
            "previewable": (not is_dir) and is_previewable(kind),
            "size": 0 if is_dir else stat.st_size,
            "mtime": stat.st_mtime,
            "_score": score,
        }

    @staticmethod
    def _score(query: str, name: str, rel: str) -> int:
        """Higher is better; -1 means no match."""
        if not query:
            return 0
        if name.startswith(query):
            return 100
        if query in name:
            return 80
        if query in rel:
            return 60
        # Subsequence fallback so "idxhtml" finds "index.html".
        pos = 0
        for ch in query:
            pos = name.find(ch, pos)
            if pos < 0:
                return -1
            pos += 1
        return 30

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------
    def meta(self) -> Dict:
        return {
            "root": self.root,
            "exists": os.path.isdir(self.root),
            "server_time": time.time(),
        }

    def stat_file(self, rel_path: str) -> Dict:
        """
        Metadata for one entry, used when opening something by path.

        Directories resolve too: callers that reference a folder (drag, `@`)
        need to learn it's a folder rather than get an error.
        """
        full = self.resolve(rel_path)
        is_dir = os.path.isdir(full)
        if not is_dir and not os.path.isfile(full):
            raise FileNotFoundError(f"File not found: {rel_path}")
        stat = os.stat(full)
        kind = "directory" if is_dir else classify_kind(full)
        return {
            "name": os.path.basename(full) or self.to_rel(full),
            "path": self.to_rel(full),
            "abs_path": full,
            "is_dir": is_dir,
            "kind": kind,
            "previewable": (not is_dir) and is_previewable(kind),
            "size": 0 if is_dir else stat.st_size,
            "mtime": stat.st_mtime,
        }
