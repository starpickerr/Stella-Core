"""Domain facades must not import private agent.briefing types."""
from __future__ import annotations

from pathlib import Path


def test_email_and_elearning_facades_use_core_source_types():
    email = Path("core/services/email_facade.py").read_text(encoding="utf-8")
    elearning = Path("core/services/elearning_facade.py").read_text(encoding="utf-8")
    assert "agent.briefing" not in email
    assert "agent.briefing" not in elearning
    assert "core.services.source_types" in email
    assert "core.services.source_types" in elearning


def test_source_types_module_owns_fetched_item():
    from core.services.source_types import FetchResult, FetchedItem, Source

    item = FetchedItem(source="email", source_id="1", title="hi")
    result = FetchResult(items=[item])
    assert result.items[0].to_catalog_payload()["title"] == "hi"
    assert getattr(Source, "__name__", "Source") == "Source"
