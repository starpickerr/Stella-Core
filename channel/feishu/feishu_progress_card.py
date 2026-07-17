"""State and Card 2.0 rendering for a Feishu agent run."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


_MAX_PANEL_STEPS = 10
_MAX_STEP_CHARS = 800


class FeishuProgressState:
    """Reduce CowAgent stream events into one renderable Feishu card state."""

    def __init__(self, started_at: Optional[float] = None):
        self.started_at = time.monotonic() if started_at is None else started_at
        self.status = "running"
        self.turns = 0
        self.current_text = ""
        self._reasoning_buffer = ""
        self.reasoning_steps: List[str] = []
        self.tool_steps: List[Dict[str, str]] = []
        self.cancelled = False

    def consume(self, event: Dict[str, Any]) -> None:
        """Consume one event emitted by ``AgentStreamHandler``."""
        event_type = event.get("type")
        data = event.get("data") or {}

        if event_type == "turn_start":
            self._mark_running_tools_done()
            turn = data.get("turn")
            if isinstance(turn, int):
                self.turns = max(self.turns, turn)
            else:
                self.turns += 1
            if self.turns > 1:
                self.current_text = ""
            return

        if event_type == "reasoning_update":
            self._reasoning_buffer += str(data.get("delta") or "")
            return

        if event_type == "message_update":
            self.current_text += str(data.get("delta") or "")
            return

        if event_type == "message_end":
            self._commit_reasoning()
            for tool_call in data.get("tool_calls") or []:
                self.tool_steps.append(
                    {
                        "summary": _format_tool_call(tool_call),
                        "status": "running",
                    }
                )
            return

        if event_type == "agent_cancelled":
            self.cancelled = True
            self.status = "stopped"
            return

        if event_type == "agent_end":
            self._commit_reasoning()
            self._mark_running_tools_done()
            cancelled = self.cancelled or bool(data.get("cancelled"))
            if cancelled:
                self.status = "stopped"
                self.current_text = self.current_text.rstrip() or "_(stopped)_"
            else:
                self.status = "done"
                final_response = data.get("final_response")
                if final_response:
                    self.current_text = str(final_response)

    def build_card(self, streaming: bool, now: Optional[float] = None) -> Dict[str, Any]:
        """Render the current state as a Feishu Card 2.0 object."""
        title, template = {
            "running": ("Working", "blue"),
            "done": ("Done", "green"),
            "stopped": ("Stopped", "grey"),
            "error": ("Error", "red"),
        }.get(self.status, ("Working", "blue"))

        main_text = self.current_text or "..."
        elements: List[Dict[str, Any]] = []

        if self.reasoning_steps:
            elements.append(
                _panel(
                    "Reasoning ({})".format(len(self.reasoning_steps)),
                    [_text_row(step, muted=True) for step in self.reasoning_steps[-_MAX_PANEL_STEPS:]],
                    expanded=streaming,
                )
            )
        elif streaming:
            elements.append(
                _panel("Reasoning", [_text_row("Thinking...", muted=True)], expanded=True)
            )

        if self.tool_steps:
            elements.append(
                _panel(
                    "Tools ({})".format(len(self.tool_steps)),
                    [
                        _text_row("{} · {}".format(step["summary"], step["status"]))
                        for step in self.tool_steps[-_MAX_PANEL_STEPS:]
                    ],
                    expanded=streaming,
                )
            )

        elements.append(
            {
                "tag": "markdown",
                "element_id": "stream_md",
                "content": main_text,
            }
        )

        elapsed = max(0.0, (time.monotonic() if now is None else now) - self.started_at)
        turn_label = "turn" if self.turns == 1 else "turns"
        elements.extend(
            [
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": "{:.1f}s · {} {}".format(elapsed, self.turns, turn_label),
                    "text_size": "notation",
                },
            ]
        )

        config: Dict[str, Any] = {
            "streaming_mode": streaming,
            "update_multi": True,
            "enable_forward_interaction": True,
            "summary": {"content": _summary(main_text, title)},
        }
        if streaming:
            config["streaming_config"] = {
                "print_frequency_ms": {"default": 40},
                "print_step": {"default": 4},
                "print_strategy": "fast",
            }

        return {
            "schema": "2.0",
            "config": config,
            "header": {
                "template": template,
                "title": {"tag": "plain_text", "content": title},
            },
            "body": {"elements": elements},
        }

    def _commit_reasoning(self) -> None:
        reasoning = self._reasoning_buffer.strip()
        if reasoning:
            self.reasoning_steps.append(reasoning[-_MAX_STEP_CHARS:])
        self._reasoning_buffer = ""

    def _mark_running_tools_done(self) -> None:
        for step in self.tool_steps:
            if step["status"] == "running":
                step["status"] = "done"


def _format_tool_call(tool_call: Dict[str, Any]) -> str:
    # Tool arguments can contain user data or credentials. The progress card
    # only needs an activity label, so never echo raw arguments into chat.
    return str(tool_call.get("name") or "tool")


def _panel(title: str, elements: List[Dict[str, Any]], expanded: bool) -> Dict[str, Any]:
    return {
        "tag": "collapsible_panel",
        "expanded": expanded,
        "background_color": "grey",
        "header": {"title": {"tag": "plain_text", "content": title}},
        "border": {"color": "grey"},
        "vertical_spacing": "8px",
        "padding": "4px 8px",
        "elements": elements,
    }


def _text_row(content: str, muted: bool = False) -> Dict[str, Any]:
    text = {
        "tag": "plain_text",
        "content": content,
        "text_size": "notation",
    }
    if muted:
        text["text_color"] = "grey"
    return {"tag": "div", "text": text}


def _summary(text: str, fallback: str) -> str:
    preview = " ".join(text.strip().split())
    return preview[:60] or fallback
