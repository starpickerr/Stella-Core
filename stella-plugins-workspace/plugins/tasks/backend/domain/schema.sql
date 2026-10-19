-- stella.tasks schema v1 (extracted from TodoService.__init__)
CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
    due_on TEXT, due_time TEXT, timezone TEXT NOT NULL DEFAULT 'UTC',
    priority INTEGER NOT NULL DEFAULT 0, completed_at TEXT,
    repeat_frequency TEXT NOT NULL DEFAULT 'none', repeat_days TEXT NOT NULL DEFAULT '[]',
    repeat_until TEXT, source_type TEXT, source_key TEXT, source_url TEXT NOT NULL DEFAULT '',
    user_modified INTEGER NOT NULL DEFAULT 0, briefing_id TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(source_type, source_key)
);
CREATE INDEX IF NOT EXISTS todos_due ON todos(due_on);
CREATE TABLE IF NOT EXISTS todo_completions (
    todo_id TEXT NOT NULL, occurrence_on TEXT NOT NULL, completed_at TEXT NOT NULL,
    PRIMARY KEY(todo_id, occurrence_on),
    FOREIGN KEY(todo_id) REFERENCES todos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS todo_checklist_completions (
    todo_id TEXT NOT NULL, occurrence_on TEXT NOT NULL, item_id TEXT NOT NULL,
    PRIMARY KEY(todo_id, occurrence_on, item_id),
    FOREIGN KEY(todo_id) REFERENCES todos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS todo_dependencies (
    task_id TEXT NOT NULL, prerequisite_id TEXT NOT NULL,
    PRIMARY KEY(task_id, prerequisite_id),
    FOREIGN KEY(task_id) REFERENCES todos(id) ON DELETE CASCADE,
    FOREIGN KEY(prerequisite_id) REFERENCES todos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS todo_notifications (
    todo_id TEXT NOT NULL, occurrence_on TEXT NOT NULL, notified_at TEXT NOT NULL,
    PRIMARY KEY(todo_id, occurrence_on),
    FOREIGN KEY(todo_id) REFERENCES todos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reminder_occurrences (
    occurrence_id TEXT PRIMARY KEY, todo_id TEXT NOT NULL,
    occurrence_on TEXT NOT NULL, reminder_kind TEXT NOT NULL,
    due_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
    UNIQUE(todo_id,occurrence_on,reminder_kind),
    FOREIGN KEY(todo_id) REFERENCES todos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reminder_deliveries (
    delivery_id TEXT PRIMARY KEY, occurrence_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending', claim_id TEXT,
    lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0,
    shown_at TEXT, error TEXT,
    FOREIGN KEY(occurrence_id) REFERENCES reminder_occurrences(occurrence_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reminder_route_deliveries (
    delivery_id TEXT NOT NULL, leg TEXT NOT NULL,
    channel_type TEXT NOT NULL, receiver TEXT NOT NULL,
    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
    retryable INTEGER NOT NULL DEFAULT 0,
    platform_response TEXT, error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(delivery_id,leg),
    FOREIGN KEY(delivery_id) REFERENCES reminder_deliveries(delivery_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS todo_migrations (name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS briefing_applied (
    briefing_id TEXT PRIMARY KEY, last_revision INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS source_tombstones (
    source_key TEXT PRIMARY KEY, deleted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS todo_scheduler_links (
    todo_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
    desired_at TEXT, state TEXT NOT NULL DEFAULT 'pending',
    error TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS todo_categories (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, color TEXT NOT NULL, created_at TEXT NOT NULL
);
