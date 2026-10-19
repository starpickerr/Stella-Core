import sqlite3

import pytest

from stella_briefing_domain.models import (
    Briefing,
    BriefingItem,
    EmailMessage,
    FilterRule,
    SourceItem,
    SyncCursor,
)
from stella_briefing_domain.store import (
    BriefingStore,
    clear_briefing_store_cache,
    get_briefing_store,
)


_TABLES = {
    "source_items",
    "email_messages",
    "briefings",
    "briefing_items",
    "briefing_candidates",
    "filter_rules",
    "sync_state",
}

_BRIEFING_COLS = """
    id, status, title, body,
    fetched_count, kept_count, filtered_count, error_message,
    generated_at, created_at, updated_at
"""

_SOURCE_ITEM_COLS = """
    id, source, account_id, source_id, thread_id,
    sender, title, snippet, occurred_at, url, payload,
    created_at, updated_at
"""

_TS = "2026-09-09T00:00:00Z"


def _insert_briefing(conn, briefing_id="brf-2026-09-09-morning"):
    conn.execute(
        f"""
        INSERT INTO briefings ({_BRIEFING_COLS}) VALUES (
            ?, 'completed',
            '晨报', '', 2, 1, 1, '',
            ?, ?, ?
        )
        """,
        (briefing_id, _TS, _TS, _TS),
    )


def _insert_source_item(conn, item_id="src-1", source_id="<msg-1@example.com>"):
    conn.execute(
        f"""
        INSERT INTO source_items ({_SOURCE_ITEM_COLS}) VALUES (
            ?, 'email', 'default', ?, '',
            'Ada', 'Need review', 'Please review the doc',
            '2026-09-08T22:00:00Z', '', '{{}}',
            ?, ?
        )
        """,
        (item_id, source_id, _TS, _TS),
    )
    conn.execute(
        """
        INSERT INTO email_messages (source_item_id, sender_email, list_id)
        VALUES (?, 'ada@example.com', '')
        """,
        (item_id,),
    )


def _insert_briefing_item(
    conn,
    item_id,
    source_id="<msg-1@example.com>",
    source_item_id="src-1",
    section="action",
    sort_order=0,
):
    conn.execute(
        """
        INSERT INTO briefing_items (
            id, briefing_id, source_item_id, source, account_id, source_id,
            thread_id, section, status, score, sender, title, snippet,
            occurred_at, url, payload, sort_order, created_at, updated_at
        ) VALUES (
            ?, 'brf-2026-09-09-morning', ?, 'email', 'default', ?,
            '', ?, 'undo', 80, 'Ada', 'Need review', 'Please review the doc',
            '2026-09-08T22:00:00Z', '', '{}', ?, ?, ?
        )
        """,
        (item_id, source_item_id, source_id, section, sort_order, _TS, _TS),
    )


def test_creates_database_when_file_is_missing(tmp_path):
    db = tmp_path / "briefing" / "briefing.db"
    store = BriefingStore(db)

    assert store.created_new is True
    assert db.is_file()
    assert _TABLES.issubset(store.table_names())


def test_reuses_existing_database_without_recreating(tmp_path):
    db = tmp_path / "briefing.db"
    first = BriefingStore(db)
    sqlite3.connect(str(db)).execute(
        f"""
        INSERT INTO briefings ({_BRIEFING_COLS}) VALUES (
            'brf-2026-09-09-morning', 'completed',
            '', '', 0, 0, 0, '',
            ?, ?, ?
        )
        """,
        (_TS, _TS, _TS),
    ).connection.commit()

    second = BriefingStore(db)

    assert first.created_new is True
    assert second.created_new is False
    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM briefings").fetchone()[0]
    conn.close()
    assert count == 1


def test_get_briefing_store_creates_once_per_path(tmp_path):
    clear_briefing_store_cache()
    db = tmp_path / "briefing.db"
    a = get_briefing_store(db)
    b = get_briefing_store(db)
    assert a is b
    clear_briefing_store_cache()


def test_source_items_reject_duplicate_source_id(tmp_path):
    db = tmp_path / "briefing.db"
    BriefingStore(db)
    conn = sqlite3.connect(str(db))
    _insert_source_item(conn)
    conn.commit()

    try:
        conn.execute(
            f"""
            INSERT INTO source_items ({_SOURCE_ITEM_COLS}) VALUES (
                'src-2', 'email', 'default', '<msg-1@example.com>', '',
                'Ada', 'Need review', 'dup',
                '2026-09-08T22:00:00Z', '', '{{}}',
                ?, ?
            )
            """,
            (_TS, _TS),
        )
        conn.commit()
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    conn.close()
    assert raised is True


