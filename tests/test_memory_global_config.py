# encoding:utf-8
"""
Regression tests for `agent_workspace` not being honored everywhere - see
`set_global_memory_config()` (agent/memory/config.py) and its two call
sites, `AgentInitializer._setup_memory_system` and
`app._init_global_memory_config`, for the underlying contract each test
here pins.
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

        # Reset the process-wide singletons so earlier tests/imports in the
        # same run can't leave a stale ~/cow-pointed config behind.
        import agent.memory.config as memory_config_module
        import agent.memory.conversation_store as conversation_store_module
        self._orig_global_memory_config = memory_config_module._global_memory_config
        self._orig_store_instance = conversation_store_module._store_instance
        memory_config_module._global_memory_config = None
        conversation_store_module._store_instance = None

    def tearDown(self):
        import agent.memory.config as memory_config_module
        import agent.memory.conversation_store as conversation_store_module
        memory_config_module._global_memory_config = self._orig_global_memory_config
        conversation_store_module._store_instance = self._orig_store_instance

        if self._orig_agent_workspace is None:
            conf().pop("agent_workspace", None)
        else:
            conf()["agent_workspace"] = self._orig_agent_workspace

        if self._real_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._real_home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_setup_memory_system_syncs_global_config(self):
        from bridge.agent_initializer import AgentInitializer
        from agent.memory.config import get_default_memory_config

        initializer = AgentInitializer(bridge=None, agent_bridge=None)
        initializer._setup_memory_system(self.workspace, session_id=None)

        global_workspace = str(get_default_memory_config().get_workspace())
        self.assertEqual(
            global_workspace,
            self.workspace,
            "get_default_memory_config() should reflect the configured "
            "agent_workspace after agent init, not the hardcoded ~/cow default",
        )

    def test_conversation_store_shares_the_configured_workspace(self):
        from bridge.agent_initializer import AgentInitializer
        from agent.memory import get_conversation_store

        initializer = AgentInitializer(bridge=None, agent_bridge=None)
        initializer._setup_memory_system(self.workspace, session_id=None)

        store = get_conversation_store()
        self.assertTrue(
            str(store._db_path).startswith(self.workspace),
            f"ConversationStore db_path {store._db_path} should live under "
            f"the configured workspace {self.workspace}, not ~/cow",
        )

    def test_app_startup_closes_the_early_access_race(self):
        """
        Simulates the real failure mode: GET /api/sessions calls
        get_conversation_store() directly on page load, before any chat
        message has ever run AgentInitializer.
        """
        import app
        from agent.memory import get_conversation_store

        app._init_global_memory_config()

        # No AgentInitializer / _setup_memory_system call happens here -
        # this is the early race, exercised directly.
        store = get_conversation_store()
        self.assertTrue(
            str(store._db_path).startswith(self.workspace),
            f"ConversationStore db_path {store._db_path} should live under "
            f"the configured workspace {self.workspace} even when accessed "
            f"before the first agent init, not ~/cow",
        )

    def test_cold_conversation_store_defaults_to_cow_without_priming(self):
        """
        The fix's correctness rests entirely on _init_global_memory_config()
        running before anything can call get_conversation_store() /
        get_default_memory_config() for the first time - an ordering
        contract enforced only by statement order in app.run(), not by any
        type system or guard. This pins what actually happens if that
        contract is ever violated (e.g. a future refactor reorders run()),
        so a regression here fails loudly instead of quietly reappearing.
        """
        from agent.memory import get_conversation_store
        from common.utils import expand_path

        # No _init_global_memory_config() call - this is the unguarded path.
        store = get_conversation_store()
        legacy_root = expand_path("~/cow")
        self.assertTrue(
            str(store._db_path).startswith(legacy_root),
            f"without priming, get_conversation_store() is expected to fall "
            f"back to the hardcoded {legacy_root} default even though "
            f"agent_workspace is set to {self.workspace} - this documents "
            f"the failure mode the ordering in app.run() must prevent",
        )


class TestLegacyWorkspaceWarning(unittest.TestCase):
    """
    `_warn_if_legacy_workspace_data_exists` is a read-only safety net: it
    never moves or touches data, only logs when the hardcoded `~/cow`
    default holds data that the configured workspace doesn't. HOME is
    redirected to an isolated temp dir so this never touches the real
    `~/cow` on the machine running the test.
    """

    def setUp(self):
        load_config()
        self.tmp = tempfile.mkdtemp()
        self._real_home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp

        self.legacy_root = os.path.join(self.tmp, "cow")
        self.new_workspace = os.path.join(self.tmp, "custom_workspace")
        os.makedirs(self.new_workspace)

    def tearDown(self):
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

    def test_warns_when_legacy_data_exists_at_a_different_path(self):
        import app

        self._write_legacy_db()
        with self.assertLogs("log", level="WARNING") as cm:
            app._warn_if_legacy_workspace_data_exists(self.new_workspace)

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
        import app

        os.makedirs(os.path.join(self.legacy_root, "skills", "some-skill"))
        with self.assertLogs("log", level="WARNING") as cm:
            app._warn_if_legacy_workspace_data_exists(self.new_workspace)

        self.assertTrue(
            any(self.legacy_root in msg for msg in cm.output),
            f"Expected a warning naming {self.legacy_root}, got: {cm.output}",
        )

    def test_no_warning_when_workspace_is_already_the_legacy_default(self):
        import app
        import logging

        self._write_legacy_db()
        logger = logging.getLogger("log")
        with unittest.mock.patch.object(logger, "warning") as mock_warning:
            app._warn_if_legacy_workspace_data_exists(self.legacy_root)
        mock_warning.assert_not_called()

    def test_no_warning_when_paths_differ_only_by_case(self):
        """
        ~/cow and ~/COW are the same directory on a case-insensitive
        filesystem (default on Windows and macOS). Uses real files, not
        mocked os.path calls - a mocked version previously forced
        Windows-like case-folding on every OS, masking a real bug where
        this comparison failed on macOS/Linux. Skips on a case-sensitive
        filesystem.
        """
        import app
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
            app._warn_if_legacy_workspace_data_exists(differently_cased_workspace)
        mock_warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
