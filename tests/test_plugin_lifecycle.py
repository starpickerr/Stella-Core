from pathlib import Path
import json

import pytest

from core.plugins.management import ManagementStore
from core.plugins.package_ops import _sha256_tree
from core.plugins.lifecycle import PluginManager


def _catalog(tmp_path, root=Path('stella-plugins-workspace/plugins/bills')):
    manifest = json.loads((root / 'plugin.json').read_text())
    file = tmp_path / 'catalog.json'
    file.write_text(json.dumps({'coreApi': '1.0.0', 'plugins': [{
        'pluginId': manifest['id'], 'version': manifest['version'], 'hostApi': manifest['hostApi'],
        'path': str(root.resolve()), 'sha256': _sha256_tree(root),
    }]}))
    return file


def test_install_uses_real_migration_then_selects_package_and_keeps_disabled_intent(tmp_path, monkeypatch):
    from core.plugins import management
    store = ManagementStore(tmp_path / 'packages')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    store.set_intent('stella.bills', 'local-default', 'disabled')
    data = tmp_path / 'domain' / 'bills.sqlite'
    manager = PluginManager(store, catalog_path=_catalog(tmp_path))
    result = manager.install('stella.bills', user_id='local-default',
                             data_handle={'dbPath': str(data), 'namespace': 'stella.bills'})
    assert result['stage'] == 'completed'
    assert data.exists()
    assert manager.packages.current_package('stella.bills')
    assert store.instance('stella.bills', 'local-default')['intent'] == 'disabled'
    assert manager.inventory('local-default')[0]['state'] == 'stopped'


def test_remove_preserves_data_and_prevents_bootstrap_resurrection(tmp_path, monkeypatch):
    from core.plugins import management
    store = ManagementStore(tmp_path / 'packages')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    data = tmp_path / 'domain' / 'bills.sqlite'
    manager = PluginManager(store, catalog_path=_catalog(tmp_path))
    manager.install('stella.bills', user_id='local-default',
                    data_handle={'dbPath': str(data), 'namespace': 'stella.bills'})
    original = data.read_bytes()
    manager.set_intent('stella.bills', 'local-default', 'removed')
    assert data.read_bytes() == original
    assert manager.inventory('local-default')[0]['intent'] == 'removed'
    assert not manager.inventory('local-default')[0]['services']


@pytest.mark.parametrize('stage', ['prepared', 'migrated', 'selected'])
def test_resume_lifecycle_selection_after_crash(tmp_path, monkeypatch, stage):
    from core.plugins import management
    store = ManagementStore(tmp_path / 'packages')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    manager = PluginManager(store, catalog_path=_catalog(tmp_path))
    data = tmp_path / 'bills.sqlite'

    class Crash(BaseException):
        pass

    def interrupt(current, op):
        if current == stage:
            raise Crash()

    with pytest.raises(Crash):
        manager.install('stella.bills', user_id='local-default',
                        data_handle={'dbPath': str(data), 'namespace': 'stella.bills'}, checkpoint=interrupt)
    operation = [op for op in store.unfinished() if op['kind'] == 'install'][0]
    restarted = PluginManager(ManagementStore(tmp_path / 'packages'), catalog_path=tmp_path / 'offline-catalog')
    result = restarted.resume(operation['operationId'])
    assert result['stage'] == 'completed'
    assert restarted.packages.current_package('stella.bills')
    assert store.instance('stella.bills', 'local-default')['state'] == 'stopped'


def test_one_corrupt_pointer_keeps_other_installed_inventory_visible(tmp_path, monkeypatch):
    from core.plugins import management
    store = ManagementStore(tmp_path / 'packages')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    manager = PluginManager(store, catalog_path=_catalog(tmp_path))
    manager.install('stella.bills', user_id='local-default',
                    data_handle={'dbPath': str(tmp_path / 'bills.sqlite'), 'namespace': 'stella.bills'})
    bad = manager.packages.packages / 'stella.tasks' / 'current.json'
    bad.parent.mkdir()
    bad.write_text('{broken')
    rows = {row['pluginId']: row for row in manager.inventory('local-default')}
    assert rows['stella.bills']['version']
    assert rows['stella.tasks']['state'] == 'failed'
    assert rows['stella.tasks']['error']
