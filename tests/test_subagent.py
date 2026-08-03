"""Sub agents: templates, guards, isolation, and the off-by-default switch.

No LLM is called. A stub Agent stands in for the child so these assert the
wiring — which template, which tools, which context, which guard — rather than
what a model happens to reply.
"""

import json
import shutil
import threading
import time
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parent.parent / "agent" / "subagent" / "assets"

import pytest

from agent.subagent import (
    BLOCKED_TOOLS,
    SubagentSettings,
    SubagentTask,
    current_depth,
    load_templates,
    parse_template,
    run_tasks,
)
from agent.tools.subagent import SubagentTool


class _Tool:
    def __init__(self, name):
        self.name = name


class _FakeParent:
    """Enough of an Agent for the runner to build a child from."""

    def __init__(self, tools, workspace_dir):
        self.tools = tools
        self.workspace_dir = workspace_dir
        self.model = object()
        self.max_steps = 7
        self.max_context_tokens = 1234
        self.skill_manager = None
        self.enable_skills = False
        self.runtime_info = None
        self.messages = []


@pytest.fixture
def workspace(tmp_path):
    return tmp_path / "ws"


@pytest.fixture
def parent(workspace):
    workspace.mkdir(parents=True, exist_ok=True)
    tools = [
        _Tool(n)
        for n in ("read", "ls", "search_files", "write", "bash", "send", "subagent")
    ]
    return _FakeParent(tools, str(workspace))


@pytest.fixture
def enabled(monkeypatch):
    settings = SubagentSettings(enabled=True, max_depth=1, max_concurrent=3, timeout_seconds=30)
    monkeypatch.setattr(SubagentSettings, "from_config", classmethod(lambda cls: settings))
    return settings


@pytest.fixture
def spawn_tool(parent, workspace):
    tool = SubagentTool({"cwd": str(workspace)})
    tool.context = parent
    return tool


def _capture_children(monkeypatch, reply="done"):
    """Replace the child Agent with a recorder."""
    built = []

    class _StubChild:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.extra_system_suffix = None
            built.append(self)

        def run_stream(self, goal, clear_history=False, cancel_event=None):
            self.goal = goal
            self.clear_history = clear_history
            self.depth_seen = current_depth()
            return reply

    monkeypatch.setattr("agent.protocol.agent.Agent", _StubChild)
    return built


# --- templates ---------------------------------------------------------------


def test_builtin_templates_are_always_available(workspace):
    templates = load_templates(str(workspace))
    assert "general-purpose" in templates
    assert "explore" in templates


def test_user_template_is_loaded_from_the_workspace(workspace):
    directory = workspace / "subagents"
    directory.mkdir(parents=True)
    (directory / "翻译.md").write_text(
        "---\nname: translator\ndescription: Translate documents.\ntools: read, write\n---\n"
        "You translate text and preserve formatting.\n",
        encoding="utf-8",
    )

    template = load_templates(str(workspace))["translator"]
    assert template.description == "Translate documents."
    assert template.tools == ["read", "write"]
    assert "preserve formatting" in template.prompt


def test_user_template_can_replace_a_builtin(workspace):
    directory = workspace / "subagents"
    directory.mkdir(parents=True)
    (directory / "explore.md").write_text(
        "---\nname: explore\ndescription: Mine.\n---\nMy own instructions.\n", encoding="utf-8"
    )

    assert load_templates(str(workspace))["explore"].description == "Mine."


def test_the_shipped_guide_is_not_offered_as_a_type(workspace):
    """README.md sits in the same directory as real templates. Loading it would
    put a bogus type in front of the Agent on every turn."""
    directory = workspace / "subagents"
    directory.mkdir(parents=True)
    (directory / "README.md").write_text(
        "---\nname: readme\ndescription: How to write one.\n---\nFormat docs.\n",
        encoding="utf-8",
    )

    templates = load_templates(str(workspace))
    assert "readme" not in templates
    assert set(templates) == {"general-purpose", "explore"}


