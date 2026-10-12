-- =============================================================================
-- Stella briefing module SQLite schema
--
-- Envelope catalog + per-source extension + briefing snapshot:
--   source_items      Shared envelope for every fetched item (email, sms, …)
--   email_messages    Email-private columns (1:1 with source_items)
--   briefings         One briefing document per day
--   briefing_items    Snapshot cards on a briefing (copy envelope; optional link)
--   briefing_candidates Historical candidate links; classified snapshots live in briefing_mail
--   filter_rules      User-authored rules (legacy field columns retained)
--   sync_state        Per-source incremental cursors
--
-- Add a new source later with another 1:1 table (e.g. sms_messages) whose
-- PRIMARY KEY is source_items.id. Do not point briefing_items at that table
-- directly — always go through source_items.
--
-- JSON text fields such as payload are read/written by the app.
-- Credentials are never stored. Filtered-out items are not written to
-- briefing_items; they increment filtered_count and stay in the candidate catalog.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Source envelope: one row per (source, account, source_id) globally.
-- Display fields live here so rules and pipeline do not depend on source type.
-- Unpromoted private fields stay in payload until they earn an extension table.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_items (
    id               TEXT    PRIMARY KEY,
    source           TEXT    NOT NULL,                          -- email / sms / calendar / …
    account_id       TEXT    NOT NULL DEFAULT 'default',        -- multi-account per source
    source_id        TEXT    NOT NULL,                          -- unique within source, e.g. Message-ID
    thread_id        TEXT    NOT NULL DEFAULT '',               -- thread merge key; empty if none
    sender           TEXT    NOT NULL DEFAULT '',               -- display name
    title            TEXT    NOT NULL DEFAULT '',               -- subject / title
    snippet          TEXT    NOT NULL DEFAULT '',               -- summary, not full body
    occurred_at      TEXT    NOT NULL,                          -- source timestamp
    url              TEXT    NOT NULL DEFAULT '',               -- mid: / webmail / web link
    payload          TEXT    NOT NULL DEFAULT '{}',             -- private JSON not yet promoted
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    UNIQUE (source, account_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_source_items_occurred
    ON source_items(source, occurred_at);

CREATE INDEX IF NOT EXISTS idx_source_items_thread
    ON source_items(source, account_id, thread_id);

-- -----------------------------------------------------------------------------
-- Email extension: 1:1 with source_items. Parent row should have source='email'.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS email_messages (
    source_item_id   TEXT    PRIMARY KEY,                       -- source_items.id
    sender_email     TEXT    NOT NULL DEFAULT '',               -- From address
    list_id          TEXT    NOT NULL DEFAULT '',               -- mailing-list id
    FOREIGN KEY (source_item_id) REFERENCES source_items(id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- Briefing document: one row per user/day (id convention, e.g.
-- brf-2026-09-09). Source windows track successful refresh boundaries.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS briefings (
    window_start     TEXT,
    window_end       TEXT,
    mail_snapshot_available INTEGER NOT NULL DEFAULT 0,
    rule_text        TEXT    NOT NULL DEFAULT '',
    source_windows   TEXT    NOT NULL DEFAULT '{}',
    updated_sources  TEXT    NOT NULL DEFAULT '[]',
    id               TEXT    PRIMARY KEY,                       -- e.g. brf-2026-09-09
    status           TEXT    NOT NULL DEFAULT 'running'
                             CHECK (status IN (
                                'running',                     -- in progress
                                'completed',                   -- finished successfully
                                'failed',                      -- failed
                                'partial'                      -- partial success
                             )),
    title            TEXT    NOT NULL DEFAULT '',               -- list title
    body             TEXT    NOT NULL DEFAULT '',               -- composed Markdown, not source text
    fetched_count    INTEGER NOT NULL DEFAULT 0
                             CHECK (fetched_count >= 0),        -- all window candidates before filtering
    kept_count       INTEGER NOT NULL DEFAULT 0
                             CHECK (kept_count >= 0),           -- selected source messages before thread merging
    filtered_count   INTEGER NOT NULL DEFAULT 0
                             CHECK (filtered_count >= 0),       -- candidates rejected by the Agent
    error_message    TEXT    NOT NULL DEFAULT '',               -- error detail when failed/partial
    generated_at     TEXT,                                      -- last compose time; null if unfinished
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL
);

-- List view: browse by compose time
CREATE INDEX IF NOT EXISTS idx_briefings_generated
    ON briefings(generated_at);

-- Scheduler / recovery: find running or failed rows
CREATE INDEX IF NOT EXISTS idx_briefings_status
    ON briefings(status);

-- -----------------------------------------------------------------------------
-- Briefing snapshot cards (action / FYI). Envelope columns are copied at
-- compose time so old briefings still render if the catalog row is gone.
-- source_item_id is optional; ON DELETE SET NULL keeps the snapshot.
-- Same catalog item may appear on different days, so uniqueness includes
-- briefing_id.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS briefing_items (
    id               TEXT    PRIMARY KEY,
    briefing_id      TEXT    NOT NULL,                          -- briefings.id
    source_item_id   TEXT,                                      -- source_items.id; null if unlinked
    source           TEXT    NOT NULL,                          -- snapshot: email / sms / …
    account_id       TEXT    NOT NULL DEFAULT 'default',
    source_id        TEXT    NOT NULL,                          -- snapshot of source-local id
    thread_id        TEXT    NOT NULL DEFAULT '',
    section          TEXT    NOT NULL
                             CHECK (section IN (
                                 'action',                      -- needs reply / decision
                                 'fyi'                          -- important FYI
                             )),
    status           TEXT    NOT NULL DEFAULT 'undo'
                             CHECK (status IN (
                                 'undo',                        -- not handled yet
                                 'done',                        -- read / handled
                                 'ignored',                     -- ignored
                                 'follow_up'                    -- needs follow-up
                             )),
    score            INTEGER NOT NULL DEFAULT 0
                             CHECK (score BETWEEN 0 AND 100),   -- ranking score
    sender           TEXT    NOT NULL DEFAULT '',               -- snapshot display name
    title            TEXT    NOT NULL DEFAULT '',               -- snapshot subject / title
    snippet          TEXT    NOT NULL DEFAULT '',               -- snapshot summary
    occurred_at      TEXT    NOT NULL,                          -- snapshot source timestamp
    url              TEXT    NOT NULL DEFAULT '',               -- snapshot link
    payload          TEXT    NOT NULL DEFAULT '{}',             -- snapshot of private JSON
    sort_order       INTEGER NOT NULL DEFAULT 0,                -- order within section
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    FOREIGN KEY (briefing_id) REFERENCES briefings(id) ON DELETE CASCADE,
    FOREIGN KEY (source_item_id) REFERENCES source_items(id) ON DELETE SET NULL,
    UNIQUE (briefing_id, source, account_id, source_id)
);

-- Detail view: render by section + order
CREATE INDEX IF NOT EXISTS idx_briefing_items_briefing
    ON briefing_items(briefing_id, section, sort_order);

-- Filter by handling status (undo / done / …)
CREATE INDEX IF NOT EXISTS idx_briefing_items_status
    ON briefing_items(briefing_id, status);

-- Thread merge / lookup on the snapshot
CREATE INDEX IF NOT EXISTS idx_briefing_items_thread
    ON briefing_items(briefing_id, thread_id);

-- Jump from a catalog row to the briefings that cited it
CREATE INDEX IF NOT EXISTS idx_briefing_items_source_item
    ON briefing_items(source_item_id);

-- One catalog row at most once per briefing (NULL links excluded)
CREATE UNIQUE INDEX IF NOT EXISTS idx_briefing_items_briefing_source_item
    ON briefing_items(briefing_id, source_item_id)
    WHERE source_item_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- User rule documents: Markdown/plain text consumed by the briefing Agent.
-- Legacy field columns remain for compatible upgrades and old API callers.
-- source = '*' means all sources; otherwise scoped (e.g. email).
-- Envelope fields match source_items; sender_email / list_id match email_messages.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS filter_rules (
    text             TEXT    NOT NULL DEFAULT '',              -- free-form filtering and writing instructions
    id               TEXT    PRIMARY KEY,
    enabled          INTEGER NOT NULL DEFAULT 1
                             CHECK (enabled IN (0, 1)),
    source           TEXT    NOT NULL DEFAULT '*',              -- '*' or email / sms / …
    action           TEXT    NOT NULL
                             CHECK (action IN (
                                 'include',                     -- whitelist: always keep
                                 'exclude'                      -- blacklist: always drop
                             )),
    match_field      TEXT    NOT NULL
                             CHECK (match_field IN (
                                 'sender',                      -- sender display name
                                 'sender_email',                -- sender address (email extension)
                                 'sender_domain',               -- sender domain (derived / payload)
                                 'title',                       -- subject / title
                                 'list_id'                      -- mailing list (email extension)
                             )),
    match_op         TEXT    NOT NULL DEFAULT 'eq'
                             CHECK (match_op IN (
                                 'eq',
                                 'contains'
                             )),
    match_value      TEXT    NOT NULL,                          -- e.g. alerts@github.com
    note             TEXT    NOT NULL DEFAULT '',
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    -- One row per match condition (note / enabled are not part of uniqueness)
    UNIQUE (source, action, match_field, match_op, match_value)
);

CREATE INDEX IF NOT EXISTS idx_filter_rules_enabled
    ON filter_rules(enabled, source, action);

-- -----------------------------------------------------------------------------
-- Incremental cursors: bookmark how far we fetched; no message bodies.
-- Advance only after a briefing is persisted successfully.
-- PK is source + account + cursor name.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sync_state (
    source           TEXT    NOT NULL,                          -- email / sms / calendar / …
    account_id       TEXT    NOT NULL DEFAULT 'default',
    cursor_key       TEXT    NOT NULL,                          -- e.g. imap_uid, imap_uidvalidity
    cursor_value     TEXT    NOT NULL DEFAULT '',
    updated_at       TEXT    NOT NULL,
    PRIMARY KEY (source, account_id, cursor_key)
);

-- Keep all run candidates (including filtered mail) so reruns can apply new
-- rules after the source cursor has advanced.
CREATE TABLE IF NOT EXISTS briefing_candidates (
    briefing_id TEXT NOT NULL REFERENCES briefings(id) ON DELETE CASCADE,
    source_item_id TEXT NOT NULL REFERENCES source_items(id) ON DELETE CASCADE,
    PRIMARY KEY (briefing_id, source_item_id)
);

-- Immutable generation/update snapshots, including copied cards.
CREATE TABLE IF NOT EXISTS briefing_revisions (
    briefing_id TEXT NOT NULL REFERENCES briefings(id) ON DELETE CASCADE,
    number INTEGER NOT NULL CHECK (number > 0),
    trigger TEXT NOT NULL,
    created_at TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    PRIMARY KEY (briefing_id, number)
);

-- Frozen candidate mail classifications; revisions retain their own copies.
CREATE TABLE IF NOT EXISTS briefing_mail (
    briefing_id TEXT NOT NULL REFERENCES briefings(id) ON DELETE CASCADE,
    source_item_id TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    PRIMARY KEY (briefing_id, source_item_id)
);
