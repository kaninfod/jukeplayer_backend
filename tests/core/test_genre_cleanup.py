"""Table tests for the surgical genre cleanup (real inventoried values)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from scripts.genre_cleanup import canonicalize_genre_string  # noqa: E402


@pytest.mark.parametrize("raw,expected", [
    # clean values pass through unchanged
    ("Rock", "Rock"),
    ("Pop", "Pop"),
    ("Blues", "Blues"),
    ("Jazz", "Jazz"),
    ("Classic Rock", "Classic Rock"),
    ("Hard Rock", "Hard Rock"),
    ("Post-Grunge", "Post-Grunge"),
    ("R&B", "R&B"),
    ("Rock & Roll", "Rock & Roll"),
    ("Electronic", "Electronic"),
    ("Indie", "Indie"),
    ("Folk", "Folk"),
    ("Top 40", "Top 40"),
    ("Acoustic", "Acoustic"),
    ("Noise", "Noise"),
    ("Bluegrass", "Bluegrass"),
    # junk -> delete (tag cleared; enrichment fills it back from MB)
    ("Unknown", None),
    ("Other", None),
    ("Misc", None),
    ("genre", None),
    # variant spellings -> MB-vocabulary canon
    ("AlternRock", "Alternative Rock"),
    ("Alt. Rock", "Alternative Rock"),
    ("Hip-Hop", "Hip Hop"),
    ("Hip Hop", "Hip Hop"),
    ("BritPop", "Britpop"),
    ("Psychadelic Rock", "Psychedelic Rock"),
    ("General Alternative", "Alternative"),
    ("General Jazz", "Jazz"),
    ("General Rock", "Rock"),
    ("Jazz Instrument", "Jazz"),
    ("Ambient Alternative", "Ambient"),
    # blended compounds keep their meaning (single canonical blend name)
    ("Pop/Rock", "Pop Rock"),
    ("Rock/Pop", "Pop Rock"),
    ("Blues/Rock", "Blues Rock"),
    ("Folk-Rock", "Folk Rock"),
    ("Folk/Rock", "Folk Rock"),
    ("Jazz+Funk", "Jazz Funk"),
    ("Alternative / Rock", "Alternative"),
    # 'and'-join -> dominant part
    ("Soul And R&B", "Soul"),
    # comma blobs -> first real part
    ("R&B, Pop, Funk, Hip Hop, Soul.", "R&B"),
    ("jazz, bossa nove", "Jazz"),
    ("Soul, Funk, Jazz", "Soul"),
    ("Other/jazz", "Jazz"),
    # semicolon joins (written by the enrichment before the gonic finding)
    ("Pop; Blue-Eyed Soul; Pop Soul", "Pop"),
    ("Pop Soul; Blue-Eyed Soul", "Pop Soul"),
])
def test_canonicalize_inventory(raw, expected):
    assert canonicalize_genre_string(raw) == expected