def test_the_repo_ships_a_guide_that_documents_the_real_format():
    """The guide is what a user copies from, so it has to stay in step with the
    loader rather than drift into describing fields that do not exist."""
    guide = ASSET_DIR / "README.md"
    assert guide.is_file(), "no sub agent guide shipped for users to copy"
    text = guide.read_text(encoding="utf-8")

    for name in sorted(BLOCKED_TOOLS):
        assert name in text, f"the guide omits {name} from the denied-tools list"


def test_the_shipped_example_is_inert_until_renamed(workspace):
    """The example is there to be copied, so it has to parse — but it must not
    quietly become a type of its own, or every install would carry a research
    agent nobody asked for."""
    directory = workspace / "subagents"
    directory.mkdir(parents=True)
    for asset in ASSET_DIR.iterdir():
        shutil.copyfile(asset, directory / asset.name)

    assert set(load_templates(str(workspace))) == {"general-purpose", "explore"}

    example = directory / "example.md.template"
    assert example.is_file(), "no example shipped for users to copy"
    example.rename(directory / "research-report.md")

    templates = load_templates(str(workspace))
    added = set(templates) - {"general-purpose", "explore"}
    assert len(added) == 1, "renaming the example did not produce exactly one type"

    template = templates[added.pop()]
    assert template.description.strip(), "the example has no description to pick it by"
    assert template.tools != ["*"], "the example's tools list was ignored"
    assert not BLOCKED_TOOLS & set(template.tools)
    assert template.prompt.strip(), "the example has no instructions in its body"


@pytest.mark.parametrize(
    "content",
    [
        "---\nname: x\n---\nBody but no description.",
        "---\nname: x\ndescription: Has one.\n---\n",
        "No frontmatter at all.",
    ],
)
def test_unusable_templates_are_rejected(content):
    assert parse_template(content, "fallback", source="t.md") is None


def test_template_tool_selection_subtracts_the_blocklist(parent):
    templates = load_templates(parent.workspace_dir)

    explore = [t.name for t in templates["explore"].select_tools(parent.tools)]
    assert explore == ["read", "ls", "search_files"]

    general = [t.name for t in templates["general-purpose"].select_tools(parent.tools)]
    assert "write" in general and "bash" in general
    # "*" must not mean "including the ones no sub agent may have".
    assert not BLOCKED_TOOLS & set(general)
    assert "subagent" not in general and "send" not in general


# --- the child's context -----------------------------------------------------


def test_child_gets_the_task_but_not_the_parents_persona_or_memory(
    parent, workspace, enabled, monkeypatch
):
    built = _capture_children(monkeypatch)
    templates = load_templates(str(workspace))

    run_tasks(
        parent,
        [SubagentTask(goal="Find the config", context="Look under /etc", subagent_type="explore")],
        templates,
        enabled,
    )

    child = built[0]
    assert child.kwargs["skip_context_files"] is True
    assert child.kwargs["memory_manager"] is None
    assert child.kwargs["workspace_dir"] == str(workspace)
    assert child.kwargs["model"] is parent.model
    assert child.clear_history is True

    brief = child.extra_system_suffix
    assert "Find the config" in brief
    assert "Look under /etc" in brief
    assert "read-only" in brief


def test_skip_context_files_actually_keeps_the_persona_out_of_the_prompt(workspace):
    """The flag being passed is not the same as the flag working. This builds a
    real Agent, so a regression in get_full_system_prompt is caught here."""
    from agent.protocol.agent import Agent

    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "AGENT.md").write_text(
        "You are PIRATE-BOT and you always say Arrr.", encoding="utf-8"
    )

    inheriting = Agent(system_prompt="base", workspace_dir=str(workspace), enable_skills=False)
    isolated = Agent(
        system_prompt="base",
        workspace_dir=str(workspace),
        enable_skills=False,
        skip_context_files=True,
    )

    assert "PIRATE-BOT" in inheriting.get_full_system_prompt()
    assert "PIRATE-BOT" not in isolated.get_full_system_prompt()


