from __future__ import annotations

from core.services.todos_public import source_key_is_tombstoned


def test_source_key_is_tombstoned_empty():
    assert source_key_is_tombstoned([]) is False
    assert source_key_is_tombstoned([""]) is False
