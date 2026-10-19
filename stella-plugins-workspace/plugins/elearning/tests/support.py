"""Test adapters over the real plugin store, service and RPC handler.

Only the retired test calling conventions are translated; all validation,
fetching, cancellation, authorization and downloads execute plugin code.
"""
import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

NAME = 'stella_elearning_domain_tests'
root = Path(__file__).resolve().parents[1] / 'backend/domain'
if NAME not in sys.modules:
    spec = importlib.util.spec_from_file_location(NAME, root / '__init__.py', submodule_search_locations=[str(root)])
    package = importlib.util.module_from_spec(spec)
    sys.modules[NAME] = package
    spec.loader.exec_module(package)
store_module = importlib.import_module(NAME + '.store')
service_module = importlib.import_module(NAME + '.service')
client = importlib.import_module(NAME + '.client')
source = importlib.import_module(NAME + '.source')
file_sync = importlib.import_module(NAME + '.file_sync')
errors = importlib.import_module(NAME + '.errors')
LoginRequired, SyncCancelled, SyncError = errors.LoginRequired, errors.SyncCancelled, errors.SyncError
ElearningStore, ElearningService = store_module.ElearningStore, service_module.ElearningService


class Settings:
    DEFAULTS = store_module.DEFAULTS
    def settings_path(self):
        raise RuntimeError('test must bind an isolated settings path')
    def store(self):
        return ElearningStore(self.settings_path().parent)
    def __getattr__(self, name):
        return getattr(self.store(), name)
    def check_connection(self, payload):
        return ElearningService(self.store().root).test_connection(payload)
    def elearning_sources(self):
        cfg = self.store().load_settings()
        return [ElearningSource(cfg, briefing_only=True)] if cfg['enabled'] else []


settings = Settings()


def Canvas(config, *args, **kwargs):
    return client.Canvas(config, settings.store(), *args, **kwargs)


def ElearningSource(config, **kwargs):
    return source.ElearningSource(config, settings.store(), **kwargs)


def sync_files(client, config, rows, **kwargs):
    return file_sync.sync_files(client, config, rows, settings.store(), **kwargs)


# Load the actual packaged entry with its own domain module identity. Restore
# generic import names afterwards so collecting another plugin is independent.
saved = {key: value for key, value in sys.modules.items() if key == 'domain' or key.startswith('domain.')}
for key in list(saved):
    del sys.modules[key]
for key, value in list(sys.modules.items()):
    if key == NAME or key.startswith(NAME + '.'):
        sys.modules['domain' + key[len(NAME):]] = value
saved_path = list(sys.path)
try:
    spec = importlib.util.spec_from_file_location('elearning_test_rpc_entry', root.parent / 'main.py')
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
finally:
    for key in list(sys.modules):
        if key == 'domain' or key.startswith('domain.'):
            del sys.modules[key]
    sys.modules.update(saved)
    sys.path[:] = saved_path



class ServiceCall:
    def __init__(self, client_factory=None, clock=None):
        self.client_factory, self.clock, self.cancel_event = client_factory, clock, None
    def execute(self, params):
        svc = ElearningService(settings.store().root, client_factory=self.client_factory,
                               clock=self.clock, cancel_event=self.cancel_event)
        method = 'list_courses' if params['action'] == 'courses' else params['action']
        with patch.object(entry, '_service', lambda _: svc):
            result = entry.handle_invoke({'method': method, 'input': {k: v for k, v in params.items() if k != 'action'}})
        import json
        if result['status'] == 'succeeded':
            value = {'courses': result['value']} if method == 'list_courses' else result['value']
            return SimpleNamespace(status='success', result=json.dumps(value, ensure_ascii=False))
        return SimpleNamespace(status='error', result=result['error']['message'])