def test_the_prompt_does_not_claim_context_files_it_did_not_load(workspace):
    """Suppressing the files but keeping the "already loaded, no need to read
    them" notice leaves the sub agent both uninformed and told not to look."""
    from agent.protocol.agent import Agent

    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "RULE.md").write_text("Always write output as HTML.", encoding="utf-8")

    inheriting = Agent(system_prompt="base", workspace_dir=str(workspace), enable_skills=False)
    isolated = Agent(
        system_prompt="base",
        workspace_dir=str(workspace),
        enable_skills=False,
        skip_context_files=True,
    )

    assert "RULE.md" in inheriting.get_full_system_prompt()
    assert "RULE.md" not in isolated.get_full_system_prompt()


def test_child_runs_one_level_deeper_than_its_parent(parent, workspace, enabled, monkeypatch):
    built = _capture_children(monkeypatch)

    assert current_depth() == 0
    run_tasks(parent, [SubagentTask(goal="go")], load_templates(str(workspace)), enabled)

    assert built[0].depth_seen == 1
    # The counter lives in the worker's context copy, so the caller is untouched.
    assert current_depth() == 0


# --- guards ------------------------------------------------------------------


def test_tool_is_refused_while_the_feature_is_off(spawn_tool, monkeypatch):
    off = SubagentSettings(enabled=False)
    monkeypatch.setattr(SubagentSettings, "from_config", classmethod(lambda cls: off))

    result = spawn_tool.execute({"goal": "anything"})
    assert result.status == "error"
    assert "disabled" in result.result


def test_depth_limit_stops_a_sub_agent_spawning_another(spawn_tool, enabled, monkeypatch):
    monkeypatch.setattr("agent.subagent.current_depth", lambda: 1)

    result = spawn_tool.execute({"goal": "recurse"})
    assert result.status == "error"
    assert "max_depth" in result.result


def test_batch_larger_than_the_concurrency_limit_is_refused(spawn_tool, enabled):
    result = spawn_tool.execute({"tasks": [{"goal": f"t{i}"} for i in range(enabled.max_concurrent + 1)]})
    assert result.status == "error"
    assert "max_concurrent" in result.result


def test_unknown_type_names_what_is_available(spawn_tool, enabled):
    result = spawn_tool.execute({"goal": "go", "subagent_type": "nope"})
    assert result.status == "error"
    assert "nope" in result.result and "general-purpose" in result.result


def test_missing_goal_is_refused(spawn_tool, enabled):
    assert spawn_tool.execute({}).status == "error"
    assert spawn_tool.execute({"tasks": []}).status == "error"


def test_a_task_that_overruns_its_budget_is_reported_not_dropped(parent, workspace, monkeypatch):
    settings = SubagentSettings(enabled=True, max_depth=1, max_concurrent=2, timeout_seconds=0.2)
    started = threading.Event()

    class _Hanging:
        def __init__(self, **kwargs):
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None):
            started.set()
            # Honour the cancel the runner sets on timeout, as a real run would.
            cancel_event.wait(timeout=5)
            return ""

    monkeypatch.setattr("agent.protocol.agent.Agent", _Hanging)

    results = run_tasks(parent, [SubagentTask(goal="hang")], load_templates(str(workspace)), settings)

    assert started.is_set()
    assert len(results) == 1
    assert results[0]["status"] == "timeout"
    assert "timeout_seconds" in results[0]["error"]


def test_a_timed_out_call_returns_without_waiting_for_the_worker(parent, workspace, monkeypatch):
    """Joining the abandoned thread would make the call overrun the very budget
    the timeout exists to enforce."""
    settings = SubagentSettings(enabled=True, max_depth=1, max_concurrent=2, timeout_seconds=0.2)
    release = threading.Event()

    class _Stuck:
        def __init__(self, **kwargs):
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None):
            release.wait(timeout=10)  # ignores the cancel, as a wedged run would
            return ""

    monkeypatch.setattr("agent.protocol.agent.Agent", _Stuck)

    started = time.time()
    results = run_tasks(parent, [SubagentTask(goal="stuck")], load_templates(str(workspace)), settings)
    elapsed = time.time() - started
    release.set()

    assert results[0]["status"] == "timeout"
    assert elapsed < 5, f"run_tasks blocked for {elapsed:.1f}s waiting on the abandoned worker"


