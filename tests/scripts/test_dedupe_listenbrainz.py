import urllib.error

import pytest

import scripts.dedupe_listenbrainz as dedupe
from scripts.dedupe_listenbrainz import listen_identity, plan_deletions


def listen(msid, client, track="Song", ts=1700000000, inserted_at=1):
    return {
        "listened_at": ts,
        "inserted_at": inserted_at,
        "recording_msid": msid,
        "track_metadata": {
            "artist_name": "Artist",
            "track_name": track,
            "additional_info": {"submission_client": client},
        },
    }


def test_plan_keeps_gonic_and_deletes_importer():
    gonic = listen("g", "gonic", track="Black Man In A White World")
    importer = listen("i", "ListenBrainz lastfm importer v2",
                      track="Black Man in a White World")

    deletions, stats = plan_deletions([gonic, importer])

    assert [item["recording_msid"] for item in deletions] == ["i"]
    assert stats["duplicate_groups"] == 1
    assert stats["planned"] == 1


def test_importer_only_duplicates_keep_the_earliest():
    first = listen("a", "ListenBrainz lastfm importer v2", inserted_at=1)
    second = listen("b", "ListenBrainz lastfm importer v2", inserted_at=2)

    deletions, stats = plan_deletions([first, second])

    assert [item["recording_msid"] for item in deletions] == ["b"]
    assert stats["kept_importer_only"] == 1


def test_single_importer_listen_is_untouched():
    only = listen("a", "ListenBrainz lastfm importer v2")

    deletions, stats = plan_deletions([only])

    assert deletions == []
    assert stats["untouched_groups"] == 0


def test_listen_identity_includes_the_timestamp():
    """The same recording at two different times is two listens."""
    first = listen("same-msid", "gonic", ts=1700000000)
    second = listen("same-msid", "gonic", ts=1700000100)

    assert listen_identity(first) != listen_identity(second)


def test_all_importer_copies_are_deleted_when_a_gonic_twin_exists():
    gonic = listen("g", "gonic")
    first = listen("i1", "ListenBrainz lastfm importer v2")
    second = listen("i2", "ListenBrainz lastfm importer v2")

    deletions, _stats = plan_deletions([gonic, first, second])

    assert {item["recording_msid"] for item in deletions} == {"i1", "i2"}


def test_missing_importer_msid_is_not_deleted():
    gonic = listen("g", "gonic")
    importer = listen(None, "ListenBrainz lastfm importer v2")

    deletions, _stats = plan_deletions([gonic, importer])

    assert deletions == []


def test_delete_one_retries_transient_network_errors(monkeypatch):
    calls = []

    def fake_request(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.URLError("network unreachable")
        return {}

    monkeypatch.setattr(dedupe, "_request", fake_request)
    monkeypatch.setattr(dedupe.time, "sleep", lambda _seconds: None)

    dedupe.delete_one("token", {"listened_at": 1, "recording_msid": "m"}, attempts=3)

    assert len(calls) == 3


def test_delete_one_does_not_retry_auth_failure(monkeypatch):
    calls = []

    def fake_request(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError("url", 401, "unauthorized", {}, None)

    monkeypatch.setattr(dedupe, "_request", fake_request)
    monkeypatch.setattr(dedupe.time, "sleep", lambda _seconds: None)

    with pytest.raises(urllib.error.HTTPError):
        dedupe.delete_one("token", {"listened_at": 1, "recording_msid": "m"}, attempts=3)

    assert len(calls) == 1
