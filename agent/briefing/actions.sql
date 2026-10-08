-- Additive decision state; existing snapshots and business objects stay intact.
CREATE TABLE IF NOT EXISTS briefing_entities (
    entity_key TEXT PRIMARY KEY,
    source TEXT NOT NULL, account_id TEXT NOT NULL, information_type TEXT NOT NULL,
    course_id TEXT NOT NULL DEFAULT '', title TEXT NOT NULL, facts TEXT NOT NULL,
    category TEXT NOT NULL, occurred_at TEXT NOT NULL, fingerprint TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS briefing_entity_items (
    item_id TEXT PRIMARY KEY, entity_key TEXT NOT NULL,
    change_type TEXT NOT NULL, snapshot_fingerprint TEXT NOT NULL,
    FOREIGN KEY(entity_key) REFERENCES briefing_entities(entity_key)
);
CREATE INDEX IF NOT EXISTS briefing_entity_items_key ON briefing_entity_items(entity_key);
CREATE TABLE IF NOT EXISTS briefing_actions (
    entity_key TEXT NOT NULL, kind TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending', operation TEXT NOT NULL DEFAULT 'create',
    target_id TEXT, options TEXT NOT NULL DEFAULT '{}', baseline TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT '{}',
    authorization TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
    PRIMARY KEY(entity_key,kind),
    FOREIGN KEY(entity_key) REFERENCES briefing_entities(entity_key)
);
CREATE TABLE IF NOT EXISTS briefing_action_rules (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, account_id TEXT NOT NULL,
    information_type TEXT NOT NULL, course_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL, mode TEXT NOT NULL, reminder_minutes INTEGER NOT NULL DEFAULT 1440,
    updated_at TEXT NOT NULL,
    UNIQUE(source,account_id,information_type,course_id,kind)
);
CREATE TABLE IF NOT EXISTS briefing_preferences (
    id INTEGER PRIMARY KEY CHECK(id=1), preferences TEXT NOT NULL
);
