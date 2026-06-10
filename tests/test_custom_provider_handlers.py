# encoding:utf-8
"""
Unit tests for the multi custom-provider management API (issue #2838, web UI).

Covers channel/web/web_channel.py::ModelsHandler:
  - _custom_provider_cards / _provider_overview expansion
  - _handle_set_custom_provider   (create / edit / rename / activate)
  - _handle_delete_custom_provider
  - _handle_set_active_custom_provider

These handlers are normally driven by the `web.py` framework, which isn't
available in the headless test environment, so we stub the `web` module before
import. The on-disk config read/write and the Bridge reset are patched to keep
the tests hermetic (no file I/O, no live bot routing).
"""
import json
import os
import sys
import types
import unittest

# Add project root to path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub the web.py framework so web_channel imports without the dependency.
if "web" not in sys.modules:
    _web_stub = types.ModuleType("web")
    _web_stub.header = lambda *a, **k: None
    _web_stub.data = lambda: b"{}"
    _web_stub.ctx = types.SimpleNamespace()
    sys.modules["web"] = _web_stub

import config as config_module
from config import Config
from channel.web.web_channel import ModelsHandler


def set_conf(d):
    """Install a fresh Config as the global config used by conf()."""
    config_module.config = Config(d)


class _HandlerHarness:
    """Test double around ModelsHandler that captures persisted config in
    memory instead of touching config.json, and no-ops the Bridge reset."""

    def __init__(self):
        self.handler = ModelsHandler.__new__(ModelsHandler)
        self._file_cfg = {}
        self.bridge_resets = 0
        # Patch the disk + bridge boundary on this instance.
        self.handler._read_file_config = lambda: dict(self._file_cfg)
        self.handler._write_file_config = self._capture_write
        self.handler._reset_bridge = self._capture_reset

    def _capture_write(self, data):
        self._file_cfg = dict(data)

    def _capture_reset(self):
        self.bridge_resets += 1

    def call(self, **payload):
        # Resolve the bound method by action for convenience.
        action = payload.get("action")
        method = {
            "set_custom_provider": self.handler._handle_set_custom_provider,
            "delete_custom_provider": self.handler._handle_delete_custom_provider,
            "set_active_custom_provider": self.handler._handle_set_active_custom_provider,
        }[action]
        return json.loads(method(payload))


class TestSetCustomProvider(unittest.TestCase):
    def setUp(self):
        set_conf({"bot_type": "custom", "custom_providers": [], "custom_active_provider": ""})
        self.h = _HandlerHarness()

    def test_create_first_provider_auto_activates(self):
        res = self.h.call(action="set_custom_provider", name="siliconflow",
                          api_base="https://api.siliconflow.cn/v1", api_key="sf-key")
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["created"])
        self.assertEqual(res["active"], "siliconflow")
        providers = config_module.conf().get("custom_providers")
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["name"], "siliconflow")
        self.assertEqual(config_module.conf().get("custom_active_provider"), "siliconflow")
        self.assertEqual(self.h.bridge_resets, 1)

    def test_create_requires_api_base(self):
        res = self.h.call(action="set_custom_provider", name="x", api_key="k")
        self.assertEqual(res["status"], "error")
        self.assertIn("api_base", res["message"])

    def test_create_requires_name(self):
        res = self.h.call(action="set_custom_provider", name="", api_base="https://x/v1")
        self.assertEqual(res["status"], "error")

    def test_second_provider_does_not_steal_active(self):
        self.h.call(action="set_custom_provider", name="a",
                    api_base="https://a/v1", api_key="ak")
        res = self.h.call(action="set_custom_provider", name="b",
                          api_base="https://b/v1", api_key="bk")
        self.assertTrue(res["created"])
        # First provider stays active unless make_active is requested.
        self.assertEqual(config_module.conf().get("custom_active_provider"), "a")

    def test_make_active_flag(self):
        self.h.call(action="set_custom_provider", name="a",
                    api_base="https://a/v1", api_key="ak")
        self.h.call(action="set_custom_provider", name="b",
                    api_base="https://b/v1", api_key="bk", make_active=True)
        self.assertEqual(config_module.conf().get("custom_active_provider"), "b")

    def test_duplicate_name_rejected(self):
        self.h.call(action="set_custom_provider", name="dup",
                    api_base="https://a/v1", api_key="ak")
        res = self.h.call(action="set_custom_provider", name="dup",
                          api_base="https://b/v1", api_key="bk")
        self.assertEqual(res["status"], "error")
        self.assertIn("already exists", res["message"])
        # The original entry must be untouched.
        providers = config_module.conf().get("custom_providers")
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["api_base"], "https://a/v1")

    def test_edit_keeps_key_when_omitted(self):
        self.h.call(action="set_custom_provider", name="a",
                    api_base="https://a/v1", api_key="secret")
        # Edit only the base; omit api_key.
        res = self.h.call(action="set_custom_provider", name="a",
                          original_name="a", api_base="https://a2/v1")
        self.assertEqual(res["status"], "success")
        self.assertFalse(res["created"])
        providers = config_module.conf().get("custom_providers")
        self.assertEqual(providers[0]["api_base"], "https://a2/v1")
        self.assertEqual(providers[0]["api_key"], "secret")  # preserved

    def test_rename_updates_active_pointer(self):
        self.h.call(action="set_custom_provider", name="old",
                    api_base="https://a/v1", api_key="ak")
        self.assertEqual(config_module.conf().get("custom_active_provider"), "old")
        res = self.h.call(action="set_custom_provider", name="new",
                          original_name="old", api_base="https://a/v1")
        self.assertEqual(res["status"], "success")
        self.assertEqual(config_module.conf().get("custom_active_provider"), "new")
        names = [p["name"] for p in config_module.conf().get("custom_providers")]
        self.assertEqual(names, ["new"])

    def test_edit_clears_model_when_empty(self):
        self.h.call(action="set_custom_provider", name="a",
                    api_base="https://a/v1", api_key="ak", model="m1")
        self.assertEqual(config_module.conf().get("custom_providers")[0]["model"], "m1")
        self.h.call(action="set_custom_provider", name="a", original_name="a",
                    api_base="https://a/v1", model="")
        self.assertNotIn("model", config_module.conf().get("custom_providers")[0])


