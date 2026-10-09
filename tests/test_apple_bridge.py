import sys

import pytest

from agent.calendar.apple_bridge import AppleCalendarBridge, BridgeError


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


def test_bridge_requires_installed_helper(tmp_path):
    bridge = AppleCalendarBridge(helper_path=tmp_path / "missing", platform="darwin")
    assert bridge.call("status") == {"supported": False, "authorization": "helper_missing"}
    with pytest.raises(BridgeError, match="not installed"):
        bridge.call("events", calendar_ids=["a"])


def test_bridge_uses_json_stdin_and_rejects_malformed_output(tmp_path):
    valid = helper(tmp_path, "import json,sys\nrequest=json.loads(sys.stdin.readline())\nprint(json.dumps({'ok':True,'echo':request}))\n")
    bridge = AppleCalendarBridge(helper_path=valid, platform="darwin")
    assert bridge.call("events", calendar_ids=["a; touch /tmp/nope"])["echo"] == {
        "op": "events", "calendar_ids": ["a; touch /tmp/nope"]}
    assert bridge.call("lookup", calendar_id="a", event_id="e")["echo"]["op"] == "lookup"
    bad = helper(tmp_path, "print('private calendar contents')\n")
    with pytest.raises(BridgeError, match="invalid response"):
        AppleCalendarBridge(helper_path=bad, platform="darwin").call("calendars")


def test_bridge_times_out_without_logging_request(tmp_path):
    slow = helper(tmp_path, "import time\ntime.sleep(2)\n")
    with pytest.raises(BridgeError, match="timed out"):
        AppleCalendarBridge(helper_path=slow, platform="darwin", timeout=0.05).call("events")
