import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.registry import AgentProfile, AgentRegistry, set_agent_registry
from common import state_dir
from common.runtime_identity import (
    EMPTY_IDENTITY,
    RuntimeIdentity,
    current_agent_id,
    current_identity,
    identity_scope,
    submit,
    use_identity,
    wrap,
)


@pytest.fixture
def registry(tmp_path):
    reg = AgentRegistry(
        [
            AgentProfile(id="alpha", name="Alpha", workspace=str(tmp_path / "alpha")),
            AgentProfile(id="beta", name="Beta", workspace=str(tmp_path / "beta")),
        ],
        "alpha",
    )
    set_agent_registry(reg)
    yield reg
    set_agent_registry(None)


def test_absent_identity_resolves_to_default_agent(registry, tmp_path):
    assert state_dir.state_root() == tmp_path / "alpha"


def test_identity_selects_the_agent_workspace(registry, tmp_path):
    with identity_scope(agent_id="beta"):
        assert state_dir.state_root() == tmp_path / "beta"
        assert state_dir.skills_dir() == tmp_path / "beta" / "skills"
    assert state_dir.state_root() == tmp_path / "alpha"


def test_unknown_agent_raises_instead_of_falling_back(registry):
    with identity_scope(agent_id="ghost"):
        with pytest.raises(state_dir.StateDirError, match="unknown agent id"):
            state_dir.state_root()


def test_user_scoped_paths_collapse_onto_the_root_without_a_user(registry, tmp_path):
    with identity_scope(agent_id="alpha"):
        assert state_dir.memory_dir() == tmp_path / "alpha" / "memory"
        assert state_dir.runs_dir() == tmp_path / "alpha" / "runs"


def test_user_scoped_paths_split_once_a_user_is_present(registry, tmp_path):
    with identity_scope(agent_id="alpha", user_id="u1"):
        assert state_dir.memory_dir() == tmp_path / "alpha" / "users" / "u1" / "memory"
        assert state_dir.runs_dir() == tmp_path / "alpha" / "users" / "u1" / "runs"
        # agent assets stay shared across users
        assert state_dir.skills_dir() == tmp_path / "alpha" / "skills"
        assert state_dir.mcp_config_file() == tmp_path / "alpha" / "mcp.json"


def test_legacy_config_keeps_the_configured_workspace(tmp_path):
    set_agent_registry(AgentRegistry.from_config({"agent_workspace": str(tmp_path / "cow")}))
    try:
        assert state_dir.state_root() == (tmp_path / "cow").resolve()
    finally:
        set_agent_registry(None)


def test_ensure_creates_directories_only_when_asked(registry, tmp_path):
    with identity_scope(agent_id="alpha"):
        assert not state_dir.knowledge_dir().exists()
        state_dir.knowledge_dir(ensure=True)
        assert (tmp_path / "alpha" / "knowledge").is_dir()


def test_scope_derives_from_the_ambient_identity():
    with use_identity(RuntimeIdentity(agent_id="a", user_id="u", session_id="s")):
        with identity_scope(run_id="r1"):
            ident = current_identity()
            assert (ident.agent_id, ident.user_id, ident.session_id) == ("a", "u", "s")
            assert ident.run_id == "r1"
        assert current_identity().run_id is None


def test_unknown_identity_field_is_rejected():
    with pytest.raises(TypeError, match="unknown identity fields"):
        with identity_scope(agnet_id="typo"):
            pass


def test_identity_does_not_leak_across_plain_threads():
    seen = []
    with use_identity(RuntimeIdentity(agent_id="alpha")):
        thread = threading.Thread(target=lambda: seen.append(current_agent_id()))
        thread.start()
        thread.join()
    assert seen == [None]


def test_submit_carries_identity_into_the_pool():
    with ThreadPoolExecutor(max_workers=1) as pool:
        with use_identity(RuntimeIdentity(agent_id="alpha", user_id="u1")):
            future = submit(pool, lambda: current_identity())
        ident = future.result()
    assert (ident.agent_id, ident.user_id) == ("alpha", "u1")


def test_wrap_carries_identity_into_a_thread():
    seen = []
    with use_identity(RuntimeIdentity(agent_id="beta")):
        target = wrap(lambda: seen.append(current_agent_id()))
    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    assert seen == ["beta"]


def test_ambient_identity_is_empty_by_default():
    assert current_identity() == EMPTY_IDENTITY
    assert current_agent_id() is None


def test_consumers_follow_the_routed_agent(registry, tmp_path):
    """The point of the whole exercise: leaf code that never heard of an
    agent id still lands in the right workspace."""
    from agent.memory.config import MemoryConfig
    from agent.protocol.artifact import get_workspace_root
    from common.tmp_dir import TmpDir

    with identity_scope(agent_id="beta"):
        assert TmpDir().path().startswith(str(tmp_path / "beta"))
        assert get_workspace_root() == os.path.realpath(str(tmp_path / "beta"))
        assert MemoryConfig().workspace_root == str(tmp_path / "beta")


def test_base_override_reuses_the_layout_without_an_identity(tmp_path):
    assert state_dir.memory_dir(base=tmp_path / "ws") == tmp_path / "ws" / "memory"
    assert state_dir.skills_dir(base=tmp_path / "ws") == tmp_path / "ws" / "skills"