class TestDeleteCustomProvider(unittest.TestCase):
    def setUp(self):
        set_conf({"bot_type": "custom", "custom_providers": [], "custom_active_provider": ""})
        self.h = _HandlerHarness()
        self.h.call(action="set_custom_provider", name="a", api_base="https://a/v1", api_key="ak")
        self.h.call(action="set_custom_provider", name="b", api_base="https://b/v1", api_key="bk")

    def test_delete_unknown(self):
        res = self.h.call(action="delete_custom_provider", name="ghost")
        self.assertEqual(res["status"], "error")

    def test_delete_non_active(self):
        res = self.h.call(action="delete_custom_provider", name="b")
        self.assertEqual(res["status"], "success")
        names = [p["name"] for p in config_module.conf().get("custom_providers")]
        self.assertEqual(names, ["a"])
        self.assertEqual(config_module.conf().get("custom_active_provider"), "a")

    def test_delete_active_falls_back_to_first_remaining(self):
        # 'a' is active (created first); deleting it should re-point to 'b'.
        self.assertEqual(config_module.conf().get("custom_active_provider"), "a")
        res = self.h.call(action="delete_custom_provider", name="a")
        self.assertEqual(res["status"], "success")
        self.assertEqual(config_module.conf().get("custom_active_provider"), "b")

    def test_delete_last_clears_active(self):
        self.h.call(action="delete_custom_provider", name="a")
        self.h.call(action="delete_custom_provider", name="b")
        self.assertEqual(config_module.conf().get("custom_providers"), [])
        self.assertEqual(config_module.conf().get("custom_active_provider"), "")


class TestSetActiveCustomProvider(unittest.TestCase):
    def setUp(self):
        set_conf({"bot_type": "custom", "custom_providers": [], "custom_active_provider": ""})
        self.h = _HandlerHarness()
        self.h.call(action="set_custom_provider", name="a", api_base="https://a/v1", api_key="ak")
        self.h.call(action="set_custom_provider", name="b", api_base="https://b/v1", api_key="bk")

    def test_set_active_valid(self):
        res = self.h.call(action="set_active_custom_provider", name="b")
        self.assertEqual(res["status"], "success")
        self.assertEqual(config_module.conf().get("custom_active_provider"), "b")

    def test_set_active_unknown(self):
        res = self.h.call(action="set_active_custom_provider", name="ghost")
        self.assertEqual(res["status"], "error")
        self.assertEqual(config_module.conf().get("custom_active_provider"), "a")


class TestProviderOverviewExpansion(unittest.TestCase):
    """_provider_overview / _custom_provider_cards should expand the list."""

    def test_no_custom_providers_keeps_single_card(self):
        set_conf({"bot_type": "custom", "custom_providers": [], "custom_active_provider": ""})
        cards = ModelsHandler._custom_provider_cards(config_module.conf())
        self.assertEqual(cards, [])
        overview = ModelsHandler._provider_overview()
        custom_cards = [c for c in overview if c.get("id") == "custom"]
        # Legacy single custom card remains present.
        self.assertEqual(len(custom_cards), 1)
        self.assertTrue(custom_cards[0].get("is_custom"))

    def test_multi_providers_expand_into_cards(self):
        set_conf({
            "bot_type": "custom",
            "custom_active_provider": "b",
            "custom_providers": [
                {"name": "a", "api_key": "ak", "api_base": "https://a/v1"},
                {"name": "b", "api_key": "bk", "api_base": "https://b/v1", "model": "m"},
            ],
        })
        overview = ModelsHandler._provider_overview()
        custom_cards = [c for c in overview if c.get("is_custom")]
        self.assertEqual(len(custom_cards), 2)
        by_name = {c["custom_name"]: c for c in custom_cards}
        self.assertEqual(by_name["a"]["id"], "custom:a")
        self.assertFalse(by_name["a"]["active"])
        self.assertTrue(by_name["b"]["active"])
        self.assertEqual(by_name["b"]["model"], "m")
        # No single legacy "custom" card when expanded.
        self.assertFalse(any(c.get("id") == "custom" for c in overview))

    def test_active_defaults_to_first_when_unset(self):
        set_conf({
            "bot_type": "custom",
            "custom_active_provider": "",
            "custom_providers": [
                {"name": "a", "api_key": "ak", "api_base": "https://a/v1"},
                {"name": "b", "api_key": "bk", "api_base": "https://b/v1"},
            ],
        })
        cards = ModelsHandler._custom_provider_cards(config_module.conf())
        by_name = {c["custom_name"]: c for c in cards}
        self.assertTrue(by_name["a"]["active"])
        self.assertFalse(by_name["b"]["active"])


if __name__ == "__main__":
    unittest.main()
