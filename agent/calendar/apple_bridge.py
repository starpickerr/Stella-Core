"""Small, fail-closed JSON process boundary for the macOS EventKit helper."""

from __future__ import annotations

import json
import select
import subprocess
import sys
from pathlib import Path


class BridgeError(RuntimeError):
    pass


def _default_helper():
    if getattr(sys, "frozen", False):
        # Electron resources/backend/stella-backend/stella-backend -> resources/apple-calendar/...
        return Path(sys.executable).resolve().parents[2] / "apple-calendar" / "StellaCalendarBridge"
    return Path(__file__).resolve().parents[2] / "native" / "apple-calendar" / ".build" / "StellaCalendarBridge"


class AppleCalendarBridge:
    def __init__(self, helper_path=None, platform=None, timeout=30):
        self.helper_path = Path(helper_path) if helper_path is not None else _default_helper()
        self.platform = platform or sys.platform
        self.timeout = timeout

    def call(self, op, **payload):
        if self.platform != "darwin":
            if op == "status":
                return {"supported": False, "authorization": "unsupported"}
            raise BridgeError("EventKit is not supported on this platform")
        if not self.helper_path.is_file():
            if op == "status":
                return {"supported": False, "authorization": "helper_missing"}
            raise BridgeError("EventKit helper is not installed")
        if op not in {"status", "request_access", "calendars", "events", "upsert", "delete"}:
            raise BridgeError("unknown EventKit operation")
        request = json.dumps({"op": op, **payload}, ensure_ascii=False) + "\n"
        try:
            result = subprocess.run([str(self.helper_path)], input=request, text=True,
                                    capture_output=True, timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise BridgeError("EventKit helper timed out") from exc
        except OSError as exc:
            raise BridgeError("EventKit helper could not start") from exc
        try:
            response = json.loads(result.stdout.strip())
        except (json.JSONDecodeError, ValueError) as exc:
            raise BridgeError("EventKit helper returned an invalid response") from exc
        if not isinstance(response, dict) or response.get("ok") is not True:
            if isinstance(response, dict) and response.get("ok") is False:
                raise BridgeError(str(response.get("error") or "EventKit operation failed"))
            raise BridgeError("EventKit helper returned an invalid response")
        return {key: value for key, value in response.items() if key != "ok"}

    def watch(self, on_change, stop_event=None):
        """Block until stopped, forwarding EKEventStoreChanged notifications."""
        if self.platform != "darwin" or not self.helper_path.is_file():
            return
        process = subprocess.Popen([str(self.helper_path)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                   bufsize=1)
        try:
            process.stdin.write('{"op":"watch"}\n')
            process.stdin.flush()
            while process.poll() is None and (stop_event is None or not stop_event.is_set()):
                ready, _, _ = select.select([process.stdout], [], [], 1)
                if ready:
                    line = process.stdout.readline()
                    if not line:
                        break
                    try:
                        if json.loads(line).get("changed") is True:
                            on_change()
                    except (ValueError, AttributeError):
                        continue
        finally:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
