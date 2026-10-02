from types import SimpleNamespace

import pytest

from agent.scheduler.skill_executor import SkillExecutor
from agent.skills.types import Skill, SkillEntry


def _entry(disable=False):
    return SkillEntry(Skill(
        name="daily-review", description="Review work", file_path="/tmp/SKILL.md",
        base_dir="/tmp", source="custom", content="Read the latest tasks and summarize them.",
        disable_model_invocation=disable))


class _Manager:
    def __init__(self, entry, enabled=True):
        self.entry = entry
        self.enabled = enabled

    def get_skill(self, name):
        return self.entry if name == "daily-review" else None

    def is_skill_enabled(self, name):
        return self.enabled

    def filter_skills(self, names):
        return [self.entry] if self.enabled else []


class _Bridge:
    def __init__(self, manager):
        self.agent = SimpleNamespace(skill_manager=manager)
        self.calls = []

    def get_agent(self, session_id, agent_id):
        assert (session_id, agent_id) == ("scheduler-session", "default")
        return self.agent

    def agent_reply(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return SimpleNamespace(content="done")


def test_scheduled_skill_resolves_enabled_instructions_and_parameters():
    bridge = _Bridge(_Manager(_entry()))
    context = {"session_id": "scheduler-session"}
    reply = SkillExecutor(bridge).execute(
        "daily-review", {"date": "2026-10-02"}, context, "default")
    assert reply.content == "done"
    assert "Read the latest tasks" in bridge.calls[0][0]
    assert '"date": "2026-10-02"' in bridge.calls[0][0]
    assert bridge.calls[0][1]["context"] is context


@pytest.mark.parametrize("manager,name,params", [
    (_Manager(_entry(), enabled=False), "daily-review", {}),
    (_Manager(_entry()), "missing", {}),
    (_Manager(_entry(disable=True)), "daily-review", {}),
    (_Manager(_entry()), "daily-review", []),
])
def test_scheduled_skill_rejects_unavailable_or_invalid_requests(manager, name, params):
    bridge = _Bridge(manager)
    with pytest.raises(ValueError):
        SkillExecutor(bridge).execute(name, params, {"session_id": "scheduler-session"}, "default")
    assert bridge.calls == []
