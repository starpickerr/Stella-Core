"""Maintenance is a real runner mode, not a business invoke bypass."""
from pathlib import Path
import sqlite3

import pytest

from core.plugins.host import PluginSession, PluginHostError
from core.plugins.registry import PluginRegistry


def test_real_bills_migration_creates_and_verifies_schema_without_publishing(tmp_path):
    registry = PluginRegistry()
    session = PluginSession(Path('stella-plugins-workspace/plugins/bills'), source_label='test',
                            registry=registry, maintenance=True)
    db = tmp_path / 'bills.sqlite'
    try:
        session.start()
        assert registry.get(session.plugin_id) is None
        applied = session.migrate(operation_id='op', migration_id='migration', from_schema=0, to_schema=1,
                                  data_handle={'dbPath': str(db), 'namespace': session.plugin_id}, mode='apply')
        assert applied['committed']
        verified = session.migrate(operation_id='op', migration_id='migration', from_schema=0, to_schema=1,
                                   data_handle={'dbPath': str(db), 'namespace': session.plugin_id}, mode='verify')
        assert verified['verified']
        with sqlite3.connect(db) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert 'financial_events' in tables
        with pytest.raises(PluginHostError, match='maintenance'):
            session._rpc('plugin.invoke', {})
    finally:
        session.dispose()


def test_active_runner_refuses_migration(tmp_path):
    session = PluginSession(Path('stella-plugins-workspace/plugins/bills'), source_label='test', registry=PluginRegistry())
    try:
        session.start()
        with pytest.raises((PluginHostError, PermissionError), match='maintenance'):
            session.migrate(operation_id='op', migration_id='m', from_schema=0, to_schema=1,
                            data_handle={'dbPath': str(tmp_path / 'never-created.sqlite'), 'namespace': session.plugin_id}, mode='apply')
        assert not (tmp_path / 'never-created.sqlite').exists()
    finally:
        session.dispose()
