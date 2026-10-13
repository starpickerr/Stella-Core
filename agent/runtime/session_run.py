"""FIFO single execution for turns which share a mutable Agent session."""
from __future__ import annotations
import threading
from contextlib import contextmanager


class SessionRun:
    def __init__(self):
        self._condition = threading.Condition()
        self._queues = {}

    def reserve(self, user_id, agent_id, session_id):
        key = (user_id, agent_id, session_id)
        ticket = (key, object())
        with self._condition:
            self._queues.setdefault(key, []).append(ticket)
        return ticket

    def discard(self, ticket):
        with self._condition:
            queue = self._queues.get(ticket[0], [])
            if ticket in queue:
                queue.remove(ticket)
            if not queue:
                self._queues.pop(ticket[0], None)
            self._condition.notify_all()

    @contextmanager
    def enter(self, user_id, agent_id, session_id, *, ticket=None):
        ticket = ticket or self.reserve(user_id, agent_id, session_id)
        try:
            with self._condition:
                self._condition.wait_for(lambda: self._queues.get(ticket[0], [None])[0] is ticket)
            yield
        finally:
            self.discard(ticket)
