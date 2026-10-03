#!/usr/bin/env python3
"""Bulk genre enrichment for the jukeplayer music collection.

Reads the MusicBrainz IDs already embedded in the files (TXXX "MusicBrainz
Release Group Id" / "MusicBrainz Artist Id"), fetches community-voted genres
from MusicBrainz (release-group first, artist for inheritance), with an
optional Last.fm fallback for artists MB has no data for — then writes GENRE
tags into the files (MP3: TCON as ID3v2.3; FLAC/ogg/opus: GENRE comment).

Dry-run is the default; nothing writes without --write. All fetch results are
cached in a sqlite database, so the script can be interrupted and re-run
without re-querying MusicBrainz.

Etiquette: serialized requests (~1 req/s), exponential backoff on 429/503,
identifying User-Agent.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MB_API = "https://musicbrainz.org/ws/2"
LASTFM_API = "https://ws.audioscrobbler.com/2.0/"
USER_AGENT = "jukeplayer-genre-enricher/1.0 (jukeplayer home jukebox)"
MUSIC_EXTS = (".mp3", ".flac", ".ogg", ".opus")

MIN_VOTES = 3
MAX_GENRES = 3
LASTFM_FALLBACK_MAX = 3


def _fold(name: str) -> str:
    """Case/punctuation-insensitive key: 'hip-hop' == 'hip hop', 'r&b' == 'R&B'."""
    return "".join(c for c in (name or "").lower() if c.isalnum())


# ---------------------------------------------------------------- pure core


def parse_mbids_from_id3(tags) -> tuple[str | None, str | None]:
    """(release_group_mbid, artist_mbid) from a mutagen ID3 tag object.

    Picard writes TXXX frames with human descriptions ("MusicBrainz Release
    Group Id"); matching is case-insensitive and tolerant of spacing."""
    if tags is None:
        return None, None
    rgid = artist = None
    for frame in tags.getall("TXXX"):
        desc = str(getattr(frame, "desc", "")).strip().lower().replace("_", " ")
        text = getattr(frame, "text", None) or [""]
        val = str(text[0]) if text else ""
        if desc == "musicbrainz release group id" and val:
            rgid = val.strip()
        elif desc in ("musicbrainz artist id", "musicbrainz album artist id") and val:
            artist = val.strip()
    return rgid, artist


def parse_mbids_from_vorbis(metadata) -> tuple[str | None, str | None]:
    """Same for FLAC/ogg/opus comment lists. Values may be multi-valued."""
    if metadata is None:
        return None, None

    def first(*keys):
        for key in keys:
            vals = metadata.get(key) or []
            if vals and str(vals[0]).strip():
                return str(vals[0]).strip()
        return None

    # Vorbis convention (Picard/FLAC): MUSICBRAINZ_<NAME>ID — no spaces;
    # mutagen keys are case-insensitive.
    return (
        first("musicbrainz_releasegroupid"),
        first("musicbrainz_artistid", "musicbrainz_albumartistid"),
    )


def normalize_genres(names: list[str]) -> list[str]:
    """Canonical display form: Title Case, deduped case-insensitively,
    preserving input order."""
    seen, out = set(), []
    for name in names:
        name = (name or "").strip()
        if not name:
            continue
        title = name.title()
        key = title.lower()
        if key not in seen:
            seen.add(key)
            out.append(title)
    return out


def qualifying(genre_dicts: list[dict], min_votes: int) -> list[str]:
    """Genre names with total votes >= min_votes, ordered votes desc."""
    scored = []
    for g in genre_dicts:
        votes = int(g.get("vote_count") or g.get("count") or 0)
        name = (g.get("name") or "").strip()
        if name and votes >= min_votes:
            scored.append((votes, name))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [name for _, name in scored]


def select_genres(
    rg_genres: list[dict],
    artist_genres: list[dict],
    lastfm_names: list[str],
    min_votes: int = MIN_VOTES,
    max_genres: int = MAX_GENRES,
) -> tuple[list[str], str]:
    """(genres, provenance): release-group first; artist inheritance second;
    Last.fm (already vocabulary-filtered) last."""
    chosen = qualifying(rg_genres, min_votes)[:max_genres]
    if chosen:
        return normalize_genres(chosen), "musicbrainz_release_group"
    chosen = qualifying(artist_genres, min_votes)[:max_genres]
    if chosen:
        return normalize_genres(chosen), "musicbrainz_artist"
    if lastfm_names:
        return normalize_genres(lastfm_names[:max_genres]), "lastfm"
    return [], "none"


def genre_join(genres: list[str]) -> str | None:
    """Subsonic-convention joined genre string for TCON, or None when empty."""
    names = normalize_genres(genres)
    return "; ".join(names) if names else None


# NOTE: genre_join is intentionally retained for reports/inspection only.
# The WRITER uses single-primary genres (see write_genres / gonic convention).


# ---------------------------------------------------------------- fetch layer


class RateLimitedClient:
    """Serialized HTTP JSON fetcher: ~1 req/s, backoff on 429/503."""

    def __init__(self, user_agent: str = USER_AGENT):
        self.user_agent = user_agent
        self._last_request_at = 0.0
        self.mb_vocab: set[str] = set()

    def get_json(self, url: str, tries: int = 5) -> dict:
        for attempt in range(tries):
            self._throttle()
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < tries - 1:
                    delay = min(60, (2 ** attempt) * 2)
                    print(f"  [rate] {e.code} — backing off {delay}s", flush=True)
                    time.sleep(delay)
                    continue
                if e.code == 404:
                    return {}
                raise
        raise RuntimeError(f"rate limit kept rejecting: {url.split('?')[0]}")

    def _throttle(self):
        now = time.monotonic()
        wait = 1.05 - (now - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()


def fetch_mb_genres(client: RateLimitedClient, entity: str, mbid: str) -> list[dict]:
    url = f"{MB_API}/{entity}/{mbid}?inc=genres&fmt=json"
    data = client.get_json(url)
    return [
        {"name": g.get("name", ""), "count": g.get("count", 0), "vote_count": g.get("vote_count", 0)}
        for g in data.get("genres", [])
    ]


def fetch_mb_genre_vocabulary(client: RateLimitedClient) -> set[str]:
    """MB's genre/all endpoint is PAGINATED (default limit 25, max 100) —
    page through it fully."""
    names, offset, page = [], 0, 100
    while True:
        data = client.get_json(f"{MB_API}/genre/all?fmt=json&limit={page}&offset={offset}")
        batch = data.get("genres", [])
        if not batch:
            break
        names += [g.get("name", "").strip().lower() for g in batch if g.get("name")]
        if len(batch) < page or offset > 5000:  # safety cap: ~2k genres expected
            break
        offset += page
    return {n for n in names if n}


def fetch_lastfm_genres(client: RateLimitedClient, artist_name: str, api_key: str) -> list[str]:
    """Top-ranked artist tags FILTERED to the MusicBrainz genre vocabulary
    (drops Last.fm noise like 'seen live'); order = Last.fm rank."""
    params = urllib.parse.urlencode(
        {"method": "artist.getinfo", "artist": artist_name, "api_key": api_key, "format": "json"}
    )
    try:
        client._throttle()
        with urllib.request.urlopen(
            urllib.request.Request(f"{LASTFM_API}?{params}", headers={"User-Agent": client.user_agent}),
            timeout=30,
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tags = (data.get("artist") or {}).get("tags", {}).get("tag", []) or []
        if isinstance(tags, dict):
            tags = [tags]
        folded_vocab = {_fold(v) for v in client.mb_vocab}
        return [
            t["name"].strip()
            for t in tags
            if _fold(t.get("name", "")) in folded_vocab
        ][:LASTFM_FALLBACK_MAX]
    except Exception as e:
        print(f"  [lastfm] lookup failed for {artist_name!r}: {e}", flush=True)
        return []


# ---------------------------------------------------------------- persistence


class Cache:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS file (
                path TEXT PRIMARY KEY,
                rgid TEXT, artist_mbid TEXT, artist_name TEXT,
                rg_key TEXT, cur_genre TEXT, has_genres INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS mb_fetch (
                key TEXT PRIMARY KEY,            -- 'rg:<mbid>' | 'artist:<mbid>'
                payload TEXT, fetched_at REAL
            );
            CREATE TABLE IF NOT EXISTS lastfm (
                artist_mbid TEXT PRIMARY KEY, payload TEXT, fetched_at REAL
            );
            CREATE TABLE IF NOT EXISTS vocab (names_json TEXT);
            CREATE INDEX IF NOT EXISTS file_rg ON file(rg_key);
            """
        )
        self.db.commit()

    # files ---------------------------------------------------------------
    def upsert_file(self, path, rgid, artist_mbid, artist_name, rg_key, cur_genre, has_genres):
        self.db.execute(
            "INSERT INTO file(path, rgid, artist_mbid, artist_name, rg_key, cur_genre, has_genres)"
            " VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(path) DO UPDATE SET rgid=?, artist_mbid=?, artist_name=?,"
            " rg_key=?, cur_genre=?, has_genres=?",
            (path, rgid, artist_mbid, artist_name, rg_key, cur_genre, int(has_genres),
             rgid, artist_mbid, artist_name, rg_key, cur_genre, int(has_genres)),
        )

    def files(self):
        return self.db.execute(
            "SELECT path, artist_name, cur_genre, has_genres, rgid, artist_mbid FROM file"
        )

    def distinct_rgs(self):
        """(rgid, artist_mbid, artist_name) — one row per release-group, plus
        the artist name to use for a Last.fm lookup if needed."""
        return self.db.execute(
            """
            SELECT rg_key,
                   MAX(artist_mbid) AS artist_mbid,
                   (SELECT artist_name FROM file f2
                     WHERE f2.rg_key = file.rg_key AND artist_name IS NOT NULL LIMIT 1)
                   AS artist_name
            FROM file WHERE rg_key IS NOT NULL GROUP BY rg_key
            """
        )

    def distinct_artists(self):
        return self.db.execute(
            "SELECT artist_mbid, MAX(artist_name) FROM file"
            " WHERE artist_mbid IS NOT NULL GROUP BY artist_mbid"
        )

    # fetch cache ----------------------------------------------------------
    @staticmethod
    def _split(key: str):
        kind, _, value = key.partition(":")
        return kind, value

    def cached_fetch(self, key: str):
        row = self.db.execute(
            "SELECT payload FROM mb_fetch WHERE key=?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def store_fetch(self, key: str, payload: dict, table_value_id: str | None = None):
        now = time.time()
        self.db.execute(
            "INSERT INTO mb_fetch(key, payload, fetched_at) VALUES(?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET payload=?, fetched_at=?",
            (key, json.dumps(payload), now, json.dumps(payload), now),
        )

    def rg_genres(self, rgid: str) -> list[dict]:
        payload = self.cached_fetch(f"rg:{rgid}")
        return (payload or {}).get("genres", [])

    def artist_genres(self, mbid: str) -> list[dict]:
        payload = self.cached_fetch(f"artist:{mbid}")
        return (payload or {}).get("genres", [])

    def lastfm_names(self, artist_mbid: str) -> list[str]:
        row = self.db.execute(
            "SELECT payload FROM lastfm WHERE artist_mbid=?", (artist_mbid,)
        ).fetchone()
        return (json.loads(row[0]) if row else {}).get("names", [])

    def store_lastfm(self, artist_mbid: str, names: list[str]):
        now = time.time()
        self.db.execute(
            "INSERT INTO lastfm(artist_mbid, payload, fetched_at) VALUES(?,?,?)"
            " ON CONFLICT(artist_mbid) DO UPDATE SET payload=?, fetched_at=?",
            (artist_mbid, json.dumps({"names": names}), now,
             json.dumps({"names": names}), now),
        )

    # vocab ------------------------------------------------------------------
    def store_vocab(self, names: list[str]):
        self.db.execute("DELETE FROM vocab")
        self.db.execute("INSERT INTO vocab(names_json) VALUES(?)", (json.dumps(sorted(names)),))

    def vocab(self):
        row = self.db.execute("SELECT names_json FROM vocab").fetchone()
        return set(json.loads(row[0])) if row else None

    def commit(self):
        self.db.commit()

    def close(self):
        self.db.close()


# ---------------------------------------------------------------- tag I/O


def _load_id3(path: str):
    """Existing ID3 for the file, or an empty tag object for files without one."""
    from mutagen.id3 import ID3
    try:
        return ID3(path)
    except Exception:
        return ID3()


def read_file_state(path: str):
    """(rgid, artist_mbid, artist_name, cur_genre_list) for one audio file."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".mp3":
        from mutagen.id3 import ID3
        tags = ID3(path)
        rgid, artist_mbid = parse_mbids_from_id3(tags)
        tpe1 = tags.getall("TPE1")
        artist_name = str(tpe1[0].text[0]) if tpe1 and tpe1[0].text else None
        tcon = tags.getall("TCON")
        cur_genre = [str(v) for f in tcon for v in f.text] or None
        return rgid, artist_mbid, artist_name, cur_genre
    if ext == ".flac":
        from mutagen.flac import FLAC
        meta = FLAC(path)
        rgid, artist_mbid = parse_mbids_from_vorbis(meta.tags)
        arts = (meta.tags or {}).get("artist") or []
        return rgid, artist_mbid, (arts[0] if arts else None), (meta.tags or {}).get("genre") or None
    if ext in (".ogg", ".opus"):
        if ext == ".ogg":
            from mutagen.oggvorbis import OggVorbis
            meta = OggVorbis(path)
        else:
            from mutagen.oggopus import OggOpus
            meta = OggOpus(path)
        rgid, artist_mbid = parse_mbids_from_vorbis(meta.tags)
        arts = (meta.tags or {}).get("artist") or []
        return rgid, artist_mbid, (arts[0] if arts else None), (meta.tags or {}).get("genre") or None
    return None, None, None, None


def write_genres(path: str, genres: list[str], overwrite: bool) -> bool:
    """Write ONE canonical genre per file: gonic treats the genre tag as an
    opaque string (no splitting), so a '; '-joined multi-genre would surface
    as a single mega-genre row. The primary (top-vote) genre wins."""
    ext = os.path.splitext(path)[1].lower()
    names = normalize_genres(genres)
    if not names:
        return False
    primary = names[0]
    if ext == ".mp3":
        from mutagen.id3 import ID3, TCON
        tags = _load_id3(path)
        existing = [v for f in tags.getall("TCON") for v in f.text if str(v).strip()]
        if existing and not overwrite:
            return False
        tags.delall("TCON")
        # encoding 1 = UTF-16 — the safely supported text encoding in ID3v2.3
        tags.add(TCON(encoding=1, text=[primary]))
        tags.save(path, v2_version=3)
        return True
    if ext == ".flac":
        from mutagen.flac import FLAC
        meta = FLAC(path)
        if (meta.tags or {}).get("genre") and not overwrite:
            return False
        meta["GENRE"] = [primary]
        meta.save()
        return True
    if ext in (".ogg", ".opus"):
        if ext == ".ogg":
            from mutagen.oggvorbis import OggVorbis
            meta = OggVorbis(path)
        else:
            from mutagen.oggopus import OggOpus
            meta = OggOpus(path)
        if (meta.tags or {}).get("genre") and not overwrite:
            return False
        meta["GENRE"] = [primary]
        meta.save()
        return True
    return False


# ---------------------------------------------------------------- pipeline


def scan(music_dir: str, cache: Cache) -> int:
    count = 0
    problems = []
    for root, _dirs, files in os.walk(music_dir):
        for name in sorted(files):
            if not name.lower().endswith(MUSIC_EXTS):
                continue
            path = os.path.join(root, name)
            try:
                rgid, artist_mbid, artist_name, cur_genre = read_file_state(path)
            except Exception as e:
                problems.append((path, f"{type(e).__name__}: {e}"))
                continue
            has_genres = bool(cur_genre and any(g.strip() for g in cur_genre))
            cache.upsert_file(
                path, rgid, artist_mbid, artist_name, rgid or None,
                "; ".join(cur_genre) if cur_genre else None, has_genres,
            )
            count += 1
            if count % 1000 == 0:
                cache.commit()
                print(f"  [scan] {count} files…", flush=True)
    cache.commit()
    for path, err in problems[:20]:
        print(f"  [scan] READ FAIL {path}: {err}")
    if len(problems) > 20:
        print(f"  [scan] … and {len(problems) - 20} more read failures")
    return count


def fetch_all(cache: Cache, client: RateLimitedClient, use_lastfm: bool, refresh_lastfm: bool = False):
    """MB genres for every release-group + artist (cached, resumable);
    vocabulary cache; Last.fm only where MB came up empty."""
    if refresh_lastfm:
        cache.db.execute("DELETE FROM lastfm")
        cache.commit()
        print("[fetch] lastfm cache wiped (—refresh-lastfm)", flush=True)
    if cache.vocab() is None:
        print("[fetch] genre vocabulary…", flush=True)
        vocab = fetch_mb_genre_vocabulary(client)
        cache.store_vocab(sorted(vocab))
        cache.commit()
        print(f"[fetch] vocabulary: {len(vocab)} genres")
    client.mb_vocab = cache.vocab()

    rgs = cache.distinct_rgs().fetchall()
    for i, (rg_key, _artist_mbid, _name) in enumerate(rgs, 1):
        if cache.cached_fetch(f"rg:{rg_key}") is not None:
            continue
        cache.store_fetch(f"rg:{rg_key}", {"genres": fetch_mb_genres(client, "release-group", rg_key)})
        if i % 50 == 0:
            cache.commit()
            print(f"  [fetch] release-groups {i}/{len(rgs)}", flush=True)
    cache.commit()
    print(f"[fetch] release-groups: {len(rgs)}")

    artists = cache.distinct_artists().fetchall()
    for i, (artist_mbid, _name) in enumerate(artists, 1):
        key = f"artist:{artist_mbid}"
        if cache.cached_fetch(key) is not None:
            continue
        cache.store_fetch(key, {"genres": fetch_mb_genres(client, "artist", artist_mbid)})
        if i % 50 == 0:
            cache.commit()
            print(f"  [fetch] artists {i}/{len(artists)}", flush=True)
    cache.commit()
    print(f"[fetch] artists: {len(artists)}")

    if use_lastfm:
        api_key = os.getenv("LASTFM_API_KEY", "").strip()
        if not api_key:
            print("[fetch] LASTFM_API_KEY not set — skipping Last.fm fallback")
        else:
            client.mb_vocab = cache.vocab() or set()
            needing = []
            for artist_mbid, artist_name in artists:
                if qualifying(cache.artist_genres(artist_mbid), MIN_VOTES):
                    continue
                # candidate only if some rg of this artist is ALSO without qualifying rg genres? —
                # simpler: fallback per artist whose own data is empty; report shows origin.
                needing.append((artist_mbid, artist_name or ""))
            needing = [(m, n) for m, n in needing if not cache.lastfm_names(m)]
            print(f"[fetch] lastfm fallback: {len(needing)} artists")
            for artist_mbid, artist_name in needing:
                if not artist_name:
                    continue
                names = fetch_lastfm_genres(client, artist_name, api_key)
                cache.store_lastfm(artist_mbid, names)
                cache.commit()
            print("[fetch] lastfm pass done", flush=True)
    print("[fetch] done", flush=True)


def build_plan(cache: Cache):
    """[(album_dir, files, genres, source, tagged, total)] — cache-only."""
    albums = {}
    for path, artist_name, cur_genre, has_genres, rgid, artist_mbid in cache.files():
        album_dir = os.path.dirname(path)
        info = albums.setdefault(
            album_dir,
            {"files": [], "rgid": rgid, "artist_mbid": artist_mbid,
             "artist_name": artist_name, "tagged": 0, "total": 0},
        )
        info["files"].append(path)
        info["total"] += 1
        info["tagged"] += int(bool(has_genres))

    plan = []
    for album_dir in sorted(albums):
        info = albums[album_dir]
        # Compilation policy (owner decision): various-artists folders get the
        # literal genre regardless of what MB/Last.fm would say.
        if any(part.lower() == "compilations" for part in album_dir.split(os.sep)):
            plan.append((album_dir, info["files"], ["Compilation"], "compilation",
                         info["tagged"], info["total"], info["artist_name"], info["rgid"]))
            continue
        rg_genres = cache.rg_genres(info["rgid"]) if info["rgid"] else []
        artist_genres = cache.artist_genres(info["artist_mbid"]) if info["artist_mbid"] else []
        lastfm_names = cache.lastfm_names(info["artist_mbid"]) if info["artist_mbid"] else []
        genres, source = select_genres(rg_genres, artist_genres, lastfm_names)
        plan.append(
            (album_dir, info["files"], genres, source,
             info["tagged"], info["total"], info["artist_name"], info["rgid"])
        )
    return plan


def write_report(plan, out_path: str | None) -> dict[str, int]:
    by_source: dict[str, int] = {}
    for _d, _f, genres, source, *_ in plan:
        by_source[source] = by_source.get(source, 0) + 1
    lines = [
        "# Genre enrichment dry-run report",
        "",
        f"albums: {len(plan)}   " + "   ".join(f"{s}: {c}" for s, c in sorted(by_source.items())),
        "",
        "| album | genre | source |",
        "|---|---|---|",
    ]
    for album_dir, _f, genres, source, *_ in plan:
        parent = os.path.basename(os.path.dirname(album_dir))
        rel = f"{parent} / {os.path.basename(album_dir)}"
        lines.append(f"| {rel} | {'; '.join(genres) if genres else '— stays untagged'} | {source} |")
    text = "\n".join(lines) + "\n"
    out_path = out_path or "genre_report.md"
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return by_source


def apply_plan(plan, overwrite: bool) -> tuple[int, int]:
    written = skipped = 0
    for album_dir, files, genres, source, tagged, total, *_ in plan:
        if not genres or source == "none":
            skipped += 1
            continue
        if tagged >= total and total > 0:
            skipped += 1  # album already fully tagged
            continue
        for path in files:
            try:
                if write_genres(path, genres, overwrite=overwrite):
                    written += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"  [write] FAIL {path}: {type(e).__name__}: {e}", flush=True)
        if written and written % 200 == 0:
            print(f"  [write] {written} files…", flush=True)
    return written, skipped


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dir", default=os.getenv("MUSIC_DIR", "/mnt/music/collection"))
    p.add_argument("--cache", default=os.getenv("GENRE_CACHE", "/home/pi/genre_enrichment.sqlite3"))
    p.add_argument("--report", default="/home/pi/genre_report.md")
    p.add_argument("--write", action="store_true", help="actually write tags (default dry-run)")
    p.add_argument("--overwrite", action="store_true", help="also tag already-tagged files")
    p.add_argument("--no-fetch", action="store_true", help="cache only, no MB/lastfm queries")
    p.add_argument("--no-lastfm", action="store_true", help="disable Last.fm fallback")
    p.add_argument("--refresh-lastfm", action="store_true",
                   help="wipe cached Last.fm results and re-fetch with current filters")
    args = p.parse_args(argv)

    # DNS returns AAAA first on this box; prefer IPv4 so a broken IPv6 route
    # can't blackhole every request. Falls back to IPv6 if IPv4 is absent.
    _orig_getaddrinfo = socket.getaddrinfo

    def ipv4_first(*fargs, **kwargs):
        res = _orig_getaddrinfo(*fargs, **kwargs)
        return sorted(res, key=lambda r: r[0] != socket.AF_INET)

    socket.getaddrinfo = ipv4_first

    cache = Cache(args.cache)
    n = scan(args.dir, cache)
    print(f"[scan] {n} files")

    if not args.no_fetch:
        fetch_all(cache, RateLimitedClient(), use_lastfm=not args.no_lastfm,
                  refresh_lastfm=args.refresh_lastfm)

    plan = build_plan(cache)
    by_source = write_report(plan, args.report)
    print(f"[report] {args.report} | {by_source}")

    if args.write:
        w, s = apply_plan(plan, overwrite=args.overwrite)
        print(f"[write] {w} files written, {s} albums/albums-files skipped")
        print("[write] next: rescan gonic so Subsonic exposes the genres")
    else:
        print("[dry-run] review the report, then re-run with --write")
    cache.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())