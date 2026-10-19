"""AutomationStore must not fall back to in-process SchedulerMutations."""
from __future__ import annotations

import pytest

from application import Application


def test_automation_store_requires_plugin(tmp_path, monkeypatch):
    from agent.scheduler.automation_store import AutomationStore

    monkeypatch.setenv("STELLA_AUTOMATION_PLUGIN", "0")
    legacy = tmp_path / "tasks.json"
    legacy.write_text("{}", encoding="utf-8")
    store = AutomationStore(str(legacy), "agent-1")
    with pytest.raises(RuntimeError, match="stella.automation"):
        Application.scheduler(store)


def test_json_task_store_still_uses_host_mutations(tmp_path, monkeypatch):
    from agent.scheduler.store import TaskStore

    monkeypatch.setenv("STELLA_AUTOMATION_PLUGIN", "0")
    store = TaskStore(str(tmp_path / "tasks.json"))
    svc = Application.scheduler(store)
    assert type(svc).__name__ == "SchedulerMutations"
