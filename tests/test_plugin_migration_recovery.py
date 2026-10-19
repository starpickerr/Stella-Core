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


def test_older_package_cannot_migrate_a_newer_domain_schema(tmp_path):
    data = tmp_path / 'bills.sqlite'
    _legacy(data)
    with closing(sqlite3.connect(data)) as db, db:
        db.execute('CREATE TABLE _stella_migrations (id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL)')
        db.execute("INSERT INTO _stella_migrations VALUES ('newer-package', 2)")
    before = data.read_bytes()
    store = ManagementStore(tmp_path / 'packages')
    with pytest.raises((RuntimeError, PermissionError), match='downgrade'):
        MigrationCoordinator(store).run(BILLS, user_id='local-default',
            data_handle={'namespace': 'stella.bills', 'dbPath': str(data)})
    assert data.read_bytes() == before


def test_email_migration_backup_and_transient_copies_are_private_and_guarded(tmp_path, monkeypatch):
    import os
    from common import state_dir
    from agent.tools.utils.credentials import is_credential_path
    monkeypatch.setattr(state_dir, 'briefing_db', lambda **_: tmp_path / 'briefing/briefing.db')
    monkeypatch.setattr(state_dir, 'shared_root', lambda: tmp_path / 'shared')
    data = tmp_path / 'email/email.db'
    data.parent.mkdir()
    _legacy(data)
    from tests.email_domain import EmailService
    EmailService(data).save_account({'action': 'add', 'host': 'imap.example.test',
                                    'user': 'test@example.test', 'password': 'migration-test-secret'})
    data.chmod(0o644)
    state = ManagementStore(tmp_path / 'shared/plugin-packages')
    seen = []
    def inspect(stage, operation):
        if stage in ('backed_up', 'migrated', 'data_selected'):
            for key in ('backupRef', 'scratchRef', 'retiredRef'):
                path = Path(operation['facts'][key])
                if path.is_file():
                    seen.append(path)
                    assert is_credential_path(str(path)), (stage, key)
                    with closing(sqlite3.connect(path)) as db:
                        assert db.execute('SELECT password FROM email_accounts').fetchone()[0] == 'migration-test-secret'
                    if os.name == 'posix':
                        assert path.stat().st_mode & 0o777 == 0o600
    result = MigrationCoordinator(state).run(Path('stella-plugins-workspace/plugins/email'),
        user_id='local-default', data_handle={'dbPath': str(data), 'namespace': 'stella.email'}, checkpoint=inspect)
    assert result['stage'] == 'data_selected' and seen
    with closing(sqlite3.connect(result['facts']['backupRef'])) as db:
        assert db.execute('SELECT value FROM user_kept').fetchone()[0] == 'original user data'
