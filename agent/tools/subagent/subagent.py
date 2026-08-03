"""The tool the main Agent uses to hand work to a sub agent.

Deliberately not the tool for reaching a peer Agent. A sub agent is a way this
Agent gets work done; a peer has its own workspace, identity and permissions, so
handing work across that boundary is a different decision, needs a different
authorization, and belongs in its own tool.
"""

import json
from typing import List

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger


_STATIC_DESCRIPTION = (
    "Hand a self-contained task to a sub agent that works in its own context "
    "and reports back with only its conclusion."
)


class SubagentTool(BaseTool):
    name = "subagent"

    params = {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": (
                    "What the sub agent should accomplish. Write it as a complete "
                    "instruction to someone who has never seen this conversation."
                ),
            },
            "context": {
                "type": "string",
                "description": (
                    "Everything the sub agent needs and cannot look up: file paths, "
                    "error text, decisions already made, what to leave alone. It "
                    "cannot see your conversation, so anything you omit is lost."
                ),
            },
            "subagent_type": {
                "type": "string",
                "description": "Which kind of sub agent to use. See the list in this tool's description.",
            },
            "tasks": {
                "type": "array",
                "description": (
                    "Run several tasks at once instead of one. Each entry takes the "
                    "same goal / context / subagent_type fields. Use this rather than "
                    "calling this tool several times: entries here run in parallel, "
                    "separate calls run one after another."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string"},
                        "context": {"type": "string"},
                        "subagent_type": {"type": "string"},
                    },
                    "required": ["goal"],
                },
            },
        },
        "required": [],
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd")

    # --- what the model reads -------------------------------------------------

    @property
    def description(self) -> str:
        """Rebuilt on every read so a template added to the workspace is
        offered on the next turn, without a restart."""
        from agent.subagent import SubagentSettings, load_templates

        try:
            templates = load_templates(self.cwd)
            settings = SubagentSettings.from_config()
        except Exception as e:
            logger.debug(f"[SubagentTool] Falling back to static description: {e}")
            return _STATIC_DESCRIPTION

        listing = "\n".join(
            f"- {name}: {template.description}"
            for name, template in sorted(templates.items())
        )
        return (
            "Hand a self-contained task to a sub agent that works in its own "
            "context.\n\n"
            "Available sub agent types:\n"
            f"{listing}\n\n"
            "Only the sub agent's conclusion comes back to you; everything it "
            "read or ran on the way stays out of your context. That is what you "
            "are buying, and it costs a full model run.\n\n"
            "USE IT WHEN:\n"
            "- The search is open-ended and most of what gets read will turn out "
            "to be irrelevant.\n"
            "- Several independent pieces of work can proceed at once. Put them "
            f"in `tasks` (up to {settings.max_concurrent}) and they run in "
            "parallel, so the batch costs about as long as its slowest task "
            "rather than the sum. Separate calls run one after another.\n\n"
            "DO NOT USE IT WHEN:\n"
            "- You already know which file or command answers the question. Just "
            "do it.\n"
            "- The task needs something the user said earlier, or needs to ask "
            "the user anything. The sub agent can do neither.\n"
            "- You would be handing over your whole task unchanged. That buys a "
            "round trip and nothing else.\n"
            "- The work must outlive this conversation. Use the scheduler.\n\n"
            "The sub agent starts with no history, so state the goal in full and "
            "put every path, identifier and constraint it needs into `context`; "
            "a vague goal comes back as a vague answer. Its reply is not shown "
            "to the user, so read it and say what matters in your own words."
        )

    # --- execution ------------------------------------------------------------

    def _collect_tasks(self, params: dict) -> List:
        from agent.subagent import SubagentTask

        raw_tasks = params.get("tasks")
        if isinstance(raw_tasks, list) and raw_tasks:
            tasks = []
            for entry in raw_tasks:
                if not isinstance(entry, dict):
                    continue
                goal = str(entry.get("goal") or "").strip()
                if not goal:
                    continue
                tasks.append(
                    SubagentTask(
                        goal=goal,
                        context=str(entry.get("context") or ""),
                        subagent_type=entry.get("subagent_type"),
                    )
                )
            return tasks

        goal = str(params.get("goal") or "").strip()
        if not goal:
            return []
        return [
            SubagentTask(
                goal=goal,
                context=str(params.get("context") or ""),
                subagent_type=params.get("subagent_type"),
            )
        ]

    def execute(self, params: dict) -> ToolResult:
        from agent.subagent import SubagentSettings, current_depth, load_templates, run_tasks

        settings = SubagentSettings.from_config()
        if not settings.enabled:
            return ToolResult.fail("Sub agents are disabled. Set subagent.enabled in config.json.")

        parent = getattr(self, "context", None)
        if parent is None:
            return ToolResult.fail("No parent agent available to spawn from.")

        depth = current_depth()
        if depth >= settings.max_depth:
            return ToolResult.fail(
                f"Already {depth} level(s) deep, and subagent.max_depth is "
                f"{settings.max_depth}. Do this task yourself instead of delegating it."
            )

        tasks = self._collect_tasks(params)
        if not tasks:
            return ToolResult.fail("Provide 'goal', or 'tasks' with at least one goal.")
        if len(tasks) > settings.max_concurrent:
            return ToolResult.fail(
                f"{len(tasks)} tasks requested but subagent.max_concurrent is "
                f"{settings.max_concurrent}. Send fewer, or split across turns."
            )

        templates = load_templates(parent.workspace_dir or self.cwd)
        unknown = sorted(
            {t.subagent_type for t in tasks if t.subagent_type and t.subagent_type not in templates}
        )
        if unknown:
            return ToolResult.fail(
                f"Unknown sub agent type(s): {', '.join(unknown)}. "
                f"Available: {', '.join(sorted(templates))}."
            )

        self.report_progress(
            f"Spawning {len(tasks)} sub agent(s)"
            if len(tasks) > 1
            else f"Spawning sub agent: {tasks[0].goal[:60]}"
        )
        logger.info(f"[SubagentTool] Running {len(tasks)} task(s) at depth {depth + 1}")

        results = run_tasks(parent, tasks, templates, settings)
        if all(r.get("status") not in ("completed", "cancelled") for r in results):
            # Every task failed or timed out: surfacing this as success would
            # let the parent report findings that do not exist.
            return ToolResult.fail(json.dumps({"results": results}, ensure_ascii=False))
        return ToolResult.success(json.dumps({"results": results}, ensure_ascii=False))
