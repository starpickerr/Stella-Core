"""Local data inventory and safe cleanup for the Security Center."""

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


def _category(entry_id: str, name: dict, path: Path, *, retention: dict, actions: list[str],
              detail: dict | None = None) -> dict:
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
    from common.state_dir import (briefing_db, memory_index_db, runs_dir, scheduler_file, tmp_dir)
    from agent.permission.audit import _path as audit_path
    from config import conf

    max_age = conf().get("conversation_max_age_days")
    retention_sessions = {
        "zh": f"超过 {max_age} 天未更新的非 Web 会话可能被自动清理。" if max_age else "按会话使用情况保留。",
        "en": (
            f"Non-web sessions unused for {max_age} days may be pruned."
            if max_age else "Kept according to session activity."
        ),
    }
    categories = [
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
            scheduler_file().parent if scheduler_file().parent.exists() else scheduler_file(),
            retention={"zh": "任务配置长期保留；执行输出在 runs 目录。",
                       "en": "Task definitions are kept; run output lives under runs."},
            actions=[],
        ),
        _category(
            "briefing",
            {"zh": "简报数据", "en": "Briefing data"},
            briefing_db(ensure=False),
            retention={"zh": "简报历史保存在本地数据库。", "en": "Briefing history is stored in a local database."},
            actions=[],
        ),
        _category(
            "security_activity",
            {"zh": "安全活动", "en": "Security activity"},
            audit_path(),
            retention={"zh": "保留最近写入的活动记录文件。", "en": "Kept in the recent activity log file."},
            actions=["clear_security_activity"],
        ),
        _category(
            "temporary",
            {"zh": "临时文件", "en": "Temporary files"},
            tmp_dir(ensure=False),
            retention={"zh": "临时下载与合成文件，可安全清理。",
                       "en": "Transient downloads and synthesized media; safe to clear."},
            actions=["clear_temporary"],
        ),
        _category(
            "runs",
            {"zh": "任务运行缓存", "en": "Task run cache"},
            runs_dir(ensure=False),
            retention={"zh": "定时任务执行痕迹与输出缓存。", "en": "Scheduled-task execution traces and output cache."},
            actions=["clear_runs"],
        ),
    ]
    from agent.permission.center import connections
    transfers = []
    for row in connections():
        if not row.get("configured"):
            continue
        transfers.append({
            "id": row["id"],
            "name": row["name"],
            "available": bool(row.get("available", row.get("connected"))),
            "note": {
                "zh": "仅在使用相关功能时，可能向该服务发送授权范围内的请求数据。",
                "en": "When you use this feature, authorized request data may be sent to this service.",
            },
        })
    transfers.insert(0, {
        "id": "model_api",
        "name": "AI Model API",
        "available": True,
        "note": {
            "zh": "对话内容、必要的工具结果与上下文可能发送给当前配置的模型服务。",
            "en": "Chat content, necessary tool results, and context may be sent to the configured model provider.",
        },
    })
    return {"available": True, "categories": categories, "external_transfers": transfers}


def cleanup(action: str) -> dict:
    action = str(action or "").strip()
    if action == "clear_temporary":
        from common.state_dir import tmp_dir
        root = tmp_dir(ensure=True)
        removed = _clear_directory(root)
        record(operation="cleanup", resource="temporary files", decision="policy_change",
               reason=f"Cleared {removed} temporary path(s).")
        return {"status": "success", "removed": removed}
    if action == "clear_security_activity":
        from agent.permission.audit import _path as audit_path
        path = audit_path()
        if path.exists():
            path.write_text("", encoding="utf-8")
        record(operation="cleanup", resource="security activity", decision="policy_change",
               reason="Cleared security activity log.")
        return {"status": "success", "removed": 1 if path.exists() else 0}
    if action == "clear_runs":
        from common.state_dir import runs_dir
        root = runs_dir(ensure=False)
        removed = _clear_directory(root) if root.exists() else 0
        record(operation="cleanup", resource="task run cache", decision="policy_change",
               reason=f"Cleared {removed} run cache path(s).")
        return {"status": "success", "removed": removed}
    raise ValueError("unsupported privacy cleanup action")


def _clear_directory(root: Path) -> int:
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
