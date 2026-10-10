"""Bound skills are returned before a matching tool call runs."""

from pathlib import Path

from agent.protocol.agent_stream import AgentStreamExecutor
from agent.skills.manager import SkillManager
from agent.skills.tool_binding import pending_skill_result, skill_marker
from agent.tools.base_tool import BaseTool, ToolResult


ELEARNING_BODY = "只同步新增的 ppt、pptx 和 pdf，禁止整门课重下。"
BILLS_BODY = "记账必须走内置 bills 工具，时间用北京时间。"


def _write_skill(root: Path, folder: str, name: str, body: str, bindings: str) -> Path:
    directory = root / folder
    directory.mkdir(parents=True)
    path = directory / "SKILL.md"
    path.write_text(
        "---\n"
        f"name: {name}\n"
        "description: Use when this skill applies.\n"
        "metadata:\n"
        "  stella:\n"
        "    tool_bindings:\n"
        f"{bindings}"
        "---\n\n"
        f"# {name}\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


def _manager(tmp_path: Path) -> SkillManager:
    builtin = tmp_path / "builtin"
    custom = tmp_path / "custom"
    builtin.mkdir()
    _write_skill(
        custom,
        "elearning-courseware-sync",
        "elearning-courseware-sync",
        ELEARNING_BODY,
        "      - tool: elearning\n        actions: [list_files, sync_files]\n",
    )
    _write_skill(
        custom,
        "bills",
        "bookkeeping",
        BILLS_BODY,
        "      - tool: bills\n",
    )
    return SkillManager(builtin_dir=str(builtin), custom_dir=str(custom))


class RecordingTool(BaseTool):
    description = "recording tool"
    params = {"type": "object", "properties": {"action": {"type": "string"}}}

    def __init__(self, name: str):
        self.name = name
        self.calls = []

    def execute(self, params):
        self.calls.append(dict(params))
        return ToolResult.success("ran")


class _Agent:
    def __init__(self, skill_manager):
        self.skill_manager = skill_manager


def _executor(skill_manager, tool: RecordingTool, messages=None) -> AgentStreamExecutor:
    executor = AgentStreamExecutor(
        agent=_Agent(skill_manager),
        model=None,
        system_prompt="",
        tools=[tool],
        messages=messages if messages is not None else [],
    )
    executor._permission_denial = lambda *_args, **_kwargs: None
    return executor


def test_action_binding_and_tool_wide_binding_are_parsed(tmp_path):
    manager = _manager(tmp_path)
    elearning = manager.skills["elearning-courseware-sync"].metadata.tool_bindings
    bills = manager.skills["bookkeeping"].metadata.tool_bindings

    assert [(item.tool, item.actions) for item in elearning] == [
        ("elearning", frozenset({"list_files", "sync_files"}))
    ]
    assert [(item.tool, item.actions) for item in bills] == [("bills", None)]


def test_bound_call_returns_skill_and_does_not_run(tmp_path):
    manager = _manager(tmp_path)
    tool = RecordingTool("elearning")
    recorded = []
    executor = _executor(manager, tool)
    executor._record_tool_result = lambda *args: recorded.append(args)

    result = executor._execute_tool({
        "id": "call-1",
        "name": "elearning",
        "arguments": {"action": "sync_files", "file_ids": ["1"]},
    })

    assert tool.calls == []
    assert recorded == []
    assert result["status"] == "skill_required"
    assert ELEARNING_BODY in result["result"]
    assert skill_marker("elearning-courseware-sync") in result["result"]
    assert "尚未执行" in result["result"]


def test_unbound_action_and_unbound_tool_still_run(tmp_path):
    manager = _manager(tmp_path)
    courses = RecordingTool("elearning")
    other = RecordingTool("calendar")

    courses_result = _executor(manager, courses)._execute_tool({
        "id": "call-courses",
        "name": "elearning",
        "arguments": {"action": "courses"},
    })
    no_action = _executor(manager, courses)._execute_tool({
        "id": "call-limit",
        "name": "elearning",
        "arguments": {"limit": 1},
    })
    other_result = _executor(manager, other)._execute_tool({
        "id": "call-calendar",
        "name": "calendar",
        "arguments": {"action": "list"},
    })

    assert courses.calls == [{"action": "courses"}, {"limit": 1}]
    assert other.calls == [{"action": "list"}]
    assert courses_result["status"] == "success"
    assert no_action["result"] == "ran"
    assert other_result["result"] == "ran"


def test_bills_binding_covers_every_action(tmp_path):
    manager = _manager(tmp_path)
    tool = RecordingTool("bills")
    result = _executor(manager, tool)._execute_tool({
        "id": "call-bill",
        "name": "bills",
        "arguments": {"action": "add", "amount": 12},
    })

    assert tool.calls == []
    assert result["status"] == "skill_required"
    assert BILLS_BODY in result["result"]
    assert skill_marker("bookkeeping") in result["result"]


def test_marker_or_prior_read_lets_the_tool_run(tmp_path):
    manager = _manager(tmp_path)
    skill = manager.skills["elearning-courseware-sync"].skill
    marked = RecordingTool("elearning")
    marked_result = _executor(manager, marked, messages=[{
        "role": "user",
        "content": [{"type": "tool_result", "content": skill_marker(skill.name)}],
    }])._execute_tool({
        "id": "call-marked",
        "name": "elearning",
        "arguments": {"action": "list_files"},
    })

    read = RecordingTool("elearning")
    read_result = _executor(manager, read, messages=[
        {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "read-1",
                "name": "read",
                "input": {"path": skill.file_path},
            }],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "read-1",
                "content": skill.content,
            }],
        },
    ])._execute_tool({
        "id": "call-read",
        "name": "elearning",
        "arguments": {"action": "sync_files"},
    })

    assert marked.calls == [{"action": "list_files"}]
    assert read.calls == [{"action": "sync_files"}]
    assert marked_result["result"] == "ran"
    assert read_result["result"] == "ran"


