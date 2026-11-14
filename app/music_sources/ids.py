"""Temporary id helpers for the namespaced-id era.

Step 2 of the Subsonic-only cleanup removes the ``subsonic:`` prefix from
outbound ids. Until then, every entry point still accepts both prefixed and
legacy bare ids; this module is the one place that knows that rule.
"""


def qualify(provider_id: str, raw_id: str) -> str:
    """subsonic + al-678 → 'subsonic:al-678' (idempotent)."""
    prefix = f"{provider_id}:"
    if str(raw_id).startswith(prefix):
        return raw_id
    return prefix + str(raw_id)


def unqualify(qualified_id: str) -> tuple:
    """'subsonic:al-678' → ('subsonic', 'al-678'). Bare ids → (None, id)."""
    sep = str(qualified_id or "").find(":")
    if sep <= 0:
        return None, qualified_id
    return qualified_id[:sep], qualified_id[sep + 1:]
