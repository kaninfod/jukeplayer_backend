"""Name and genre normalisation for matching ListenBrainz to gonic.

ListenBrainz serves MusicBrainz names ("The Battle at Garden's Gate",
"blue-eyed soul"); gonic serves the tags written into the files. The two are
close but not identical, so every comparison is folded through this module.
"""

from __future__ import annotations

import re
import unicodedata

# Strip the common cosmetic suffixes that make an owned album look different
# from the ListenBrainz release group ("Deluxe Edition", "Remastered", ...).
_SUFFIX_RE = re.compile(
    r"\s*[\(\[]\s*"
    r"(?:deluxe|remaster(?:ed)?|expanded|anniversary|bonus|special|"
    r"collector|edition|version)"
    r"[^)\]]*[\)\]]\s*$",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def fold(value: object) -> str:
    """Case/punctuation/whitespace-insensitive key.

    Accents are removed, ``&`` becomes ``and``, apostrophes and punctuation
    become spaces. Articles are deliberately kept: "The The" and "The Band"
    are different artists.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    return " ".join(_NON_ALNUM.sub(" ", text).split())


def album_key(artist: object, album: object) -> tuple[str, str]:
    """Stable (folded artist, folded album) key used on both sides."""
    title = _SUFFIX_RE.sub("", str(album or ""))
    return fold(artist), fold(title)


def canonical_genre(value: object) -> str:
    """Collapse MusicBrainz/Last.fm genre tags into broad listening buckets.

    Order matters: "blues rock" is a blues listening signal, "pop soul" is
    soul, and "alternative rock" is rock. Unknown tags are returned folded so
    they still compare case-insensitively.
    """
    genre = fold(value)
    if not genre:
        return ""
    if "jazz" in genre or "bop" in genre:
        return "jazz"
    if "blues" in genre:
        return "blues"
    if "soul" in genre or "rhythm and blues" in genre or genre in {"r and b", "rnb"}:
        return "soul"
    if "hip hop" in genre or "rap" in genre:
        return "hip hop"
    if "classical" in genre or "opera" in genre:
        return "classical"
    if "folk" in genre or "singer songwriter" in genre:
        return "folk"
    if "country" in genre:
        return "country"
    if any(word in genre for word in ("electronic", "ambient", "dance", "house", "techno")):
        return "electronic"
    if "soundtrack" in genre or "score" in genre:
        return "soundtrack"
    if "rock" in genre:
        return "rock"
    if "pop" in genre:
        return "pop"
    return genre
