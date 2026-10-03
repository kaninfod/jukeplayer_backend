#!/usr/bin/env python3
"""Surgical genre-tag cleanup for the jukeplayer collection.

Rationale (measured on this library): the server (gonic) treats each genre
tag as ONE opaque string — multi-genre joins ("; "/", "/"-separated) become
single weird genre rows. This pass therefore:

1. Truncates previously-written multi-joins to their primary (top-vote) genre.
2. Normalizes known variant spellings to MusicBrainz-vocabulary canon.
   (e.g. AlternRock/Alt. Rock -> Alternative Rock, Pop/Rock -> Pop Rock.)
3. Collapses comma/plus-blobs to their first real genre
   ('R&B, Pop, Funk, Hip Hop, Soul.' -> R&B).
4. DELETES placeholder junk (Unknown/Other/Misc/genre) — the enrichment
   rerun then fills those files from MusicBrainz.

Clean canonical values (Rock, Pop, Jazz, Blues, Classic Rock, ...) are left
untouched. Only TCON/GENRE frames are modified; everything else preserved.

Dry-run default; --write applies.
"""
from __future__ import annotations

import argparse
import os
import sys

MUSIC_EXTS = (".mp3", ".flac", ".ogg", ".opus")
JUNK = {"unknown", "other", "misc", "genre"}  # _fold'd values
# whole-value variant -> canonical (folded keys, MusicBrainz-vocabulary aligned).
# checked BEFORE any split, so compound blends keep their meaning.
VARIANT_MAP = {
    "alternrock": "Alternative Rock",
    "altrock": "Alternative Rock",
    "poprock": "Pop Rock",
    "rockpop": "Pop Rock",
    "bluesrock": "Blues Rock",
    "rockblues": "Blues Rock",
    "folkrock": "Folk Rock",
    "rockfolk": "Folk Rock",
    "jazzfunk": "Jazz Funk",
    "funkjazz": "Jazz Funk",
    "hiphop": "Hip Hop",
    "britpop": "Britpop",
    "psychadelicrock": "Psychedelic Rock",
    "psychedelicrock": "Psychedelic Rock",
    "generalalternative": "Alternative",
    "generaljazz": "Jazz",
    "generalrock": "Rock",
    "generalpop": "Pop",
    "generalblues": "Blues",
    "jazzinstrument": "Jazz",
    "ambientalternative": "Ambient",
    "vocalpop": "Pop",
    "soulandrb": "Soul",
}


def _fold(name: str) -> str:
    return "".join(c for c in (name or "").lower() if c.isalnum())


def canonicalize_genre_string(raw: str) -> str | None:
    """The ONE algorithm for a stored genre value. Returns the single
    canonical genre, or None when the whole tag should be deleted.

    Order matters:
    1. junk (Unknown/Other/Misc/genre) -> delete
    2. whole-value variants (blends like Pop/Rock, typos, compound words)
       -> mapped canon. This runs BEFORE any split so "Pop/Rock" keeps its
       blended meaning instead of collapsing to its first half.
    3. multi-blobs (','-separated lists) -> FIRST real part, then that part
       goes through the variant map again (handles 'Other/jazz' etc.)."""
    raw = (raw or "").strip().rstrip(". ")
    fold_raw = _fold(raw)
    if not raw:
        return None
    if fold_raw in JUNK:
        return None
    if fold_raw in VARIANT_MAP:
        return VARIANT_MAP[fold_raw]

    # 3. multi-blob: first real part wins (handles "," blobs AND the "; "
    #    joins this tooling wrote earlier for gonic-incompatible multi-genre)
    for part in raw.replace(";", ",").split(","):
        part = part.strip().rstrip(". ")
        if not part:
            continue
        for sub in part.replace("/", ",").replace("+", ",").split(","):
            sub = sub.strip()
            fold_sub = _fold(sub)
            if not sub or fold_sub in JUNK:
                continue
            canon = VARIANT_MAP.get(fold_sub, sub).strip()
            return canon.title()
    return None


def genre_tag_value(raw_values: list[str]) -> str | None:
    """What the TCON/GENRE tag should say after cleanup, given everything in
    the tag today (list of strings). None = delete the tag."""
    for entry in raw_values:
        canon = canonicalize_genre_string(str(entry))
        if canon:
            return canon
    return None


