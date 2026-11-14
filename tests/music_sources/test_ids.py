"""The temporary namespaced-id helpers (removed in the id migration)."""
from app.music_sources.ids import qualify, unqualify


def test_qualify_idempotent_and_unqualify():
    assert qualify("subsonic", "al-678") == "subsonic:al-678"
    assert qualify("subsonic", "subsonic:al-678") == "subsonic:al-678"
    assert unqualify("subsonic:al-678") == ("subsonic", "al-678")
    # legacy bare ids (every card encoded before the namespace)
    assert unqualify("al-678") == (None, "al-678")
