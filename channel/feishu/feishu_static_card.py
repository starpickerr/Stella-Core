"""Helpers for choosing the native Feishu delivery format for text replies."""

import json
import re
from typing import Tuple


_BLOCK_MARKDOWN = re.compile(
    r"(?m)^\s{0,3}(?:#{1,6}\s|>\s|[-*+]\s|\d+[.)]\s|```|~~~)"
)
_INLINE_MARKDOWN = re.compile(r"(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^]\n]+\]\([^)\n]+\))")
_TABLE_SEPARATOR = re.compile(r"(?m)^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def contains_markdown(text: str) -> bool:
    """Return whether *text* contains syntax that benefits from card Markdown."""
    if not text:
        return False
    return bool(
        _BLOCK_MARKDOWN.search(text)
        or _INLINE_MARKDOWN.search(text)
        or _TABLE_SEPARATOR.search(text)
    )


def build_markdown_card(text: str) -> dict:
    """Build an inline Card 2.0 payload with one Markdown element."""
    return {
        "schema": "2.0",
        "config": {},
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": text,
                }
            ]
        },
    }


def build_text_delivery(text: str, enabled: bool = True) -> Tuple[str, str]:
    """Return the Feishu ``msg_type`` and serialized content for a text reply."""
    if enabled and contains_markdown(text):
        return "interactive", json.dumps(build_markdown_card(text), ensure_ascii=False)
    return "text", json.dumps({"text": text}, ensure_ascii=False)
