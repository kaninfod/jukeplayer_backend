"""The collection ledger — the record-store's record of deliberately added
albums (the album-store principle: the local source IS the collection; the
online albums enter it one explicit "add" at a time).

A tiny sqlite, one table. The identity = (pid, aid) — the same tuple a
future RFID card carries; the metadata is the add-time SNAPSHOT (the shelf
renders offline; play time always re-resolves from the source).
"""
import datetime
import os
import sqlite3
from typing import List, Optional

import logging

logger = logging.getLogger(__name__)


class AlbumStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or "data/collection.db"
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS collection_albums (
                    pid TEXT NOT NULL,
                    aid TEXT NOT NULL,
                    title TEXT,
                    artist TEXT,
                    year TEXT,
                    thumb TEXT,
                    track_count INTEGER,
                    added_at TEXT,
                    origin TEXT,
                    PRIMARY KEY (pid, aid)
                )
            """)

    def add_album(self, pid: str, aid: str, title: str = "", artist: str = "",
                  year: str = "", thumb: str = "", track_count: int = 0,
                  origin: str = "api") -> dict:
        """Insert or refresh the snapshot; the added_at keeps the FIRST add
        unless the row was empty (the re-add refreshes its text only)."""
        now = datetime.datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT added_at FROM collection_albums WHERE pid=? AND aid=?",
                (pid, aid)).fetchone()
            added_at = existing["added_at"] if existing else now
            conn.execute("""
                INSERT INTO collection_albums (pid, aid, title, artist, year, thumb, track_count, added_at, origin)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(pid, aid) DO UPDATE SET
                    title=excluded.title, artist=excluded.artist, year=excluded.year,
                    thumb=excluded.thumb, track_count=excluded.track_count, origin=excluded.origin
            """, (pid, aid, title, artist, year, thumb, track_count, added_at, origin))
        logger.info(f"[AlbumStore] {origin}: added '{title}' ({pid}:{aid})")
        return self.get_album(pid, aid) or {"pid": pid, "aid": aid}

    def get_album(self, pid: str, aid: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM collection_albums WHERE pid=? AND aid=?", (pid, aid)).fetchone()
            return dict(row) if row else None

    def list_albums(self, pid: Optional[str] = None) -> List[dict]:
        """All ledger rows, newest-first. Optional source filter."""
        with self._connect() as conn:
            if pid:
                rows = conn.execute(
                    "SELECT * FROM collection_albums WHERE pid=? ORDER BY added_at DESC", (pid,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM collection_albums ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in rows]

    def artists(self, pid: Optional[str] = None) -> List[dict]:
        """The distinct added artists with their album counts (the library's
        virtual-artist rows)."""
        sql = "SELECT artist, COUNT(*) AS albums FROM collection_albums WHERE 1=1"
        params = []
        if pid:
            sql += " AND pid=?"
            params.append(pid)
        sql += " GROUP BY artist ORDER BY artist COLLATE NOCASE"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params)]

    def albums_by_artist(self, artist: str) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM collection_albums WHERE artist=? COLLATE NOCASE ORDER BY year",
                (artist,)).fetchall()
        return [dict(r) for r in rows]

    def remove_album(self, pid: str, aid: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM collection_albums WHERE pid=? AND aid=?", (pid, aid))
            removed = cur.rowcount > 0
        if removed:
            logger.info(f"[AlbumStore] removed {pid}:{aid}")
        return removed

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS c FROM collection_albums").fetchone()["c"])