"""Stable category-link checks shared by calendar and reminder sync."""

DIRECTIONS = frozenset({"import", "export", "bidirectional"})


def reconcile_names(stored_apple, stored_stella, apple_now, stella_now):
    """Decide a name change from the last synced pair, not from content direction.

    Returns ``(action, name)``. ``name`` is the string the other side should
    adopt, or ``None`` when the two sides disagree.
    """
    apple_changed = apple_now != stored_apple
    stella_changed = stella_now != stored_stella
    if apple_changed and stella_changed:
        if apple_now == stella_now:
            return "aligned", apple_now
        return "conflict", None
    if apple_changed:
        return "apple_to_stella", apple_now
    if stella_changed:
        return "stella_to_apple", stella_now
    return "unchanged", stella_now


def validate_links(rows):
    """Reject links that are not a one-to-one enabled mapping."""
    seen_apple = set()
    seen_stella = set()
    for row in rows:
        apple_id = str(row.get("apple_id") or "").strip()
        stella_id = str(row.get("stella_id") or "").strip()
        direction = str(row.get("direction") or "").strip()
        if not apple_id:
            raise ValueError("apple_id is required")
        if not stella_id:
            raise ValueError("stella_id is required")
        if direction not in DIRECTIONS:
            raise ValueError(f"direction must be one of {', '.join(sorted(DIRECTIONS))}")
        if not isinstance(row.get("enabled"), bool):
            raise ValueError("enabled must be a boolean")
        if apple_id in seen_apple or stella_id in seen_stella:
            raise ValueError("category links must be one-to-one")
        seen_apple.add(apple_id)
        seen_stella.add(stella_id)
