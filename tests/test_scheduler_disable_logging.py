"""Non-retryable scheduler failures disable the task and write a warning."""
from datetime import datetime

from agent.scheduler.outcome import ExecutionOutcome
from agent.scheduler.service import SchedulerService
from common.log import logger


def test_non_retryable_failure_disables_task_and_logs(caplog):
    updates = []

    class Store:
        def update_task(self, task_id, fields):
            updates.append((task_id, fields))

    service = SchedulerService(Store(), execute_callback=lambda _task: None)
    service._is_task_due = lambda *_a, **_k: True
    service._claim_task = lambda *_a, **_k: True
    service._release_task = lambda *_a, **_k: None
    service._execute_task = lambda _task: ExecutionOutcome("failed", "permission denied", retryable=False)

    task = {"id": "task-1", "name": "Probe", "enabled": True, "next_run_at": datetime.now().isoformat()}
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("WARNING", logger=logger.name):
            service._check_one_task(task, datetime.now())
    finally:
        logger.removeHandler(caplog.handler)

    assert any(fields.get("enabled") is False for _, fields in updates)
    assert "disabled after non-retryable failure" in caplog.text
    assert "permission denied" in caplog.text