def test_email_messages_require_source_item(tmp_path):
    db = tmp_path / "briefing.db"
    BriefingStore(db)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        conn.execute(
            """
            INSERT INTO email_messages (source_item_id, sender_email, list_id)
            VALUES ('missing', 'ada@example.com', '')
            """
        )
        conn.commit()
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    conn.close()
    assert raised is True


def test_briefing_items_require_parent_and_unique_source_id(tmp_path):
    db = tmp_path / "briefing.db"
    BriefingStore(db)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON")
    _insert_briefing(conn)
    _insert_source_item(conn)
    _insert_briefing_item(conn, "item-1")
    conn.commit()

    try:
        _insert_briefing_item(
            conn, "item-2", source_item_id=None, section="fyi", sort_order=1
        )
        conn.commit()
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    conn.close()
    assert raised is True


def test_deleting_source_item_unlinks_snapshot(tmp_path):
    db = tmp_path / "briefing.db"
    BriefingStore(db)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON")
    _insert_briefing(conn)
    _insert_source_item(conn)
    _insert_briefing_item(conn, "item-1")
    conn.commit()

    conn.execute("DELETE FROM source_items WHERE id = 'src-1'")
    conn.commit()

    row = conn.execute(
        "SELECT source_item_id, title FROM briefing_items WHERE id = 'item-1'"
    ).fetchone()
    email_gone = conn.execute(
        "SELECT COUNT(*) FROM email_messages WHERE source_item_id = 'src-1'"
    ).fetchone()[0]
    conn.close()

    assert row[0] is None
    assert row[1] == "Need review"
    assert email_gone == 0


