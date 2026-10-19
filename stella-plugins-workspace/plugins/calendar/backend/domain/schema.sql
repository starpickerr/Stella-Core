-- =============================================================================
-- Stella 日程模块 SQLite 表结构（stella.calendar）
-- 由 CalendarService.__init__ 通过 IF NOT EXISTS 幂等应用；
-- repeat_* 列另由服务层 PRAGMA table_info 检查补齐旧库。
-- 时间字段均为 ISO-8601 文本（UTC），重复规则时区存于 repeat_timezone。
-- =============================================================================

CREATE TABLE IF NOT EXISTS calendar_categories (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calendar_events (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    start_at TEXT NOT NULL, end_at TEXT NOT NULL, all_day INTEGER NOT NULL DEFAULT 0,
    location TEXT NOT NULL DEFAULT '', category_id TEXT,
    source_type TEXT, source_key TEXT, source_url TEXT NOT NULL DEFAULT '',
    user_modified INTEGER NOT NULL DEFAULT 0,
    repeat_frequency TEXT NOT NULL DEFAULT 'none',
    repeat_days TEXT NOT NULL DEFAULT '[]',
    repeat_until TEXT,
    repeat_timezone TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY(category_id) REFERENCES calendar_categories(id) ON DELETE SET NULL,
    UNIQUE(source_type, source_key)
);
CREATE INDEX IF NOT EXISTS calendar_events_start ON calendar_events(start_at);
CREATE TABLE IF NOT EXISTS calendar_occurrence_exclusions (
    series_id TEXT NOT NULL, occurrence_on TEXT NOT NULL,
    PRIMARY KEY(series_id, occurrence_on),
    FOREIGN KEY(series_id) REFERENCES calendar_events(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS agenda_handoffs (
    source_type TEXT NOT NULL, source_key TEXT NOT NULL,
    destination TEXT NOT NULL CHECK(destination IN ('task','calendar')),
    title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
    briefing_id TEXT NOT NULL, briefing_item_id TEXT NOT NULL,
    calendar_event_id TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY(source_type, source_key, destination)
);
CREATE TABLE IF NOT EXISTS briefing_applied (
    briefing_id TEXT PRIMARY KEY, last_revision INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS source_tombstones (
    source_key TEXT PRIMARY KEY, deleted_at TEXT NOT NULL
);

