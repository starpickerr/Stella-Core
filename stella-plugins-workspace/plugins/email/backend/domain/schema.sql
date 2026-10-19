-- stella.email schema v1
CREATE TABLE IF NOT EXISTS email_accounts (
    id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    host TEXT NOT NULL,
    user TEXT NOT NULL,
    password TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 993,
    folder TEXT NOT NULL DEFAULT 'INBOX',
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS email_cursors (
    source_account_id TEXT NOT NULL,
    cursor_key TEXT NOT NULL,
    cursor_value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source_account_id, cursor_key)
);
CREATE TABLE IF NOT EXISTS email_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
