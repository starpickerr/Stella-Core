"""Force a skill to be in context before a bound tool call runs."""

import os
import re
from typing import List, Optional

from agent.skills.types import Skill, ToolBinding


def skill_marker(name: str) -> str:
    return f"[[stella-skill:{name}]]"


def pending_skill_result(skill_manager, tool_name: str, arguments: dict, messages) -> Optional[str]:
    """Skill text that must be returned instead of running the tool.

    None means every matching skill is already in the conversation, or no
    enabled skill binds this call, so the tool may run.
    """
    unread = [
        skill for skill in _matching_skills(skill_manager, tool_name, arguments)
        if not skill_already_loaded(messages, skill)
    ]
    if not unread:
        return None
    parts = [
        "本次调用尚未执行。先遵循下列技能，再按技能中的参数重新调用该工具。"
        "不要把这段文字当成该工具已经完成。",
    ]
    for skill in unread:
        parts.append(f"{skill_marker(skill.name)}\n\n{skill.content}")
    return "\n\n".join(parts)


def skill_already_loaded(messages, skill: Skill) -> bool:
    """True once this conversation already contains the skill body.

    A tool_use that has not yet received its tool_result does not count: the
    model has not seen the skill until that result is in the history.
    """
    marker = skill_marker(skill.name)
    probe = _body_probe(skill.content)
    path = os.path.normcase(os.path.normpath(skill.file_path))
    read_ids = set()
    for block in _content_blocks(messages):
        kind = block.get("type")
        if kind == "tool_result":
            content = block.get("content")
            if isinstance(content, str) and marker in content:
                return True
            continue
        if kind != "tool_use" or block.get("name") != "read" or not probe:
            continue
        raw = _read_path(block.get("input"))
        if raw and os.path.normcase(os.path.normpath(raw)) == path:
            read_ids.add(block.get("id"))
    if not read_ids or not probe:
        return False
    for block in _content_blocks(messages):
        if block.get("type") != "tool_result" or block.get("tool_use_id") not in read_ids:
            continue
        content = block.get("content")
        if isinstance(content, str) and probe in content:
            return True
    return False


def _matching_skills(skill_manager, tool_name: str, arguments: dict) -> List[Skill]:
    if skill_manager is None:
        return []
    arguments = arguments if isinstance(arguments, dict) else {}
    matched = []
    for entry in skill_manager.filter_skills():
        metadata = entry.metadata
        if metadata is None:
            continue
        if any(_binding_matches(binding, tool_name, arguments) for binding in metadata.tool_bindings):
            matched.append(entry.skill)
    matched.sort(key=lambda skill: skill.name)
    return matched


def _binding_matches(binding: ToolBinding, tool_name: str, arguments: dict) -> bool:
    if binding.tool != tool_name:
        return False
    if binding.actions is None:
        return True
    action = arguments.get("action")
    return isinstance(action, str) and action in binding.actions


def _body_probe(content: str) -> str:
    match = re.match(r"^---\s*\n.*?\n---\s*\n", content or "", re.DOTALL)
    body = content[match.end():] if match else (content or "")
    return body.strip()[:80]


def _read_path(raw) -> str:
    if not isinstance(raw, dict):
        return ""
    path = raw.get("path") or raw.get("location") or ""
    return path if isinstance(path, str) else ""


def _content_blocks(messages):
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            yield {"type": "tool_result", "content": content}
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict):
                yield block
