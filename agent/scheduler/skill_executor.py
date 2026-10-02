"""Resolve and execute a scheduled skill under the normal Agent tool gate."""

from __future__ import annotations

import json


class SkillExecutor:
    def __init__(self, agent_bridge):
        self.agent_bridge = agent_bridge

    def execute(self, skill_name, params, context, agent_id=None):
        if not isinstance(skill_name, str) or not skill_name.strip():
            raise ValueError("skill_name is required")
        if not isinstance(params, dict):
            raise ValueError("skill_params must be an object")
        name = skill_name.strip()
        agent = self.agent_bridge.get_agent(context.get("session_id"), agent_id)
        manager = getattr(agent, "skill_manager", None)
        entry = manager.get_skill(name) if manager else None
        if not entry or not manager.is_skill_enabled(name):
            raise ValueError(f"skill is unavailable: {name}")
        if entry not in manager.filter_skills([name]):
            raise ValueError(f"skill requirements are not met: {name}")
        if entry.skill.disable_model_invocation:
            raise ValueError(f"skill cannot be invoked by a scheduled model run: {name}")

        # Skill instructions are resolved before the model call. The Agent's
        # existing tool loop still invokes ToolInvocation for every tool call.
        prompt = (
            "这是一个已到执行时刻的定时技能任务。请按下方已启用技能的说明执行，"
            "完成后返回结果；不要仅描述计划。\n\n"
            f"技能：{name}\n"
            f"参数：{json.dumps(params, ensure_ascii=False, sort_keys=True)}\n\n"
            f"--- 技能说明开始 ---\n{entry.skill.content}\n--- 技能说明结束 ---"
        )
        return self.agent_bridge.agent_reply(
            prompt, context=context, on_event=None, clear_history=False)
