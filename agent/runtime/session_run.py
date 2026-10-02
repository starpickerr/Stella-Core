"""Serialize turns which share a mutable Agent session."""

from __future__ import annotations

import threading
from contextlib import contextmanager


class SessionRun:
    def __init__(self):
        self._guard = threading.Lock()
        self._locks = {}

    @contextmanager
    def enter(self, user_id, agent_id, session_id):
        # A default Agent is also mutable, even without a session id.
        key = (user_id, agent_id, session_id)
        with self._guard:
            lock, users = self._locks.get(key, (threading.Lock(), 0))
            self._locks[key] = (lock, users + 1)
        try:
            with lock:
                yield
        finally:
            with self._guard:
                _, users = self._locks[key]
                if users == 1:
                    del self._locks[key]
                else:
                    self._locks[key] = (lock, users - 1)
