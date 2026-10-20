# encoding:utf-8
"""
Regression tests for `agent_workspace` not being honored everywhere - see
`_default_workspace()` / `set_global_memory_config()` (agent/memory/config.py)
and `AgentInitializer._setup_memory_system` for the underlying contract each
test here pins.
"""
import os
import sys
import shutil
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import conf, load_config


class TestMemoryGlobalConfigSync(unittest.TestCase):
    def setUp(self):
        load_config()
        self.tmp = tempfile.mkdtemp()
        self._real_home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp
        self.workspace = os.path.join(self.tmp, "custom_workspace")
        os.makedirs(self.workspace)

        self._orig_agent_workspace = conf().get("agent_workspace")
        conf()["agent_workspace"] = self.workspace

        # Drop cached configs and stores so earlier tests/imports in the same
        # run can't leave a stale ~/stella-pointed one behind.
        from agent.memory import clear_conversation_store_cache
        clear_conversation_store_cache()

    def tearDown(self):
        from agent.memory import clear_conversation_store_cache
        from agent.registry import set_agent_registry
        clear_conversation_store_cache()

        if self._orig_agent_workspace is None:
            conf().pop("agent_workspace", None)
        else:
            conf()["agent_workspace"] = self._orig_agent_workspace
        set_agent_registry(None)

        if self._real_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._real_home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_setup_without_optional_plugins_does_not_initialize_domain_implementations(self):
        from bridge.agent_initializer import AgentInitializer
        from unittest.mock import patch
        initializer = AgentInitializer(bridge=None, agent_bridge=None)
        with patch('core.services.memory_facade.plugin_available', return_value=False):
            memory, tools = initializer._setup_memory_system(self.workspace)
        self.assertFalse(memory.is_available())
        self.assertFalse(any(tool.is_available() for tool in tools))
        self.assertFalse(os.path.exists(os.path.join(self.workspace, 'MEMORY.md')))

    def test_conversation_store_shares_the_configured_workspace(self):
        from bridge.agent_initializer import AgentInitializer
        from agent.memory import get_conversation_store

        initializer = AgentInitializer(bridge=None, agent_bridge=None)
        initializer._setup_memory_system(self.workspace, session_id=None)

        store = get_conversation_store()
        self.assertTrue(
            os.path.realpath(store._db_path).startswith(os.path.realpath(self.workspace)),
            f"ConversationStore db_path {store._db_path} should live under "
            f"the configured workspace {self.workspace}, not ~/stella",
        )

    def test_conversation_store_honors_workspace_without_any_priming(self):
        """
        The real failure mode: GET /api/sessions calls
        get_conversation_store() directly on web-console page load, before
        any chat message has ever run AgentInitializer. Nothing primes the
        singleton on that path, so the lazily built default itself has to
        resolve agent_workspace.
        """
        from agent.memory import get_conversation_store

        store = get_conversation_store()
        # realpath on both sides: the workspace root is canonicalised so that
        # prefix-based containment checks are sound, and on macOS the temp dir
        # reached through /var is really /private/var.
        self.assertTrue(
            os.path.realpath(store._db_path).startswith(os.path.realpath(self.workspace)),
            f"ConversationStore db_path {store._db_path} should live under "
            f"the configured workspace {self.workspace} even when accessed "
            f"before the first agent init, not ~/stella",
        )

    def test_falls_back_to_stella_when_agent_workspace_is_unset(self):
        """
        Resolving from config must not change the default for anyone who
        never set agent_workspace.
        """
        from common.state_dir import state_root_str
        from agent.registry import set_agent_registry
        from common.utils import expand_path

        conf().pop("agent_workspace", None)
        # Runtime routing caches the registry derived from config. Rebuild it
        # after changing the config in this test to exercise the unset case.
        set_agent_registry(None)
        self.assertEqual(
            os.path.realpath(state_root_str()),
            os.path.realpath(expand_path("~/stella")),
            "an unset agent_workspace should still resolve to the ~/stella default",
        )


