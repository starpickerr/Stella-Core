"""Generate the daily briefing at 08:00 local time, with wake/start catch-up."""
from datetime import datetime, timedelta
import threading

from agent.briefing.pipeline import BriefingPipeline
from agent.briefing.service import BriefingService, briefing_id_for
from agent.briefing.settings import email_sources, mailbox_path, public_mailboxes
from agent.briefing.generator import AgentBriefingGenerator
from common.log import logger


class BriefingScheduler:
    def __init__(self, service=None, clock=None, pipeline_factory=None, configured=None):
        self.service = service or BriefingService()
        self.clock = clock or (lambda: datetime.now().astimezone())
        # Resolve the user scope before launching the worker.
        settings_path = mailbox_path()
        self.configured = configured or (lambda: public_mailboxes(settings_path)["configured"])
        self.pipeline_factory = pipeline_factory or (lambda: BriefingPipeline(
            self.service, email_sources(settings_path), clock=self.clock,
            generator=AgentBriefingGenerator(cancel_event=self._stop)))
        self._stop = threading.Event()
        self._thread = None
        self._retry_at = None

    def tick(self):
        now = self.clock()
        if now.hour < 8 or (self._retry_at and now < self._retry_at):
            return
        day = now.date().isoformat()
        existing = self.service.store.get_briefing(briefing_id_for(day, "morning"))
        if existing and existing.generated_at:
            return
        if not self.configured():
            return
        # Failed attempts retry without creating another daily document.
        self._retry_at = now + timedelta(minutes=5)
        result = self.pipeline_factory().run(briefing_date=day, operation="create", trigger="scheduled")
        if result["briefing"].generated_at:
            self._retry_at = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="briefing-scheduler", daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("[BriefingScheduler] Daily briefing failed")
            now = self.clock()
            due = now.replace(hour=8, minute=0, second=0, microsecond=0)
            delay = min(30, max(0.1, (due - now).total_seconds())) if now < due else 30
            self._stop.wait(delay)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
