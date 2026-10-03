"""Explicit workspace and conversation routing for new desktop tasks."""
from __future__ import annotations

import os
import re
import uuid
import hashlib
import json

from agent.workspace import project_store

_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _scope_token(action):
    parts = (action.get("conversation_mode"), action.get("source_session_id") or "",
             action.get("conversation_space") or "", action.get("execution_project_dir") or "")
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:16]


def _known_project(path):
    real = os.path.realpath(path)
    return next((item for item in project_store.list_known_projects()
                 if os.path.realpath(item["path"]) == real), None)


def validate_conversation_action(action, *, allow_pending_source=False):
    """Require an explicit conversation choice for desktop tasks."""
    action = dict(action)
    if "conversation_mode" not in action:
        if action.get("channel_type") == "web":
            raise ValueError("Choose a conversation mode for this desktop task")
        return action
    if action.get("channel_type") != "web":
        raise ValueError("Conversation choices require desktop delivery")
    mode = action.get("conversation_mode")
    space = action.get("conversation_space")
    if mode not in ("source", "reuse", "new"):
        raise ValueError("Invalid task conversation choice")
    if mode == "source":
        session_id = action.get("source_session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("Choose a conversation for this task")
        from agent.memory import get_conversation_store
        from agent.registry import get_agent_registry
        from common.runtime_identity import current_identity
        profile = get_agent_registry().get(current_identity().agent_id)
        store = get_conversation_store(profile.workspace)
        if not allow_pending_source and session_id not in store.list_session_ids(channel_type="web"):
            raise ValueError("The bound conversation is no longer available")
        current_project = project_store.get_project_dir(session_id, current_identity().agent_id) or ""
        frozen_project = action.get("execution_project_dir") or ""
        if frozen_project and os.path.realpath(frozen_project) != os.path.realpath(current_project):
            raise ValueError("The bound conversation changed projects; choose its scope again")
        if action.get("conversation_space") and action["conversation_space"] != ("project" if current_project else "personal"):
            raise ValueError("The bound conversation changed projects; choose its scope again")
        action["conversation_space"] = "project" if current_project else "personal"
        action["execution_project_dir"] = current_project
        return action
    if space not in ("personal", "project"):
        raise ValueError("Invalid task conversation space")
    path = action.get("execution_project_dir") or ""
    if space == "personal":
        if path:
            raise ValueError("Personal tasks cannot have a project folder")
        action["execution_project_dir"] = ""
    else:
        if not isinstance(path, str) or not os.path.isabs(path):
            raise ValueError("Choose an existing project for this task")
        project = _known_project(path)
        if not project:
            raise ValueError("The selected project is no longer available")
        action["execution_project_dir"] = project["path"]
    return action


def prepare_run(task, agent_id=None):
    """Resolve one run's execution and output conversation before any tool runs."""
    action = validate_conversation_action(task.get("action") or {})
    if "conversation_mode" not in action:
        return task
    task_id = str(task.get("id") or "")
    if not _ID.fullmatch(task_id):
        raise ValueError("Invalid task ID")
    if action["conversation_mode"] == "source":
        session_id = action["source_session_id"]
    elif action["conversation_mode"] == "reuse":
        session_id = f"task_{task_id}_{_scope_token(action)}"
    else:
        occurrence = str(task.get("job_run_id") or uuid.uuid4().hex)
        if not _ID.fullmatch(occurrence):
            raise ValueError("Invalid task run ID")
        session_id = f"task_{task_id}_{occurrence}"
    if action["conversation_mode"] == "source":
        pass  # The existing conversation owns its project binding.
    elif action["conversation_space"] == "project":
        # Recheck project membership on every run. A deleted project cannot
        # silently turn a scheduled write into a personal-workspace write.
        project_store.set_project_dir(session_id, action["execution_project_dir"], agent_id)
    else:
        project_store.set_project_dir(session_id, None, agent_id)
    action.update(receiver=session_id, notify_session_id=session_id, execution_session_id=session_id)
    return {**task, "action": action}


def agent_session_id(task):
    """The Agent transcript is separate from the visible task conversation."""
    action = task.get("action") or {}
    base = f"scheduler_{task['id']}"
    if action.get("conversation_mode") == "new":
        return base + "_" + str(task.get("job_run_id") or uuid.uuid4().hex)
    if action.get("conversation_mode") in ("source", "reuse"):
        return base + "_" + _scope_token(action)
    return base


def source_context(action, agent_id=None):
    """Recent visible text from a bound chat for an isolated scheduled Agent run."""
    if action.get("conversation_mode") != "source":
        return ""
    from agent.memory import get_conversation_store
    from agent.registry import get_agent_registry
    store = get_conversation_store(get_agent_registry().get(agent_id).workspace)
    lines = []
    for message in store.load_messages(action["source_session_id"], max_turns=8):
        if message.get("role") not in ("user", "assistant"):
            continue
        content = message.get("content")
        if isinstance(content, str):
            value = content
        elif isinstance(content, list):
            value = "\n".join(block.get("text", "") for block in content
                              if isinstance(block, dict) and block.get("type") == "text")
        else:
            continue
        if value.strip():
            lines.append(f"{message['role']}: {value.strip()}")
    result = "\n".join(lines)
    return result[-12000:]
