from datetime import datetime, timezone

from app.recommendations.listenbrainz import ListenBrainzClient, build_profile
from app.recommendations.text import album_key, fold


def _row(artist, album, count):
    return {
        "artist_name": artist,
        "release_group_name": album,
        "listen_count": count,
    }


def test_build_profile_classifies_quarter_alltime_and_top20():
    quarter = [_row("Greta Van Fleet", "The Battle at Garden’s Gate", 365)]
    all_time = quarter + [_row("Old Artist", "Old Album", 4)]
    profile = build_profile(quarter, all_time, [], now=datetime(2026, 11, 12, 9, tzinfo=timezone.utc))

    gvf = album_key("Greta Van Fleet", "The Battle at Garden's Gate")
    old = album_key("Old Artist", "Old Album")
    assert gvf in profile.quarter_keys
    assert old in profile.all_time_keys
    assert old not in profile.quarter_keys
    assert profile.top_album_keys == {gvf}
    assert profile.artist_weights[fold("Greta Van Fleet")] == 1.0


def test_build_profile_keeps_only_20_top_albums():
    quarter = [_row(f"Artist {i}", f"Album {i}", 100 - i) for i in range(25)]
    profile = build_profile(quarter, quarter, [], now=datetime(2026, 11, 12, 9, tzinfo=timezone.utc))
    assert len(profile.top_album_keys) == 20
    assert album_key("Artist 0", "Album 0") in profile.top_album_keys
    assert album_key("Artist 24", "Album 24") not in profile.top_album_keys


def test_build_profile_uses_the_current_hour_for_genres():
    genres = [
        {"genre": "blues", "hour": 9, "listen_count": 100},
        {"genre": "hard bop", "hour": 9, "listen_count": 50},
        {"genre": "pop", "hour": 20, "listen_count": 100},
    ]
    profile = build_profile(
        [], [], genres, now=datetime(2026, 11, 12, 9, tzinfo=timezone.utc)
    )
    # 9 UTC plus the +/-1 window; "pop" only exists at 20, so it must not win.
    assert profile.genre_weights["blues"] == 1.0
    assert profile.genre_weights["jazz"] == 0.5
    assert "pop" not in profile.genre_weights


def test_build_profile_collects_recent_release_names():
    recent = [
        {
            "track_metadata": {
                "artist_name": "Greta Van Fleet",
                "release_name": "The Battle at Garden’s Gate",
            }
        }
    ]
    profile = build_profile([], [], [], recent)
    assert album_key("Greta Van Fleet", "The Battle at Garden's Gate") in profile.recent_keys


def test_client_parses_release_group_payload(monkeypatch):
    client = ListenBrainzClient("mhinge")
    monkeypatch.setattr(
        client,
        "_get",
        lambda path, params=None: {
            "payload": {
                "release_groups": [
                    {"artist_name": "A", "release_group_name": "B", "listen_count": 2}
                ]
            }
        },
    )
    rows = client.release_groups()
    assert rows[0]["listen_count"] == 2


def test_build_profile_aggregates_duplicate_release_groups():
    rows = [
        _row("A", "B", 1),
        _row("A", "B", 2),
        _row("C", "D", 3),
    ]
    profile = build_profile(rows, rows, [])
    assert profile.quarter_keys == {album_key("A", "B"), album_key("C", "D")}
    assert len(profile.top_album_keys) == 2
    assert profile.artist_weights[fold("A")] == 1.0


def test_client_listens_since_paginates_and_filters(monkeypatch):
    client = ListenBrainzClient("mhinge")
    pages = [
        {"payload": {"listens": [{"listened_at": 100}, {"listened_at": 90}]}},
        {"payload": {"listens": [{"listened_at": 80}, {"listened_at": 70}]}},
    ]
    calls = []

    def fake_get(path, params=None):
        calls.append(params)
        return pages.pop(0)

    monkeypatch.setattr(client, "_get", fake_get)
    rows = client.listens_since(75, count=2, max_pages=2)
    assert [row["listened_at"] for row in rows] == [100, 90, 80]
    assert calls[1]["max_ts"] == 90
