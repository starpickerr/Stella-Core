import importlib.util
import sys
from pathlib import Path
import pytest

root = Path(__file__).parent
name = 'stella_elearning_test_support'
if name not in sys.modules:
    spec = importlib.util.spec_from_file_location(name, root / 'support.py', submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
settings = sys.modules[name].settings

@pytest.fixture(autouse=True)
def config_path(tmp_path, monkeypatch):
    path = tmp_path / 'elearning/elearning.json'
    monkeypatch.setattr(settings, 'settings_path', lambda: path)
    return path

@pytest.fixture
def security_audit_path(config_path):
    return settings.store().audit_path
