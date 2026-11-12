from app.recommendations.text import album_key, canonical_genre, fold


def test_fold_handles_accents_ampersand_and_punctuation():
    assert fold("Beyoncé & Jay-Z") == "beyonce and jay z"
    assert fold("  Gary Clark Jr.  ") == "gary clark jr"


def test_album_key_handles_curly_apostrophes_and_suffixes():
    assert album_key("Greta Van Fleet", "The Battle at Garden’s Gate") == album_key(
        "Greta Van Fleet", "The Battle at Garden's Gate"
    )
    assert album_key("X", "Album (Deluxe Edition)") == album_key("X", "Album")
    assert album_key("X", "Album [Remastered 2011]") == album_key("X", "Album")


def test_canonical_genre_buckets():
    assert canonical_genre("blues rock") == "blues"
    assert canonical_genre("hard bop") == "jazz"
    assert canonical_genre("pop soul") == "soul"
    assert canonical_genre("alternative rock") == "rock"
    assert canonical_genre("R&B") == "soul"
    assert canonical_genre("Hip Hop") == "hip hop"
    assert canonical_genre("") == ""
