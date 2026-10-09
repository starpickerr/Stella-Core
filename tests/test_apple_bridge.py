import sys
import platform
import subprocess
import threading
from pathlib import Path

import pytest

from agent.calendar.apple_bridge import AppleCalendarBridge, BridgeError


@pytest.mark.skipif(platform.system() != 'Darwin', reason='Swift compiler requires macOS')
def test_native_marker_lookup_distinguishes_recurring_occurrences(tmp_path):
    root = Path(__file__).parents[1] / 'native/apple-calendar'
    binary = tmp_path / 'occurrence-identity'
    subprocess.run(['/usr/bin/swiftc', '-framework', 'EventKit',
                    str(root / 'OccurrenceIdentity.swift'), str(root / 'ReminderFields.swift'),
                    str(root / 'tests/main.swift'), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert 'Occurrence identity passed' in result.stdout


def helper(tmp_path, body):
    path = tmp_path / "bridge"
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o755)
    return path


def test_bridge_reports_unsupported_platform_without_launching(tmp_path):
    bridge = AppleCalendarBridge(helper_path=tmp_path / "missing", platform="linux")
    assert bridge.call("status") == {"supported": False, "authorization": "unsupported"}
    with pytest.raises(BridgeError, match="not supported"):
        bridge.call("calendars")
    assert bridge.call("reminder_status") == {"supported": False, "authorization": "unsupported"}
    with pytest.raises(BridgeError, match="not supported"):
        bridge.call("reminders", list_ids=["a"])


def test_bridge_requires_installed_helper(tmp_path):
    bridge = AppleCalendarBridge(helper_path=tmp_path / "missing", platform="darwin")
    assert bridge.call("status") == {"supported": False, "authorization": "helper_missing"}
    with pytest.raises(BridgeError, match="not installed"):
        bridge.call("events", calendar_ids=["a"])
    assert bridge.call("reminder_status") == {"supported": False, "authorization": "helper_missing"}


def test_bridge_uses_json_stdin_and_rejects_malformed_output(tmp_path):
    valid = helper(tmp_path, "import json,sys\nrequest=json.loads(sys.stdin.readline())\nprint(json.dumps({'ok':True,'echo':request}))\n")
    bridge = AppleCalendarBridge(helper_path=valid, platform="darwin")
    assert bridge.call("events", calendar_ids=["a; touch /tmp/nope"])["echo"] == {
        "op": "events", "calendar_ids": ["a; touch /tmp/nope"]}
    assert bridge.call("lookup", calendar_id="a", event_id="e")["echo"]["op"] == "lookup"
    for op in ("reminder_status", "reminder_request_access", "reminder_lists", "reminders",
               "reminder_lookup", "reminder_upsert", "reminder_delete"):
        assert bridge.call(op, list_id="test-list")["echo"]["op"] == op
    bad = helper(tmp_path, "print('private calendar contents')\n")
    with pytest.raises(BridgeError, match="invalid response"):
        AppleCalendarBridge(helper_path=bad, platform="darwin").call("calendars")


def test_bridge_times_out_without_logging_request(tmp_path):
    slow = helper(tmp_path, "import time\ntime.sleep(2)\n")
    with pytest.raises(BridgeError, match="timed out"):
        AppleCalendarBridge(helper_path=slow, platform="darwin", timeout=0.05).call("events")


def test_permission_prompt_has_longer_timeout_than_regular_calls(tmp_path, monkeypatch):
    valid = helper(tmp_path, "print('{\"ok\":true,\"authorization\":\"denied\"}')\n")
    from agent.calendar import apple_bridge
    original = apple_bridge.subprocess.run
    timeouts = []

    def run(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return original(*args, **kwargs)

    monkeypatch.setattr(apple_bridge.subprocess, "run", run)
    bridge = AppleCalendarBridge(helper_path=valid, platform="darwin", timeout=2)
    bridge.call("status")
    bridge.call("request_access")
    bridge.call("reminder_request_access")
    assert timeouts[0] == 2
    assert timeouts[1] >= 120
    assert timeouts[2] >= 120


def test_reminder_watch_uses_same_process_protocol(tmp_path):
    operation = tmp_path / "operation"
    script = helper(tmp_path, "import json,sys,time\n"
                    f"open({str(operation)!r},'w').write(json.loads(sys.stdin.readline())['op'])\n"
                    "print('{\"changed\":true}',flush=True)\ntime.sleep(10)\n")
    stop = threading.Event()
    changes = []
    bridge = AppleCalendarBridge(helper_path=script, platform="darwin")
    bridge.watch(lambda: (changes.append(True), stop.set()), stop, kind="reminder")
    assert changes == [True]
    assert operation.read_text() == "reminder_watch"


@pytest.mark.skipif(platform.system() != 'Darwin', reason='Swift compiler requires macOS')
def test_native_reminder_date_fields(tmp_path):
    root = Path(__file__).parents[1] / 'native/apple-calendar'
    binary = tmp_path / 'reminder-fields'
    subprocess.run(['/usr/bin/swiftc', str(root / 'ReminderFields.swift'),
                    str(root / 'tests/reminders/main.swift'), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert 'Reminder fields passed' in result.stdout