class TestLegacyWorkspaceWarning(unittest.TestCase):
    """
    `_warn_if_legacy_workspace_data_exists` is a read-only safety net: it
    never moves or touches data, only logs when the hardcoded `~/stella`
    default holds data that the configured workspace doesn't. HOME is
    redirected to an isolated temp dir so this never touches the real
    `~/stella` on the machine running the test.
    """

    def setUp(self):
        load_config()
        self.tmp = tempfile.mkdtemp()
        self._real_home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp

        self.legacy_root = os.path.join(self.tmp, "stella")
        self.new_workspace = os.path.join(self.tmp, "custom_workspace")
        os.makedirs(self.new_workspace)

        self._orig_agent_workspace = conf().get("agent_workspace")

    def tearDown(self):
        if self._orig_agent_workspace is None:
            conf().pop("agent_workspace", None)
        else:
            conf()["agent_workspace"] = self._orig_agent_workspace

        if self._real_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._real_home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_legacy_db(self):
        legacy_db_dir = os.path.join(self.legacy_root, "memory", "long-term")
        os.makedirs(legacy_db_dir, exist_ok=True)
        with open(os.path.join(legacy_db_dir, "index.db"), "wb") as f:
            f.write(b"")

    def _check(self, workspace_root):
        import app

        conf()["agent_workspace"] = workspace_root
        app._warn_if_legacy_workspace_data_exists()

    def test_warns_when_legacy_data_exists_at_a_different_path(self):
        self._write_legacy_db()
        with self.assertLogs("log", level="WARNING") as cm:
            self._check(self.new_workspace)

        self.assertTrue(
            any(self.legacy_root in msg and self.new_workspace in msg for msg in cm.output),
            f"Expected a warning naming both {self.legacy_root} and "
            f"{self.new_workspace}, got: {cm.output}",
        )

    def test_warns_on_leftover_data_thats_not_the_memory_db(self):
        """
        The warning message promises to catch "session history, memory, or
        skills" - not just the long-term memory DB. A skills-only leftover
        (no memory/long-term/index.db at all) must still trigger it.
        """
        os.makedirs(os.path.join(self.legacy_root, "skills", "some-skill"))
        with self.assertLogs("log", level="WARNING") as cm:
            self._check(self.new_workspace)

        self.assertTrue(
            any(self.legacy_root in msg for msg in cm.output),
            f"Expected a warning naming {self.legacy_root}, got: {cm.output}",
        )

    def test_no_warning_when_workspace_is_already_the_legacy_default(self):
        import logging

        self._write_legacy_db()
        logger = logging.getLogger("log")
        with unittest.mock.patch.object(logger, "warning") as mock_warning:
            self._check(self.legacy_root)
        mock_warning.assert_not_called()

    def test_no_warning_when_only_hidden_files_are_left_over(self):
        """
        A stray .DS_Store (or any dotfile the OS drops in) isn't user data,
        and would otherwise warn on every single startup.
        """
        import logging

        os.makedirs(self.legacy_root)
        with open(os.path.join(self.legacy_root, ".DS_Store"), "wb") as f:
            f.write(b"")

        logger = logging.getLogger("log")
        with unittest.mock.patch.object(logger, "warning") as mock_warning:
            self._check(self.new_workspace)
        mock_warning.assert_not_called()

    def test_no_warning_when_paths_differ_only_by_case(self):
        """
        ~/stella and ~/STELLA are the same directory on a case-insensitive
        filesystem (default on Windows and macOS). Uses real files, not
        mocked os.path calls - a mocked version previously forced
        Windows-like case-folding on every OS, masking a real bug where
        this comparison failed on macOS/Linux. Skips on a case-sensitive
        filesystem.
        """
        import logging

        self._write_legacy_db()
        differently_cased_workspace = self.legacy_root.upper()
        is_case_insensitive = os.path.isdir(differently_cased_workspace) and os.path.samefile(
            self.legacy_root, differently_cased_workspace
        )
        if not is_case_insensitive:
            self.skipTest("filesystem is case-sensitive; premise doesn't apply")

        logger = logging.getLogger("log")
        with unittest.mock.patch.object(logger, "warning") as mock_warning:
            self._check(differently_cased_workspace)
        mock_warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
