"""Public source DTOs; connection implementations live in their plugins."""
from agent.briefing.sources.base import FetchResult, FetchedItem, Source

__all__ = ['FetchResult', 'FetchedItem', 'Source']
