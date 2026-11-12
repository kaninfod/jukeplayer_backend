from scripts.dedupe_listenbrainz import plan_deletions


def listen(msid, client, track="Song", ts=1700000000):
    return {
        "listened_at": ts,
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


def test_importer_only_group_is_untouched():
    first = listen("a", "ListenBrainz lastfm importer v2")
    second = listen("b", "ListenBrainz lastfm importer v2")

    deletions, stats = plan_deletions([first, second])

    assert deletions == []
    assert stats["untouched_groups"] == 1


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
