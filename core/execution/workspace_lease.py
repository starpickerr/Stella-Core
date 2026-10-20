"""Per-attempt managed work copy. Git uses worktree when possible; else output dir."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Any

from core.execution.paths import managed_child


def allocate_workspace_lease(
    *,
    work_root: Path,
    execution_id: str,
    attempt_id: str,
    source_project: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(work_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lease_id = f"wlease-{uuid.uuid4().hex[:12]}"
    dest = managed_child(root, execution_id, attempt_id)
    dest.mkdir(parents=True, exist_ok=True)
    kind = "output_dir"
    if source_project:
        src = Path(source_project).resolve()
        if (src / ".git").exists() or (src / ".git").is_file():
            try:
                subprocess.run(
                    ["git", "worktree", "add", "--detach", str(dest / "tree"), "HEAD"],
                    cwd=str(src),
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                dest = (dest / "tree").resolve()
                kind = "git_worktree"
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                kind = "output_dir"
    lease_ref = f"workspace:{lease_id}"
    root_s = str(root)

    def assert_inside(path: str | Path) -> Path:
        target = Path(path).resolve()
        try:
            target.relative_to(dest)
        except ValueError as exc:
            raise PermissionError(f"path escapes workspace lease: {target}") from exc
        if not str(target).startswith(root_s):
            raise PermissionError(f"path escapes work root: {target}")
        return target

    return {
        "workspaceLeaseRef": lease_ref,
        "path": str(dest),
        "kind": kind,
        "executionId": execution_id,
        "attemptId": attempt_id,
        "assert_inside": assert_inside,
    }
