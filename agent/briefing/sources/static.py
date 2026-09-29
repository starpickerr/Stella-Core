"""In-memory source for tests and pipeline dry-runs. Not a real inbox."""

from __future__ import annotations

from typing import Dict, List, Optional

from agent.briefing.sources.base import FetchResult, FetchedItem


class StaticSource:
    name = "email"
    account_id = "default"

    def __init__(
        self,
        items: Optional[List[FetchedItem]] = None,
        cursors: Optional[Dict[str, str]] = None,
        *,
        name: str = "email",
        account_id: str = "default",
        error: Optional[BaseException] = None,
    ):
        self.name = name
        self.account_id = account_id
        self._items = list(items or [])
        self._cursors = dict(cursors or {"imap_uid": "1"})
        self._error = error

    def fetch(self, cursors: Dict[str, str]) -> FetchResult:
        if self._error is not None:
            raise self._error
        return FetchResult(items=list(self._items), cursors=dict(self._cursors))
