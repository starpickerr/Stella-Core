# encoding:utf-8
"""Keep the suite out of the developer's real workspace.

Whatever a test loads config for, ``agent_workspace`` ends up pointing at the
directory the person running the suite actually uses, and anything that resolves
a path without pinning one down writes there: the memory files, the scheduler
store and the tmp directory are all reachable that way.

Only that one key is redirected, and only for the session. Loading the config
outright would be worse than the problem: tests would inherit the developer's
model, language and channel settings, and start passing or failing on them.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True, scope="session")
def workspace_out_of_the_way():
    import config as config_module

    with tempfile.TemporaryDirectory(prefix="stella-tests-") as tmp:
        workspace = os.path.join(tmp, "stella")
        real_load = config_module.load_config

        def load_then_redirect():
            real_load()
            config_module.conf()["agent_workspace"] = workspace

        # Applied now for tests that never load, and re-applied after any that
        # do, since loading replaces the value with the real one.
        config_module.conf()["agent_workspace"] = workspace
        config_module.load_config = load_then_redirect

        # Collection imports every test module before this runs, and a module
        # that loads config on import can leave a registry or a store already
        # resolved against the real path. Drop those.
        _forget_resolved_paths()
        # Standalone tool tests bypass Agent startup, which creates Work.
        from common.state_dir import personal_work_dir
        personal_work_dir(base=workspace)
        try:
            yield workspace
        finally:
            config_module.load_config = real_load


def _forget_resolved_paths():
    from agent.memory import clear_conversation_store_cache
    from agent.memory.config import reset_memory_configs
    from agent.registry import set_agent_registry

    set_agent_registry(None)
    reset_memory_configs()
    clear_conversation_store_cache()


@pytest.fixture(autouse=True)
def security_audit_path(monkeypatch):
    """Keep policy checks out of the real Security Center and remove them after each test."""
    with tempfile.TemporaryDirectory(prefix="stella-security-test-") as directory:
        path = Path(directory) / "security-activity.jsonl"
        monkeypatch.setattr("agent.permission.audit._path", lambda: path)
        yield path


@pytest.fixture
def deterministic_briefing_generator(monkeypatch):
    """Run the production generator with scripted tool calls, never a provider."""
    from agent.briefing.generator import AgentBriefingGenerator
    from briefing_fakes import DeterministicBriefingModel

    def generator(**kwargs):
        return AgentBriefingGenerator(**{**kwargs, "model": DeterministicBriefingModel()})

    monkeypatch.setattr("agent.briefing.pipeline.AgentBriefingGenerator", generator)
    return generator
