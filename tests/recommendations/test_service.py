import pytest

from app.recommendations.service import RecommendationService, normalize_mode


class FakeSource:
    def __init__(self, rows):
        self.rows = rows

    def list_all_albums(self):
        return self.rows


class FakeRegistry:
    def __init__(self, source):
        self.source = source

    def get(self, pid=None):
        return self.source


class FakeConfig:
    def __init__(self, username="mhinge"):
        self.username = username

    def listenbrainz(self):
        return {"username": self.username, "token": ""}


def _listen(artist, album, ts):
    return {
        "listened_at": ts,
        "track_metadata": {"artist_name": artist, "release_name": album},
    }


class FakeListenBrainz:
    """A realistic-enough profile: 100 recent listens plus 25 older ones.

    The top-20 set then has 20 real albums, so "Old Album" (all-time, not in
    the 90-day window) is a genuine neglected candidate rather than a
    degenerate top-20 entry.
    """

    def __init__(self, username, token="", timeout=15.0):
        self.username = username

    def listens_since(self, min_ts, count=1000, max_pages=5):
        rows = [
            _listen("Greta Van Fleet", "Top Album", 2000 - i)
            for i in range(60)
        ]
        rows += [
            _listen("Khruangbin", "A LA SALA", 1000 - i)
            for i in range(40)
        ]
        rows += [
            _listen(f"Dummy {i}", f"Album {i}", 100 - i)
            for i in range(25)
        ]
        return rows

    def release_groups(self, range_name="all_time"):
        rows = [
            {"artist_name": "Greta Van Fleet", "release_group_name": "Top Album", "listen_count": 365},
            {"artist_name": "Khruangbin", "release_group_name": "A LA SALA", "listen_count": 278},
            {"artist_name": "Old Artist", "release_group_name": "Old Album", "listen_count": 4},
        ]
        rows += [
            {"artist_name": f"Dummy {i}", "release_group_name": f"Album {i}", "listen_count": 1}
            for i in range(25)
        ]
        return rows

    def genre_activity(self, range_name="quarter"):
        return []

    def recent_listens(self, count=100):
        return []


def _rows():
    return [
        {"id": "top", "name": "Top Album", "artist": "Greta Van Fleet", "genre": "Rock", "playCount": 50},
        {"id": "quarter", "name": "A LA SALA", "artist": "Khruangbin", "genre": "Funk", "playCount": 20},
        {"id": "neglected", "name": "Old Album", "artist": "Old Artist", "genre": "Jazz", "playCount": 2},
        {"id": "never", "name": "New Album", "artist": "New Artist", "genre": "Soul", "playCount": 0},
    ]


@pytest.mark.asyncio
async def test_pick_uses_listenbrainz_and_excludes_top_and_quarter(monkeypatch):
    monkeypatch.setattr(
        "app.recommendations.service.ListenBrainzClient", FakeListenBrainz
    )
    service = RecommendationService(FakeRegistry(FakeSource(_rows())), FakeConfig())
    pick = await service.pick("living_room")
    assert pick is not None
    assert pick.album_id in {"neglected", "never"}


@pytest.mark.asyncio
async def test_pick_falls_back_to_local_without_listenbrainz(monkeypatch):
    service = RecommendationService(
        FakeRegistry(FakeSource(_rows())), FakeConfig(username="")
    )
    pick = await service.pick("living_room")
    assert pick is not None
    assert pick.components.get("local_fallback") == 1.0


@pytest.mark.asyncio
async def test_session_picks_are_not_repeated(monkeypatch):
    monkeypatch.setattr(
        "app.recommendations.service.ListenBrainzClient", FakeListenBrainz
    )
    service = RecommendationService(
        FakeRegistry(FakeSource(_rows())), FakeConfig(), oddball_rate=0.0
    )
    first = await service.pick()
    second = await service.pick()
    assert first is not None and second is not None
    assert first.album_id != second.album_id


@pytest.mark.asyncio
async def test_pick_random_mode_needs_no_listenbrainz(monkeypatch):
    monkeypatch.setattr(
        "app.recommendations.service.ListenBrainzClient", FakeListenBrainz
    )
    service = RecommendationService(
        FakeRegistry(FakeSource(_rows())), FakeConfig(username="")
    )

    pick = await service.pick("living_room", mode="random")

    assert pick is not None
    assert pick.reason == "pure random"
    assert pick.album_id in {"top", "quarter", "neglected", "never"}


@pytest.mark.asyncio
async def test_pick_neglected_mode_uses_the_hard_exclusions(monkeypatch):
    monkeypatch.setattr(
        "app.recommendations.service.ListenBrainzClient", FakeListenBrainz
    )
    service = RecommendationService(FakeRegistry(FakeSource(_rows())), FakeConfig())

    pick = await service.pick("living_room", mode="neglected")

    assert pick is not None
    assert pick.reason == "random from neglected"
    assert pick.album_id in {"neglected", "never"}


def test_normalize_mode_defaults_to_smart():
    assert normalize_mode(None) == "smart"
    assert normalize_mode("RANDOM") == "random"
    assert normalize_mode("nonsense") == "smart"


@pytest.mark.asyncio
async def test_warm_survives_a_broken_source(monkeypatch):
    class BrokenSource:
        def list_all_albums(self):
            raise RuntimeError("gonic down")

    service = RecommendationService(
        FakeRegistry(BrokenSource()), FakeConfig(username="")
    )
    await service.warm()  # must not raise


def test_album_from_raw_uses_genre_when_genres_is_empty():
    from app.recommendations.service import _album_from_raw

    album = _album_from_raw({
        "id": "al-1",
        "name": "Album",
        "artist": "Artist",
        "genres": [],
        "genre": "Jazz",
        "playCount": "3",
    })
    assert album is not None
    assert album.genres == ("jazz",)
    assert album.play_count == 3
