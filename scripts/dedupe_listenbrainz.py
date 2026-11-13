#!/usr/bin/env python3
"""Find and optionally delete ListenBrainz duplicate listens.

The common duplicate is one play submitted twice:

- ``gonic`` submitted it directly to ListenBrainz;
- the ListenBrainz Last.fm importer imported the same play from Last.fm
  (``submission_client`` = ``ListenBrainz lastfm importer v2``).

They share ``listened_at``, artist and track (title casing may differ).
This tool groups those pairs, keeps the gonic copy, and optionally deletes
the importer copy through ``POST /1/delete-listen``.

Safety:
- dry-run by default; nothing is deleted without ``--execute --yes``;
- keeps one gonic copy when present, otherwise the earliest importer copy;
  deletes only the extra importer copies;
- writes the full deletion plan to a JSON file first;
- requires ``LB_TOKEN`` (ListenBrainz user token) for deletion;
- rate-limits itself to ~1 request/second.

Example:
    LB_USER=mhinge python3 scripts/dedupe_listenbrainz.py --user mhinge
    LB_TOKEN=... python3 scripts/dedupe_listenbrainz.py --user mhinge --execute --yes

The delete endpoint schedules deletion shortly after the hour; it is not
instant. Run an export first if you want a full backup.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

BASE = "https://api.listenbrainz.org/1"
USER_AGENT = "jukeplayer-dedupe/1.0 (+https://github.com/kaninfod/jukeplayer_backend)"
IMPORTER_MARKER = "lastfm importer"


def fold(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def submission_client(listen: dict) -> str:
    meta = listen.get("track_metadata") or {}
    info = meta.get("additional_info") or {}
    return str(info.get("submission_client") or info.get("client") or "")


def is_importer(listen: dict) -> bool:
    return IMPORTER_MARKER in submission_client(listen).lower()


def is_gonic(listen: dict) -> bool:
    return submission_client(listen).lower() == "gonic"


def listen_key(listen: dict) -> tuple:
    """Same timestamp + normalized artist/track is a duplicate pair."""
    meta = listen.get("track_metadata") or {}
    return (
        int(listen.get("listened_at") or 0),
        fold(meta.get("artist_name")),
        fold(meta.get("track_name")),
    )


def listen_identity(listen: dict) -> tuple:
    """A listen is identified by (listened_at, recording_msid).

    ``recording_msid`` is a recording ID shared by every play of the same
    recording, not a per-listen ID; using it alone collapses the history.
    """
    msid = str(listen.get("recording_msid") or "")
    if msid:
        return (int(listen.get("listened_at") or 0), msid)
    return listen_key(listen) + (submission_client(listen),)


def _request(path: str, params: dict | None = None, token: str = "",
             body: dict | None = None) -> dict:
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode()
        return json.loads(raw) if raw.strip() else {}


def fetch_listens(user: str, token: str = "") -> list[dict]:
    """Fetch the full listen history, paginating on max_ts.

    ``max_ts`` is exclusive, so it is stepped to ``oldest - 1`` to avoid
    skipping the second copy of a duplicate pair that shares the page
    boundary timestamp. Duplicate rows are removed by recording_msid.
    """
    collected: list[dict] = []
    seen: set[tuple] = set()
    max_ts = None
    for page in range(200):
        params: dict[str, object] = {"count": 1000}
        if max_ts is not None:
            params["max_ts"] = max_ts
        data = _request(f"/user/{urllib.parse.quote(user)}/listens", params, token)
        batch = (data.get("payload") or {}).get("listens") or []
        if not batch:
            break
        for listen in batch:
            key = listen_identity(listen)
            if key in seen:
                continue
            seen.add(key)
            collected.append(listen)
        oldest = min(int(item.get("listened_at") or 0) for item in batch)
        if len(batch) < 1000 or oldest <= 0:
            break
        max_ts = oldest - 1
        time.sleep(1.05)
    return collected


def plan_deletions(listens: list[dict]) -> tuple[list[dict], dict]:
    """Group duplicate plays and return (deletions, stats).

    A group keeps one copy: the gonic submission when present, otherwise
    the earliest importer copy. Every other importer copy is deleted.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for listen in listens:
        groups[listen_key(listen)].append(listen)

    deletions: list[dict] = []
    stats = {
        "listens": len(listens),
        "duplicate_groups": 0,
        "planned": 0,
        "untouched_groups": 0,
        "kept_gonic": 0,
        "kept_importer_only": 0,
        "skipped_missing_msid": 0,
    }

    def add_deletion(item: dict) -> None:
        if not item.get("recording_msid"):
            stats["skipped_missing_msid"] += 1
            return
        meta = item.get("track_metadata") or {}
        deletions.append({
            "listened_at": int(item.get("listened_at") or 0),
            "recording_msid": item.get("recording_msid"),
            "artist": meta.get("artist_name"),
            "track": meta.get("track_name"),
            "album": meta.get("release_name"),
            "client": submission_client(item),
        })

    for group in groups.values():
        if len(group) < 2:
            continue
        stats["duplicate_groups"] += 1
        gonic = [item for item in group if is_gonic(item)]
        importer = [item for item in group if is_importer(item)]

        if gonic:
            # Keep one direct gonic submission; delete every importer copy.
            stats["kept_gonic"] += 1
            for item in importer:
                add_deletion(item)
            continue

        if len(importer) > 1:
            # Repeated Last.fm imports: keep the earliest importer copy.
            keep = min(
                importer,
                key=lambda item: int(item.get("inserted_at") or item.get("listened_at") or 0),
            )
            stats["kept_importer_only"] += 1
            for item in importer:
                if item is not keep:
                    add_deletion(item)
            continue

        stats["untouched_groups"] += 1

    stats["planned"] = len(deletions)
    deletions.sort(key=lambda item: item["listened_at"])
    return deletions, stats


