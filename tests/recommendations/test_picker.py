import random

from app.recommendations.models import Album, ListeningProfile
from app.recommendations.picker import (
    pick_album,
    pick_local,
    pick_neglected,
    pick_random,
    score_album,
)
from app.recommendations.text import fold


def album(album_id, artist, name, genres=(), plays=None):
    return Album(
        album_id=album_id,
        artist=artist,
        name=name,
        genres=tuple(genres),
        play_count=plays,
    )


def test_pick_never_returns_top_or_quarter_albums():
    top = album("top", "Top", "Top Album")
    quarter = album("quarter", "Quarter", "Quarter Album")
    neglected = album("neglected", "Neglected", "Neglected Album")
    never = album("never", "Never", "Never Album")
    profile = ListeningProfile(
        quarter_keys={top.key, quarter.key},
        all_time_keys={top.key, quarter.key, neglected.key},
        top_album_keys={top.key},
    )
    for seed in range(40):
        pick = pick_album(
            [top, quarter, neglected, never],
            profile,
            oddball_rate=0.0,
            rng=random.Random(seed),
        )
        assert pick.album_id in {"neglected", "never"}


def test_score_prefers_never_played_over_neglected():
    neglected = album("neglected", "Neglected", "Neglected Album")
    never = album("never", "Never", "Never Album")
    profile = ListeningProfile(
        all_time_keys={neglected.key},
        quarter_keys=set(),
        top_album_keys=set(),
    )
    rng = random.Random(7)
    never_score, never_parts = score_album(never, profile, rng)
    neglected_score, neglected_parts = score_album(neglected, profile, rng)
    assert never_score > neglected_score
    assert never_parts["never"] == 1.0
    assert neglected_parts["never"] == 0.0


def test_oddball_restricts_to_zero_affinity():
    loved = album("loved", "Loved", "Loved Album")
    other = album("other", "Other", "Other Album")
    third = album("third", "Third", "Third Album")
    profile = ListeningProfile(
        artist_weights={fold("Loved"): 1.0},
    )
    for seed in range(20):
        pick = pick_album(
            [loved, other, third],
            profile,
            oddball_rate=1.0,
            rng=random.Random(seed),
        )
        assert pick.album_id in {"other", "third"}


def test_recent_album_is_excluded():
    recent = album("recent", "Artist", "Recent Album")
    fresh = album("fresh", "Artist", "Fresh Album")
    profile = ListeningProfile(recent_keys={recent.key})
    for seed in range(20):
        pick = pick_album(
            [recent, fresh],
            profile,
            oddball_rate=0.0,
            rng=random.Random(seed),
        )
        assert pick.album_id == "fresh"


def test_pick_random_is_uniform_over_the_catalog():
    albums = [
        album("a", "A", "A"),
        album("b", "B", "B"),
        album("c", "C", "C"),
    ]
    seen = set()
    for seed in range(60):
        pick = pick_random(albums, rng=random.Random(seed))
        assert pick.reason == "pure random"
        seen.add(pick.album_id)
    assert seen == {"a", "b", "c"}


def test_pick_random_avoids_the_session_tail():
    albums = [album("a", "A", "A"), album("b", "B", "B")]
    pick = pick_random(albums, session_recent={"a"}, rng=random.Random(0))
    assert pick.album_id == "b"


def test_pick_neglected_keeps_the_hard_exclusions_without_affinity():
    top = album("top", "Top", "Top Album")
    quarter = album("quarter", "Quarter", "Quarter Album")
    recent = album("recent", "Recent", "Recent Album")
    neglected = album("neglected", "Neglected", "Neglected Album")
    never = album("never", "Never", "Never Album")
    profile = ListeningProfile(
        quarter_keys={top.key, quarter.key},
        all_time_keys={top.key, quarter.key, recent.key, neglected.key},
        top_album_keys={top.key},
        recent_keys={recent.key},
        artist_weights={fold("Top"): 1.0},
    )
    for seed in range(40):
        pick = pick_neglected(
            [top, quarter, recent, neglected, never],
            profile,
            rng=random.Random(seed),
        )
        assert pick.album_id in {"neglected", "never"}
        assert pick.reason == "random from neglected"


def test_local_fallback_prefers_unplayed():
    unplayed = album("a", "A", "A", plays=0)
    for seed in range(5):
        pick = pick_local([unplayed], rng=random.Random(seed))
        assert pick.album_id == "a"
        assert pick.reason == "never played"


def test_pick_returns_none_when_nothing_is_playable():
    only = album("only", "A", "A")
    assert pick_local([only], session_recent={"only"}) is None