# ---------------------------------------------------------------- tag IO


def read_genres(path: str) -> list[str]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".mp3":
        from mutagen.id3 import ID3
        try:
            tags = ID3(path)
        except Exception:
            return []
        return [str(v) for f in tags.getall("TCON") for v in f.text]
    if ext == ".flac":
        from mutagen.flac import FLAC
        return list((FLAC(path).tags or {}).get("genre") or [])
    if ext in (".ogg", ".opus"):
        if ext == ".ogg":
            from mutagen.oggvorbis import OggVorbis
            meta = OggVorbis(path)
        else:
            from mutagen.opus import OpusFile
            meta = OpusFile(path)
        return list((meta.tags or {}).get("genre") or [])
    return []


def write_genres(path: str, value: str | None) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".mp3":
        from mutagen.id3 import ID3
        try:
            tags = ID3(path)
        except Exception:
            tags = None
        if tags is None:
            from mutagen.id3 import ID3 as _ID3
            tags = _ID3()
        tags.delall("TCON")
        if value:
            tags.add(_tcon(value))
        tags.save(path, v2_version=3)
        return True
    if ext == ".flac":
        from mutagen.flac import FLAC
        meta = FLAC(path)
        if value:
            meta["GENRE"] = [value]
        else:
            del meta["GENRE"]
        meta.save()
        return True
    if ext in (".ogg", ".opus"):
        if ext == ".ogg":
            from mutagen.oggvorbis import OggVorbis
            meta = OggVorbis(path)
        else:
            from mutagen.opus import OpusFile
            meta = OpusFile(path)
        if value:
            meta["GENRE"] = [value]
        else:
            if "GENRE" in (meta.tags or {}):
                del meta["GENRE"]
        meta.save()
        return True
    return False


def _tcon(value: str):
    from mutagen.id3 import TCON
    return TCON(encoding=1, text=[value])


# ---------------------------------------------------------------- driver


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="surgical genre cleanup")
    p.add_argument("--dir", default=os.getenv("MUSIC_DIR", "/mnt/music/collection"))
    p.add_argument("--report", default="/home/pi/genre_cleanup_report.md")
    p.add_argument("--write", action="store_true")
    args = p.parse_args(argv)

    changes: dict[str, int] = {}
    deletions = 0
    untouched = 0
    details = []
    for root, _dirs, files in os.walk(args.dir):
        for name in sorted(files):
            if not name.lower().endswith(MUSIC_EXTS):
                continue
            path = os.path.join(root, name)
            try:
                raw = read_genres(path)
            except Exception as e:
                print(f"  [read-fail] {path}: {type(e).__name__}: {e}")
                continue
            if not any(gen for gen in raw):
                untouched += 1
                continue
            fresh = genre_tag_value(raw)
            current = raw[0].strip() if raw else ""
            if fresh == current:
                untouched += 1
                continue
            detail = {
                "file": path,
                "before": "; ".join(raw),
                "after": fresh or "(deleted)",
            }
            details.append((fresh is None, detail))
            key = f"{current} -> {fresh or '(deleted)'}"
            changes[key] = changes.get(key, 0) + 1
            if fresh is None:
                deletions += 1
            if args.write:
                write_genres(path, fresh)

    # report ---------------------------------------------------------------
    lines = [
        "# Genre cleanup report",
        "",
        f"files touched: {len(details)}   deletions: {deletions}   untouched: {untouched}",
        "",
        "## Transformations (count by before -> after)",
        "",
    ]
    for key, n in sorted(changes.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {n:4d}x  {key}")
    lines += ["", "## File details", "", "| before | after | file |", "|---|---|---|"]
    for _deletion, d in details:
        rel = d["file"].split("/collection/", 1)[-1]
        lines.append(f"| {d['before']} | {d['after']} | {rel} |")
    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"[cleanup] touched {len(details)}, deletions {deletions}, untouched {untouched}")
    print(f"[cleanup] report: {args.report}")
    if not args.write:
        print("[cleanup] dry-run only — re-run with --write to apply")
    else:
        print("[cleanup] next: rerun genre_enrichment to fill cleared tags from MB, then rescan gonic")
    return 0


if __name__ == "__main__":
    sys.exit(main())