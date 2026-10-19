"""Background scheduler service for executing scheduled tasks."""

import time
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional
from common.log import logger
from agent.scheduler.cron import iter_cron


def _parse_naive_local(iso_str: str) -> datetime:
    """Parse an ISO datetime and coerce it to tz-naive local time.

    The scheduler uses ``datetime.now()`` (tz-naive) for all comparisons,
    so any persisted timestamp must be normalized to the same flavor —
    otherwise comparing naive vs aware raises TypeError.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


class SchedulerService:
    """
    Background service that executes scheduled tasks
    """
    
    def __init__(self, task_store, execute_callback: Callable):
        """
        Initialize scheduler service
        
        Args:
            task_store: TaskStore instance
            execute_callback: Function to call when executing a task
        """
        self.task_store = task_store
        self.execute_callback = execute_callback
        self.running = False
        self.thread = None
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self._execution_lock = threading.Lock()
        self._active_task_ids = set()
    
    def start(self):
        """Start the scheduler service"""
        with self._lock:
            if self.running:
                logger.warning("[Scheduler] Service already running")
                return
            
            self.stop_event.clear()
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
    
    def stop(self):
        """Stop the scheduler service"""
        with self._lock:
            if not self.running:
                return
            
            self.running = False
            self.stop_event.set()
            if self.thread:
                self.thread.join(timeout=5)
            logger.info("[Scheduler] Service stopped")
    
    def _run_loop(self):
        """Main scheduler loop"""
        logger.info("[Scheduler] Scheduler loop started")
        
        while self.running:
            try:
                self._check_and_execute_tasks()
                if hasattr(self.task_store, "agent_id"):
                    from common.runtime_identity import identity_scope
                    from agent.briefing.service import BriefingService
                    from agent.briefing.outbox import dispatch_pending
                    with identity_scope(agent_id=self.task_store.agent_id):
                        dispatch_pending(BriefingService().store)
            except Exception as e:
                logger.error(f"[Scheduler] Error in scheduler loop: {e}")

            time.sleep(30)
    
    def _recover_pending_reminder_links(self):
        from common.runtime_identity import identity_scope
        from core.plugins.caller import caller_origin_scope
        from core.plugins.management import default_store
        from core.services.todos_public import reconcile_pending_reminders

        management = default_store()
        for user in management.users('stella.tasks'):
            if management.instance('stella.tasks', user)['intent'] != 'enabled':
                continue
            try:
                with identity_scope(user_id=user, agent_id=getattr(self.task_store, 'agent_id', None)):
                    with caller_origin_scope('scheduler'):
                        reconcile_pending_reminders()
            except Exception as exc:
                # Recovery must not postpone unrelated deliveries, and never
                # creates a new background grant to make a repair succeed.
                logger.warning('[Scheduler] Tasks reminder recovery deferred user=%s: %s', user, exc)

    def _check_and_execute_tasks(self):
        """Check for due tasks and execute them"""
        now = datetime.now()
        tasks = (self.task_store.list_tasks(enabled_only=True, include_all=True)
                 if hasattr(self.task_store, "claim_occurrence") else
                 self.task_store.list_tasks(enabled_only=True))
        
        for task in tasks:
            if hasattr(self.task_store, "claim_occurrence"):
                from common.runtime_identity import identity_scope
                with identity_scope(agent_id=self.task_store.agent_id,
                                    user_id=task.get("owner_user_id") or None):
                    self._check_one_task(task, now)
            else:
                self._check_one_task(task, now)

        self._recover_pending_reminder_links()

    def _check_one_task(self, task, now):
        try:
            if not self._is_task_due(task, now):
                return
            logger.info(f"[Scheduler] Executing task: {task['id']} - {task['name']}")
            if not self._claim_task(task['id']):
                logger.info(f"[Scheduler] Task {task['id']} is already running; skipping this tick")
                return
            job_run_id = None
            try:
                if hasattr(self.task_store, "claim_occurrence"):
                    job_run_id = self.task_store.claim_occurrence(task['id'], task.get("next_run_at"))
                    if job_run_id is None:
                        if self.task_store.occurrence_status(
                            task['id'], task.get("next_run_at")) == "completed":
                            # The action finished before a crash, but advancing
                            # next_run_at did not. Finish that transition now.
                            self._advance_completed_task(task, now)
                        return
                run_task = dict(task, job_run_id=job_run_id) if job_run_id else task
                ok = self._execute_task(run_task)
                if job_run_id:
                    self.task_store.finish_occurrence(job_run_id, ok)
            finally:
                self._release_task(task['id'])
            if not ok:
                from agent.scheduler.outcome import ExecutionOutcome
                if isinstance(ok, ExecutionOutcome) and not ok.retryable:
                    self.task_store.update_task(task['id'], {"enabled": False, "retry_at": None,
                        "last_error": ok.error, "last_run_status": ok.status,
                        "last_error_at": datetime.now().isoformat()})
                    logger.warning(
                        "[Scheduler] Task %s disabled after non-retryable failure: %s %s",
                        task["id"], ok.status, ok.error,
                    )
                    return
                self.task_store.update_task(task['id'], {
                    "last_run_status": ok.status if isinstance(ok, ExecutionOutcome) else "delivery_pending",
                    "last_error": ok.error if isinstance(ok, ExecutionOutcome) else "Delivery pending; the saved execution output will be reused",
                    "last_error_at": datetime.now().isoformat(),
                })
                retry_seconds = task.get("retry_interval_seconds", 0)
                if retry_seconds:
                    self.task_store.update_task(task['id'], {
                        "retry_at": (datetime.now() + timedelta(seconds=retry_seconds)).isoformat(),
                    })
                logger.warning(f"[Scheduler] Task {task['id']} delivery failed, will retry next tick")
                return
            self._advance_completed_task(task, now)
        except Exception as e:
            logger.error(f"[Scheduler] Error processing task {task.get('id')}: {e}")

    def _advance_completed_task(self, task, now):
        self.task_store.update_task(task['id'], {"last_run_status": "completed", "last_error": None})
        next_run = self._calculate_next_run(task, now)
        if next_run:
            self.task_store.update_task(task['id'], {
                "next_run_at": next_run.isoformat(), "last_run_at": now.isoformat(),
                "retry_at": None,
            })
        else:
            self.task_store.update_task(task['id'], {
                "enabled": False, "next_run_at": None, "retry_at": None,
                "last_run_at": now.isoformat(),
                "completed_at" if task.get("schedule", {}).get("type") == "once" else "stopped_at": now.isoformat(),
            })
            logger.info(f"[Scheduler] Task {task['id']} completed with no next run")

    def run_task_now(self, task_id: str) -> None:
        """Queue one immediate execution without changing the task schedule.

        Disabled and one-time tasks may be run manually for testing. The
        stored ``next_run_at`` remains unchanged, so a manual run never
        consumes or delays the next scheduled occurrence.

        Raises:
            ValueError: if the task does not exist.
            RuntimeError: if the same task is already executing.
        """
        task = self.task_store.get_task(task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found")
        if not self._claim_task(task_id):
            raise RuntimeError(f"Task '{task_id}' is already running")

        def _run():
            now = datetime.now()
            try:
                logger.info(f"[Scheduler] Manually executing task: {task_id} - {task.get('name', '')}")
                job_run_id = (self.task_store.claim_occurrence(task_id, manual=True)
                              if hasattr(self.task_store, "claim_occurrence") else None)
                run_task = dict(task, job_run_id=job_run_id, manual_run=True)
                ok = self._execute_task(run_task)
                if job_run_id:
                    self.task_store.finish_occurrence(job_run_id, ok)
                if ok:
                    self.task_store.update_task(task_id, {
                        "last_run_at": now.isoformat(),
                        "last_manual_run_at": now.isoformat(),
                        "last_run_status": "completed", "last_error": None,
                    })
                    logger.info(f"[Scheduler] Manual execution completed: {task_id}")
                else:
                    from agent.scheduler.outcome import ExecutionOutcome
                    if isinstance(ok, ExecutionOutcome):
                        self.task_store.update_task(task_id, {"last_error": ok.error,
                            "last_run_status": ok.status, "last_error_at": now.isoformat(),
                            **({"enabled": False} if not ok.retryable else {})})
                    logger.warning(f"[Scheduler] Manual execution failed: {task_id}")
            finally:
                self._release_task(task_id)

        from common.runtime_identity import wrap
        threading.Thread(
            target=wrap(_run),
            daemon=True,
            name=f"scheduler-manual-{task_id}",
        ).start()

    def _claim_task(self, task_id: str) -> bool:
        """Prevent scheduled and manual runs of the same task from overlapping."""
        with self._execution_lock:
            if task_id in self._active_task_ids:
                return False
            self._active_task_ids.add(task_id)
            return True

    def _release_task(self, task_id: str) -> None:
        with self._execution_lock:
            self._active_task_ids.discard(task_id)
    
    def _is_task_due(self, task: dict, now: datetime) -> bool:
        """
        Check if a task is due to run
        
        Args:
            task: Task dictionary
            now: Current datetime
            
        Returns:
            True if task should run now
        """
        next_run_str = task.get("next_run_at")
        if not next_run_str:
            # Calculate initial next_run_at
            next_run = self._calculate_next_run(task, now)
            if next_run:
                self.task_store.update_task(task['id'], {
                    "next_run_at": next_run.isoformat()
                })
                return False
            return False
        
        try:
            next_run = _parse_naive_local(next_run_str)
            if task.get("retry_at") and now < _parse_naive_local(task["retry_at"]):
                return False

            schedule = task.get("schedule", {})
            if next_run <= now and task.get("catch_up") == "same_day" and schedule.get("type") == "cron":
                # Opt-in catch-up executes the latest occurrence today, never
                # replays all the days the app was closed. Other tasks retain
                # their existing ten-minute grace period.
                latest = iter_cron(schedule["expression"], now + timedelta(microseconds=1)).get_prev(datetime)
                if latest.date() != now.date():
                    next_run = self._calculate_next_run(task, now)
                    self.task_store.update_task(task['id'], {"next_run_at": next_run.isoformat()})
                    return False
                return True

            if next_run < now:
                time_diff = (now - next_run).total_seconds()
                schedule = task.get("schedule", {})
                schedule_type = schedule.get("type")

                # Catch-up window: fire if we're within 10 minutes of the
                # scheduled tick. Beyond that we'd rather skip than push a
                # stale daily report to the user.
                if time_diff <= 600:
                    return True

                logger.warning(
                    f"[Scheduler] Task {task['id']} is overdue by {int(time_diff)}s, "
                    f"skipping and scheduling next run"
                )

                if schedule_type == "once":
                    self.task_store.update_task(task['id'], {
                        "enabled": False, "next_run_at": None,
                        "expired_at": now.isoformat(),
                    })
                    logger.info(f"[Scheduler] One-time task {task['id']} expired")
                    return False

                next_next_run = self._calculate_next_run(task, now)
                if next_next_run:
                    self.task_store.update_task(task['id'], {
                        "next_run_at": next_next_run.isoformat()
                    })
                    logger.info(f"[Scheduler] Rescheduled task {task['id']} to {next_next_run}")
                return False

            return now >= next_run
        except Exception as e:
            logger.error(
                f"[Scheduler] Failed to evaluate due-state for task "
                f"{task.get('id')} (next_run_at={next_run_str!r}): {e}"
            )
            return False
    
    def _calculate_next_run(self, task: dict, from_time: datetime) -> Optional[datetime]:
        """
        Calculate next run time for a task
        
        Args:
            task: Task dictionary
            from_time: Calculate from this time
            
        Returns:
            Next run datetime or None for one-time tasks
        """
        schedule = task.get("schedule", {})
        schedule_type = schedule.get("type")
        
        if schedule_type == "cron":
            # Cron expression
            expression = schedule.get("expression")
            if not expression:
                return None
            
            try:
                cron = iter_cron(expression, from_time)
                return cron.get_next(datetime)
            except Exception as e:
                logger.error(f"[Scheduler] Invalid cron expression '{expression}': {e}")
                return None
        
        elif schedule_type == "interval":
            # Interval in seconds
            seconds = schedule.get("seconds", 0)
            if seconds <= 0:
                return None
            return from_time + timedelta(seconds=seconds)
        
        elif schedule_type == "once":
            # One-time task at specific time
            run_at_str = schedule.get("run_at")
            if not run_at_str:
                return None
            
            try:
                run_at = _parse_naive_local(run_at_str)
                if run_at > from_time:
                    return run_at
            except Exception as e:
                logger.error(
                    f"[Scheduler] Failed to parse once-task run_at "
                    f"{run_at_str!r}: {e}"
                )
            return None
        
        return None
    
    def _execute_task(self, task: dict) -> bool:
        """
        Execute a task.

        Returns True if delivery succeeded (caller should advance state),
        False if it failed (caller should keep next_run_at so the next
        loop iteration retries). Callback may return None for legacy
        behaviour, treated as success.
        """
        try:
            result = self.execute_callback(task)
            from agent.scheduler.outcome import ExecutionOutcome
            if isinstance(result, ExecutionOutcome):
                return result
            return False if result is False else True
        except Exception as e:
            logger.error(f"[Scheduler] Error executing task {task['id']}: {e}")
            self.task_store.update_task(task['id'], {
                "last_error": str(e),
                "last_error_at": datetime.now().isoformat()
            })
            return False
