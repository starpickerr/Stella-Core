"""Source protocol re-exports Core-owned envelopes for host adapters."""

from core.services.source_types import FetchResult, FetchedItem, Source

__all__ = ["FetchResult", "FetchedItem", "Source"]
