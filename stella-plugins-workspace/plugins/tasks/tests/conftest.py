import copy
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest


domain_root = Path(__file__).resolve().parents[1] / "backend/domain"
spec = importlib.util.spec_from_file_location(
    "stella_tasks_domain", domain_root / "__init__.py", submodule_search_locations=[str(domain_root)]
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class MemorySchedulerStore:
    """In-memory stand-in for the host scheduler adapter (get/add/update/delete/list)."""

    def __init__(self):
        self.tasks = {}

    def get_task(self, task_id):
        task = self.tasks.get(task_id)
        return copy.deepcopy(task) if task is not None else None

    def add_task(self, task):
        self.tasks[task["id"]] = copy.deepcopy(task)

    def update_task(self, task_id, task):
        self.tasks[task_id] = copy.deepcopy(task)

    def delete_task(self, task_id):
        self.tasks.pop(task_id, None)

    def list_tasks(self):
        return [copy.deepcopy(task) for task in self.tasks.values()]


@pytest.fixture
def scheduler_store_cls():
    return MemorySchedulerStore


@pytest.fixture
def scheduler_store():
    return MemorySchedulerStore()


def create_legacy_calendar_db(path):
    """The legacy calendar tables the one-time calendar-affairs migration reads."""
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                start_at TEXT NOT NULL, end_at TEXT NOT NULL, all_day INTEGER NOT NULL DEFAULT 0,
                location TEXT NOT NULL DEFAULT '', category_id TEXT,
                source_type TEXT, source_key TEXT, source_url TEXT NOT NULL DEFAULT '',
                user_modified INTEGER NOT NULL DEFAULT 0,
                repeat_frequency TEXT NOT NULL DEFAULT 'none',
                repeat_days TEXT NOT NULL DEFAULT '[]',
                repeat_until TEXT, repeat_timezone TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(source_type, source_key)
            );
            CREATE TABLE IF NOT EXISTS agenda_handoffs (
                source_type TEXT NOT NULL, source_key TEXT NOT NULL,
                destination TEXT NOT NULL CHECK(destination IN ('task','calendar')),
                title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
                briefing_id TEXT NOT NULL, briefing_item_id TEXT NOT NULL,
                calendar_event_id TEXT, updated_at TEXT NOT NULL,
                PRIMARY KEY(source_type, source_key, destination)
            );
        """)


@pytest.fixture
def legacy_calendar_db():
    return create_legacy_calendar_db
