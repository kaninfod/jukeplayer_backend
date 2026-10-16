"""The collection ledger: add/snapshot/list/artists/remove — the tiny sqlite
of deliberately added albums."""
from app.music_sources.collection import AlbumStore


def make_store(tmp_path):
    return AlbumStore(path=str(tmp_path / "collection.db"))


def test_add_and_list_roundtrip(tmp_path):
    store = make_store(tmp_path)
    store.add_album(pid="ytmusic", aid="MPREb_x", title="An Album",
                    artist="The Band", year="1975", thumb="http://t/1", track_count=10)
    rows = store.list_albums()
    assert len(rows) == 1
    row = rows[0]
    assert (row["pid"], row["aid"]) == ("ytmusic", "MPREb_x")
    assert row["title"] == "An Album" and row["origin"] == "api"
    assert row["added_at"]   # timestamped


def test_readd_refreshes_snapshot_keeps_first_added_at(tmp_path):
    store = make_store(tmp_path)
    first = store.add_album(pid="ytmusic", aid="MPREb_x", title="An Album")
    second = store.add_album(pid="ytmusic", aid="MPREb_x", title="An Album (deluxe)")
    assert second["added_at"] == first["added_at"]   # the first add wins
    assert second["title"] == "An Album (deluxe)"    # the snapshot refreshed
    assert store.count() == 1


def test_artists_and_albums_by_artist(tmp_path):
    store = make_store(tmp_path)
    store.add_album(pid="ytmusic", aid="MPREb_x", title="One", artist="Led Zeppelin", year="1975")
    store.add_album(pid="ytmusic", aid="MPREb_y", title="Two", artist="Led Zeppelin", year="1979")
    store.add_album(pid="ytmusic", aid="MPREb_z", title="Three", artist="Bee Gees", year="1971")

    arts = store.artists()
    assert [a["artist"] for a in arts] == ["Bee Gees", "Led Zeppelin"]   # nocase alpha
    assert arts[1]["albums"] == 2
    albums = store.albums_by_artist("led zeppelin")
    assert [a["title"] for a in albums] == ["One", "Two"]


def test_remove(tmp_path):
    store = make_store(tmp_path)
    store.add_album(pid="ytmusic", aid="MPREb_x", title="An Album")
    assert store.remove_album("ytmusic", "MPREb_x") is True
    assert store.remove_album("ytmusic", "MPREb_x") is False
    assert store.count() == 0


def test_filter_by_source(tmp_path):
    store = make_store(tmp_path)
    store.add_album(pid="ytmusic", aid="MPREb_x", title="One")
    store.add_album(pid="subsonic", aid="al-9", title="Local-ish (a future case?)")
    assert [r["aid"] for r in store.list_albums(pid="ytmusic")] == ["MPREb_x"]
    assert store.count() == 2