def test_filter_rules_reject_duplicate_match(tmp_path):
    db = tmp_path / "briefing.db"
    BriefingStore(db)
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        INSERT INTO filter_rules (
            id, enabled, source, action, match_field, match_op, match_value,
            note, created_at, updated_at
        ) VALUES (
            'rule-1', 1, 'email', 'exclude', 'sender_domain', 'eq', 'spam.example',
            '', ?, ?
        )
        """,
        (_TS, _TS),
    )
    conn.commit()

    try:
        conn.execute(
            """
            INSERT INTO filter_rules (
                id, enabled, source, action, match_field, match_op, match_value,
                note, created_at, updated_at
            ) VALUES (
                'rule-2', 0, 'email', 'exclude', 'sender_domain', 'eq', 'spam.example',
                'dup', ?, ?
            )
            """,
            (_TS, _TS),
        )
        conn.commit()
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    conn.close()
    assert raised is True


def test_schema_indexes_exist(tmp_path):
    db = tmp_path / "briefing.db"
    BriefingStore(db)
    conn = sqlite3.connect(str(db))
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'"
        ).fetchall()
    }
    conn.close()
    assert {
        "idx_source_items_occurred",
        "idx_source_items_thread",
        "idx_briefings_generated",
        "idx_briefings_status",
        "idx_briefing_items_briefing",
        "idx_briefing_items_status",
        "idx_briefing_items_thread",
        "idx_briefing_items_source_item",
        "idx_briefing_items_briefing_source_item",
        "idx_filter_rules_enabled",
    }.issubset(names)


def _source(item_id="src-1", source_id="<msg-1@example.com>", title="Need review"):
    return SourceItem(
        id=item_id,
        source="email",
        account_id="default",
        source_id=source_id,
        thread_id="",
        sender="Ada",
        title=title,
        snippet="Please review the doc",
        occurred_at="2026-09-08T22:00:00Z",
        url="",
        payload={"k": 1},
        created_at=_TS,
        updated_at=_TS,
    )


def _email(item_id="src-1"):
    return EmailMessage(
        source_item_id=item_id, sender_email="ada@example.com", list_id=""
    )


def _briefing(briefing_id="brf-2026-09-09-morning", status="completed", title="晨报"):
    return Briefing(
        id=briefing_id,
        status=status,
        title=title,
        body="# hello",
        fetched_count=2,
        kept_count=1,
        filtered_count=1,
        error_message="",
        generated_at=_TS,
        created_at=_TS,
        updated_at=_TS,
    )


def _card(item_id="item-1", source_item_id="src-1", section="action", sort_order=0):
    return BriefingItem(
        id=item_id,
        briefing_id="brf-2026-09-09-morning",
        source="email",
        account_id="default",
        source_id="<msg-1@example.com>",
        thread_id="",
        section=section,
        status="undo",
        score=80,
        sender="Ada",
        title="Need review",
        snippet="Please review the doc",
        occurred_at="2026-09-08T22:00:00Z",
        url="",
        sort_order=sort_order,
        created_at=_TS,
        updated_at=_TS,
        source_item_id=source_item_id,
        payload={"k": 1},
    )


def test_upsert_source_item_round_trip_and_natural_key(tmp_path):
    store = BriefingStore(tmp_path / "briefing.db")
    item, email = store.upsert_source_item(_source(), _email())

    assert item.id == "src-1"
    assert item.payload == {"k": 1}
    assert email is not None
    assert email.sender_email == "ada@example.com"

    by_id = store.get_source_item("src-1")
    by_key = store.get_source_item_by_key("email", "default", "<msg-1@example.com>")
    assert by_id is not None and by_key is not None
    assert by_id[0].title == by_key[0].title == "Need review"

    updated, email2 = store.upsert_source_item(
        _source(item_id="src-other", title="Updated"),
        EmailMessage(source_item_id="src-other", sender_email="ada@x.com", list_id="l1"),
    )
    assert updated.id == "src-1"
    assert updated.title == "Updated"
    assert email2 is not None
    assert email2.sender_email == "ada@x.com"
    assert email2.list_id == "l1"
    assert store.get_source_item("src-other") is None


def test_briefing_snapshot_replace_and_status(tmp_path):
    store = BriefingStore(tmp_path / "briefing.db")
    store.upsert_source_item(_source(), _email())
    store.save_snapshot(_briefing(), [_card()])

    items = store.list_briefing_items("brf-2026-09-09-morning")
    assert len(items) == 1
    assert items[0].payload == {"k": 1}

    store.save_snapshot(_briefing(), [_card(item_id="item-2", section="fyi", sort_order=1)])
    items = store.list_briefing_items("brf-2026-09-09-morning")
    assert [row.id for row in items] == ["item-2"]

    changed = store.update_item_status("item-2", "done", "2026-09-09T01:00:00Z")
    assert changed is not None
    assert changed.status == "done"
    assert store.update_item_status("missing", "done", _TS) is None

    again = store.upsert_briefing(_briefing(status="partial", title="补跑"))
    assert again.created_at == _TS
    assert again.status == "partial"
    listed = store.list_briefings()
    assert [row.id for row in listed] == ["brf-2026-09-09-morning"]


def test_filter_rules_and_cursors(tmp_path):
    store = BriefingStore(tmp_path / "briefing.db")
    rule = FilterRule(
        id="rule-1",
        enabled=True,
        source="email",
        action="exclude",
        match_field="sender_domain",
        match_op="eq",
        match_value="spam.example",
        note="",
        created_at=_TS,
        updated_at=_TS,
    )
    store.insert_rule(rule)
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_rule(
            FilterRule(
                id="rule-2",
                enabled=False,
                source="email",
                action="exclude",
                match_field="sender_domain",
                match_op="eq",
                match_value="spam.example",
                note="dup",
                created_at=_TS,
                updated_at=_TS,
            )
        )

    updated = store.update_rule(
        FilterRule(
            id="rule-1",
            enabled=False,
            source="email",
            action="exclude",
            match_field="sender_domain",
            match_op="eq",
            match_value="spam.example",
            note="off",
            created_at=_TS,
            updated_at="2026-09-09T01:00:00Z",
        )
    )
    assert updated is not None
    assert updated.enabled is False
    assert store.list_rules(enabled_only=True) == []
    assert store.delete_rule("rule-1") is True
    assert store.delete_rule("rule-1") is False

    store.set_cursor(
        SyncCursor(
            source="email",
            account_id="default",
            cursor_key="imap_uid",
            cursor_value="10",
            updated_at=_TS,
        )
    )
    store.set_cursor(
        SyncCursor(
            source="email",
            account_id="default",
            cursor_key="imap_uid",
            cursor_value="20",
            updated_at="2026-09-09T01:00:00Z",
        )
    )
    cursor = store.get_cursor("email", "default", "imap_uid")
    assert cursor is not None
    assert cursor.cursor_value == "20"