def test_second_call_in_the_same_turn_still_waits(tmp_path):
    manager = _manager(tmp_path)
    tool = RecordingTool("elearning")
    executor = _executor(manager, tool)
    first = executor._execute_tool({
        "id": "call-1",
        "name": "elearning",
        "arguments": {"action": "sync_files"},
    })
    second = executor._execute_tool({
        "id": "call-2",
        "name": "elearning",
        "arguments": {"action": "list_files"},
    })

    assert tool.calls == []
    assert first["status"] == "skill_required"
    assert second["status"] == "skill_required"


def test_same_turn_read_without_result_still_blocks(tmp_path):
    manager = _manager(tmp_path)
    skill = manager.skills["elearning-courseware-sync"].skill
    tool = RecordingTool("elearning")
    result = _executor(manager, tool, messages=[{
        "role": "assistant",
        "content": [{
            "type": "tool_use",
            "id": "read-1",
            "name": "read",
            "input": {"path": skill.file_path},
        }],
    }])._execute_tool({
        "id": "call-sync",
        "name": "elearning",
        "arguments": {"action": "sync_files"},
    })

    assert tool.calls == []
    assert result["status"] == "skill_required"


def test_disabled_skill_does_not_gate(tmp_path):
    manager = _manager(tmp_path)
    manager.set_skill_enabled("bookkeeping", False)
    tool = RecordingTool("bills")
    result = _executor(manager, tool)._execute_tool({
        "id": "call-bill",
        "name": "bills",
        "arguments": {"action": "query"},
    })

    assert tool.calls == [{"action": "query"}]
    assert result["result"] == "ran"
    assert pending_skill_result(manager, "bills", {"action": "query"}, []) is None


def test_missing_skill_manager_does_not_gate():
    tool = RecordingTool("elearning")
    result = _executor(None, tool)._execute_tool({
        "id": "call-1",
        "name": "elearning",
        "arguments": {"action": "sync_files"},
    })

    assert tool.calls == [{"action": "sync_files"}]
    assert result["result"] == "ran"
