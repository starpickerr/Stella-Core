from __future__ import annotations

import pytest

from core.services.todos_public import source_key_is_tombstoned


@pytest.mark.usefixtures("todos_plugin")
def test_source_key_is_tombstoned_empty():
    # The ambient service is the real stella.tasks worker (tests/conftest.py).
    assert source_key_is_tombstoned([]) is False
    assert source_key_is_tombstoned([""]) is False