def test_siblings_do_not_share_tool_instances(parent, workspace, enabled, monkeypatch):
    """The agent loop clears cancel_event on a tool after each call. Shared
    instances would let one sibling disarm another's timeout."""
    seen = []

    class _Recording:
        def __init__(self, **kwargs):
            self.tools = kwargs["tools"]
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None):
            # Keep the objects alive, not their ids: a freed copy's address can
            # be handed straight back to the next allocation.
            seen.append({t.name: t for t in self.tools})
            return "ok"

    monkeypatch.setattr("agent.protocol.agent.Agent", _Recording)

    run_tasks(
        parent,
        [SubagentTask(goal="a"), SubagentTask(goal="b")],
        load_templates(str(workspace)),
        enabled,
    )

    parent_tools = {t.name: t for t in parent.tools}
    assert len(seen) == 2
    for name in seen[0]:
        assert seen[0][name] is not seen[1][name], f"siblings share the same {name} instance"
        assert seen[0][name] is not parent_tools[name], f"child shares the parent's {name} instance"


def test_a_failing_task_is_reported_as_failed(parent, workspace, enabled, monkeypatch):
    class _Exploding:
        def __init__(self, **kwargs):
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr("agent.protocol.agent.Agent", _Exploding)

    results = run_tasks(parent, [SubagentTask(goal="boom")], load_templates(str(workspace)), enabled)
    assert results[0]["status"] == "failed"
    assert "model unavailable" in results[0]["error"]


def test_all_tasks_failing_surfaces_as_a_tool_error(spawn_tool, enabled, monkeypatch):
    """A parent that reads a success result will report findings to the user.
    There are none, so this must not come back as success."""

    class _Exploding:
        def __init__(self, **kwargs):
            self.extra_system_suffix = None

        def run_stream(self, goal, clear_history=False, cancel_event=None):
            raise RuntimeError("nope")

    monkeypatch.setattr("agent.protocol.agent.Agent", _Exploding)

    result = spawn_tool.execute({"goal": "go"})
    assert result.status == "error"


# --- results and the tool description ----------------------------------------


def test_results_come_back_one_per_task_in_order(spawn_tool, enabled, monkeypatch):
    _capture_children(monkeypatch, reply="the answer")

    result = spawn_tool.execute(
        {"tasks": [{"goal": "first"}, {"goal": "second", "subagent_type": "explore"}]}
    )

    assert result.status == "success"
    results = json.loads(result.result)["results"]
    assert [r["task_index"] for r in results] == [0, 1]
    assert [r["subagent_type"] for r in results] == ["general-purpose", "explore"]
    assert all(r["summary"] == "the answer" for r in results)


def test_description_lists_the_types_the_model_can_pick(spawn_tool, enabled, workspace):
    directory = workspace / "subagents"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "auditor.md").write_text(
        "---\nname: auditor\ndescription: Review changes for defects.\n---\nAudit carefully.\n",
        encoding="utf-8",
    )

    description = spawn_tool.description
    assert "auditor: Review changes for defects." in description
    assert "general-purpose:" in description and "explore:" in description
    # The listing is rebuilt per read, so a template added mid-session shows up.
    (directory / "auditor.md").unlink()
    assert "auditor:" not in spawn_tool.description


def test_description_reaches_the_model_through_get_json_schema(spawn_tool, enabled):
    """The agent loop reads `.description`; other callers read the schema.
    They must not disagree."""
    assert spawn_tool.get_json_schema()["description"] == spawn_tool.description