def delete_one(token: str, item: dict) -> None:
    body = {
        "listened_at": item["listened_at"],
        "recording_msid": item["recording_msid"],
    }
    _request("/delete-listen", token=token, body=body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.getenv("LB_USER", ""),
                        help="ListenBrainz username (or LB_USER)")
    parser.add_argument("--execute", action="store_true",
                        help="delete the planned importer copies (needs LB_TOKEN)")
    parser.add_argument("--yes", action="store_true",
                        help="skip the interactive confirmation for --execute")
    parser.add_argument("--limit", type=int, default=0,
                        help="maximum deletions to perform (testing)")
    parser.add_argument("--plan-file", default="",
                        help="write the deletion plan here (default: timestamped JSON)")
    args = parser.parse_args()

    if not args.user:
        parser.error("--user or LB_USER is required")
    token = os.environ.get("LB_TOKEN", "").strip()

    print(f"Fetching listens for {args.user} ...")
    listens = fetch_listens(args.user, token)
    deletions, stats = plan_deletions(listens)

    print(f"listens: {stats['listens']}")
    print(f"duplicate groups: {stats['duplicate_groups']}")
    print(f"planned deletions: {stats['planned']} (extra importer copies)")
    print(f"kept groups: {stats['kept_gonic']} with gonic, "
          f"{stats['kept_importer_only']} importer-only")
    print(f"skipped (missing MSID): {stats['skipped_missing_msid']}")
    print(f"groups left untouched: {stats['untouched_groups']}")

    for item in deletions[:10]:
        stamp = datetime.fromtimestamp(item["listened_at"], tz=timezone.utc).isoformat()
        print(f"  delete {stamp} | {item['artist']} — {item['track']} | {item['client']}")
    if len(deletions) > 10:
        print(f"  ... {len(deletions) - 10} more")

    plan_path = args.plan_file or (
        "lb_dedupe_plan_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    with open(plan_path, "w", encoding="utf-8") as handle:
        json.dump({"stats": stats, "deletions": deletions}, handle, indent=2)
    print(f"plan written to {plan_path}")

    if not args.execute:
        print("Dry run. Re-run with --execute --yes and LB_TOKEN set to delete.")
        return 0

    if not token:
        print("LB_TOKEN is required for --execute.", file=sys.stderr)
        return 2
    if not deletions:
        print("Nothing to delete.")
        return 0
    if not args.yes:
        answer = input(f"Delete {len(deletions)} listens? Type 'delete' to proceed: ")
        if answer.strip().lower() != "delete":
            print("Aborted.")
            return 1

    todo = deletions[:args.limit] if args.limit else deletions
    failed = 0
    for index, item in enumerate(todo, 1):
        try:
            delete_one(token, item)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                reset = exc.headers.get("X-RateLimit-Reset-In")
                delay = min(60.0, float(reset) if reset else 2.0)
                print(f"rate limited; sleeping {delay:.0f}s")
                time.sleep(delay)
                try:
                    delete_one(token, item)
                except Exception as retry_exc:  # noqa: BLE001
                    failed += 1
                    print(f"  failed {item['listened_at']}: {retry_exc}")
            elif exc.code in (401, 403):
                print("Token rejected; stopping.", file=sys.stderr)
                return 2
            else:
                failed += 1
                print(f"  failed {item['listened_at']}: HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  failed {item['listened_at']}: {exc}")
        if index % 25 == 0 or index == len(todo):
            print(f"deleted {index}/{len(todo)} ({failed} failed)")
        time.sleep(1.05)

    print("Done. ListenBrainz schedules deletions shortly after the hour.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
