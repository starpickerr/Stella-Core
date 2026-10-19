"""Scheduler domain: persistence, background loop, and AgentBridge glue.

The model-facing tool lives in ``agent.tools.scheduler`` and is a thin
adapter over this package.
"""

from agent.scheduler.store import TaskStore
from agent.scheduler.service import SchedulerService
from agent.scheduler.integration import (
    attach_scheduler_to_tool,
    get_scheduler_service,
    get_task_store,
    init_scheduler,
    reset_scheduler_services,
)

__all__ = [
    "TaskStore",
    "SchedulerService",
    "init_scheduler",
    "get_task_store",
    "get_scheduler_service",
    "reset_scheduler_services",
    "attach_scheduler_to_tool",
]
