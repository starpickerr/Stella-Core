"""Actual bills migration and read-only verification (maintenance mode)."""
from __future__ import annotations
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
from domain.store import BillStore
REQUIRED_TABLES = frozenset(['financial_events', 'planned_payments', 'ledger_entries', 'period_statements', 'period_statement_items', 'plugin_operation_receipts'])


def apply(migration_id, data_handle):
    path = Path(data_handle['dbPath'])
    BillStore(path)
    return {'migrationId': migration_id, 'applied': True, 'schemaVersion': 1}


def verify(migration_id, data_handle):
    path = Path(data_handle['dbPath'])
    if not path.is_file():
        return {'migrationId': migration_id, 'verified': False, 'schemaVersion': 1}
    with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True)) as db:
        present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        integrity = db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    return {'migrationId': migration_id, 'verified': integrity and REQUIRED_TABLES <= present,
            'schemaVersion': 1, 'missingTables': sorted(REQUIRED_TABLES - present)}
