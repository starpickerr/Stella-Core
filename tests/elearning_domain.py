"""Core integration tests use the independent MCP Server's test adapters and real domain."""
import importlib.util
import sys
from pathlib import Path
from importlib import import_module

from tests.mcp_checkout import require_checkout

root = Path(__file__).resolve().parents[2] / 'MCP/fudan-elearning-mcp/tests/domain'
require_checkout(root / 'support.py', 'eLearning MCP test support is not in this checkout')
name = 'stella_elearning_test_support'
if name not in sys.modules:
    spec = importlib.util.spec_from_file_location(name, root / 'support.py', submodule_search_locations=[str(root)])
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    spec.loader.exec_module(package)
support = sys.modules[name]
fakes = import_module(name + '.fakes')
settings, Canvas, ElearningSource, DomainServiceCall = support.settings, support.Canvas, support.ElearningSource, support.ServiceCall
LoginRequired, SyncCancelled, SyncError = support.LoginRequired, support.SyncCancelled, support.SyncError
FakeCanvas, config = fakes.FakeCanvas, fakes.config
