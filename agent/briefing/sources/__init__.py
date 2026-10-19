from agent.briefing.sources.base import FetchResult, FetchedItem, Source

__all__ = [
    "EmailSource",
    "FetchResult",
    "FetchedItem",
    "Source",
]


def __getattr__(name):
    # The legacy IMAP source loads on demand so plugin-backed runs that only need
    # the shared DTOs in ``base`` never import it.
    if name == "EmailSource":
        from agent.briefing.sources.email import EmailSource
        return EmailSource
    raise AttributeError(name)
