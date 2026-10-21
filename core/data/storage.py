"""Core-owned storage inventory and safe local cache cleanup."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from agent.permission.audit import record


def _path_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _category(
    entry_id: str,
    name: dict,
    path: Path,
    *,
    retention: dict,
    actions: list[str],
    detail: dict | None = None,
) -> dict:
    return {
        "id": entry_id,
        "name": name,
        "path": str(path),
        "bytes": _path_bytes(path),
        "exists": path.exists(),
        "retention": retention,
        "actions": list(actions),
        "detail": detail or {},
    }


def inventory() -> dict:
    from common.state_dir import (
        briefing_db,
        memory_index_db,
        runs_dir,
        scheduler_file,
        tmp_dir,
        data_service_db,
    )
    from config import conf

    max_age = conf().get("conversation_max_age_days")
    retention_sessions = {
        "zh": f"超过 {max_age} 天未更新的非 Web 会话可能被自动清理。"
        if max_age
        else "按会话使用情况保留。",
        "en": (
            f"Non-web sessions unused for {max_age} days may be pruned."
            if max_age
            else "Kept according to session activity."
        ),
    }
    categories = [
        _category(
            "data_service",
            {"zh": "来源数据与同步状态", "en": "Source records and sync state"},
            data_service_db(ensure=False),
            retention={
                "zh": "按信息源的引用、缓存或持久化策略保留。",
                "en": "Kept according to each source storage policy.",
            },
            actions=[],
        ),
        _category(
            "conversations",
            {"zh": "对话记录", "en": "Conversations"},
            memory_index_db(ensure=False),
            retention=retention_sessions,
            actions=[],
            detail={"manage_in": "sessions"},
        ),
        _category(
            "scheduler",
            {"zh": "定时任务与执行记录", "en": "Scheduled tasks and run logs"},
            scheduler_file().parent
            if scheduler_file().parent.exists()
            else scheduler_file(),
            retention={
                "zh": "任务配置长期保留；执行输出在 runs 目录。",
                "en": "Task definitions are kept; run output lives under runs.",
            },
            actions=[],
        ),
        _category(
            "briefing",
            {"zh": "简报数据", "en": "Briefing data"},
            briefing_db(ensure=False),
            retention={
                "zh": "简报历史保存在本地数据库。",
                "en": "Briefing history is stored in a local database.",
            },
            actions=[],
        ),
        _category(
            "temporary",
            {"zh": "临时文件", "en": "Temporary files"},
            tmp_dir(ensure=False),
            retention={
                "zh": "临时下载与合成文件，可安全清理。",
                "en": "Transient downloads and synthesized media; safe to clear.",
            },
            actions=["clear_temporary"],
        ),
        _category(
            "runs",
            {"zh": "任务运行缓存", "en": "Task run cache"},
            runs_dir(ensure=False),
            retention={
                "zh": "定时任务执行痕迹与输出缓存。",
                "en": "Scheduled-task execution traces and output cache.",
            },
            actions=["clear_runs"],
        ),
    ]
    return {"available": True, "categories": categories}


def cleanup(action: str) -> dict:
    action = str(action or "").strip()
    if action not in {"clear_temporary", "clear_runs"}:
        raise ValueError("unsupported storage cleanup action")
    from agent.permission.data_access import authorize

    authorize("delete", "storage:" + action)
    if action == "clear_temporary":
        from common.state_dir import tmp_dir

        root = tmp_dir(ensure=True)
        removed = _clear_directory(root)
        record(
            operation="cleanup",
            resource="temporary files",
            decision="policy_change",
            reason=f"Cleared {removed} temporary path(s).",
        )
        return {"status": "success", "removed": removed}
    if action == "clear_runs":
        from common.state_dir import runs_dir

        root = runs_dir(ensure=False)
        removed = _clear_directory(root) if root.exists() else 0
        record(
            operation="cleanup",
            resource="task run cache",
            decision="policy_change",
            reason=f"Cleared {removed} run cache path(s).",
        )
        return {"status": "success", "removed": removed}
    raise ValueError("unsupported privacy cleanup action")


def _clear_directory(root: Path) -> int:
    if root.is_symlink():
        raise ValueError("Refusing a symlink cache root")
    if not root.exists():
        return 0
    removed = 0
    for child in list(root.iterdir()):
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed
