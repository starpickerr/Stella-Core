"""One polling and change-watch lifecycle shared by EventKit sync adapters."""

from __future__ import annotations

import threading

from common.log import logger


def report_sync_error(kind, phase, error):
    """Keep a caught EventKit failure visible in both the UI and desktop log."""
    logger.exception("[AppleSync] %s failed during %s", kind, phase)
    return f"{phase}失败：{error or type(error).__name__}"


class EventKitAutoRunner:
    def __init__(self, bridge, connected, sync, *, kind="calendar", interval=300):
        self.bridge = bridge
        self.connected = connected
        self.sync = sync
        self.kind = kind
        self.interval = interval
        self.stop_event = threading.Event()
        self.started = False

    def start(self):
        if self.started:
            return
        self.started = True

        def poll():
            while not self.stop_event.is_set():
                if self.connected():
                    try:
                        self.sync()
                    except Exception:
                        logger.exception("EventKit %s poll failed", self.kind)
                self.stop_event.wait(self.interval)

        def watch():
            while not self.stop_event.is_set():
                if self.connected():
                    try:
                        if self.kind == "reminder":
                            self.bridge.watch(self.sync, self.stop_event, kind="reminder")
                        else:
                            self.bridge.watch(self.sync, self.stop_event)
                    except Exception:
                        logger.exception("EventKit %s watch failed", self.kind)
                self.stop_event.wait(self.interval)

        threading.Thread(target=poll, name=f"apple-{self.kind}-poll", daemon=True).start()
        threading.Thread(target=watch, name=f"apple-{self.kind}-watch", daemon=True).start()

    def stop(self):
        self.stop_event.set()
        self.started = False
