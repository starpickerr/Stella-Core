"""R07 includes actual domain bytes, backup, migration marker and restart."""
from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from core.plugins.management import ManagementStore
from core.plugins.migration import MigrationCoordinator

BILLS = Path('stella-plugins-workspace/plugins/bills')


class PowerLoss(BaseException):
    pass


def _legacy(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE user_kept (value TEXT)')
        db.execute("INSERT INTO user_kept VALUES ('original user data')")


@pytest.mark.parametrize('stage', ['drained', 'backed_up', 'migrating', 'migrated', 'data_selected'])
def test_resume_actual_domain_migration_after_each_durable_stage(tmp_path, stage):
    data = tmp_path / 'bills.sqlite'
    _legacy(data)
    management = ManagementStore(tmp_path / 'packages')
    coordinator = MigrationCoordinator(management)

    def interrupt(current, operation):
        if current == stage:
            raise PowerLoss()

    with pytest.raises(PowerLoss):
        coordinator.run(BILLS, user_id='local-default', data_handle={'dbPath': str(data), 'namespace': 'stella.bills'},
                        checkpoint=interrupt)
    operation = management.unfinished('stella.bills')[0]
    resumed = MigrationCoordinator(ManagementStore(tmp_path / 'packages')).run(
        BILLS, user_id='local-default', data_handle={'dbPath': str(data), 'namespace': 'stella.bills'},
        operation_id=operation['operationId'])
    assert resumed['stage'] == 'data_selected'
    with closing(sqlite3.connect(data)) as db:
        assert db.execute('SELECT value FROM user_kept').fetchone()[0] == 'original user data'
        assert db.execute('SELECT COUNT(*) FROM _stella_migrations').fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='financial_events'").fetchone()
    backup = Path(resumed['facts']['backupRef'])
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute('SELECT value FROM user_kept').fetchone()[0] == 'original user data'
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='_stella_migrations'").fetchone()
    # Old code cannot reopen until the package-selection owner finishes.
    assert management.instance('stella.bills', 'local-default')['state'] == 'maintenance'


def test_schema_verification_failure_keeps_original_and_requires_repair(tmp_path):
    import shutil

    data = tmp_path / 'bills.sqlite'
    _legacy(data)
    package = tmp_path / 'broken'
    shutil.copytree(BILLS, package)
    (package / 'backend/migrate.py').write_text('''def apply(mid, handle):
    return {'applied': True, 'schemaVersion': 1}
def verify(mid, handle):
    return {'verified': False, 'schemaVersion': 1}
''')
    management = ManagementStore(tmp_path / 'packages')
    with pytest.raises(RuntimeError, match='verification'):
        MigrationCoordinator(management).run(package, user_id='local-default',
                                             data_handle={'dbPath': str(data), 'namespace': 'stella.bills'})
    with closing(sqlite3.connect(data)) as db:
        assert db.execute('SELECT value FROM user_kept').fetchone()[0] == 'original user data'
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='_stella_migrations'").fetchone()
    assert management.unfinished()[0]['stage'] == 'repair_required'
