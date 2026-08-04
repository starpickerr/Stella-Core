"""The tool the main Agent uses to hand work to a sub agent.

Deliberately not the tool for reaching a peer Agent. A sub agent is a way this
Agent gets work done; a peer has its own workspace, identity and permissions, so
handing work across that boundary is a different decision, needs a different
authorization, and belongs in its own tool.
"""

import json
import uuid
from typing import List

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger


_STATIC_DESCRIPTION = (
    "Hand a self-contained task to a sub agent that works in its own context "
    "and reports back with only its conclusion."
)


class SubagentTool(BaseTool):
    name = "subagent"
    # Sub agents share nothing but the workspace, so two of them running at
    # once is the same situation as two tasks inside one call. Models routinely
    # express independent work as several calls rather than one call with a
    # list; this lets that phrasing run just as fast.
    parallel_safe = True

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
                    "Run several tasks at once instead of one. Each entry takes "
                    "the same goal / context / subagent_type fields, and every "
                    "entry runs in parallel."
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
            "The task must be self-contained: statable in full up front, and "
            "answerable without you or the user in the loop.\n\n"
            "USE IT WHEN:\n"
            "- Independent pieces of work can proceed at once. Send one per "
            f"entry in `tasks` (up to {settings.max_concurrent}); they run in "
            "parallel.\n"
            "- One piece would bury you in output you won't need again. Hand "
            "over the question, not the individual queries.\n\n"
            "DO NOT USE IT WHEN:\n"
            "- You need what it would find in order to keep working. A few "
            "reads or searches of your own are normal work, not grounds to "
            "delegate.\n"
            "- The task needs something the user said earlier, or needs to ask "
            "the user anything. The sub agent can do neither.\n"
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

    def _card_reporter(self, tasks: List):
        """Announce each sub agent separately while they run.

        A spawn of several sub agents is one tool call, so without this the
        client shows one spinner for the lot: no telling how many are running,
        which one is still going, or what any of them found. Giving each its
        own id turns them into entries the client already knows how to render.

        Skipped for a lone sub agent, which the call itself already stands for.
        """
        if len(tasks) < 2:
            return None

        ids = [uuid.uuid4().hex[:12] for _ in tasks]
        closed = set()

        def on_state(index: int, state: dict) -> None:
            name = f"subagent:{state.get('subagent_type') or 'unknown'}"
            if state.get("status") == "running":
                self.emit_event("tool_execution_start", {
                    "tool_call_id": ids[index],
                    "tool_name": name,
                    "arguments": {"goal": tasks[index].goal},
                })
                return
            # A task cancelled on timeout settles twice: once when the timeout
            # is declared, once when the run it belongs to notices. The first
            # is the one that explains what happened.
            if index in closed:
                return
            closed.add(index)
            self.emit_event("tool_execution_end", {
                "tool_call_id": ids[index],
                "tool_name": name,
                "status": "success" if state.get("status") == "completed" else "error",
                "result": state.get("summary") or state.get("error") or "",
                "execution_time": state.get("duration_seconds", 0),
            })

        return on_state

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

        results = run_tasks(parent, tasks, templates, settings, on_state=self._card_reporter(tasks))
        if all(r.get("status") not in ("completed", "cancelled") for r in results):
            # Every task failed or timed out: surfacing this as success would
            # let the parent report findings that do not exist.
            return ToolResult.fail(json.dumps({"results": results}, ensure_ascii=False))
        return ToolResult.success(json.dumps({"results": results}, ensure_ascii=False))
