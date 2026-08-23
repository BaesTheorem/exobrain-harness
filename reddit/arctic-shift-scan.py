#!/usr/bin/env python3
"""Scan a subreddit's full post stream via the Arctic Shift archive API.

Pulls EVERY post from the last N days (not just megathreads), plus full
comment trees for megathread-shaped posts, into a JSON snapshot that the
/local-events skill reads and judges. The script fetches and annotates;
it deliberately does NOT decide what counts as an event. That judgment
stays with the model pass that reads the snapshot.

INVARIANTS (do not break when editing):
- STALENESS IS CONTENT, NOT STATUS: Arctic Shift's dangerous failure mode
  is silent-stale-200 (PullPush served >1yr-old data with clean 200s).
  The freshness assertion on newest-post age must never be removed, and
  a stale result must set status "stale" in the output, never crash.
- SILENT-SKIP DEGRADATION: network/HTTP failure writes status "blocked"
  to the snapshot and exits 0. Watchers must never false-alarm on a
  fragile channel (Gatorade-watcher discipline).
- PACING: >=1s between requests. Arctic Shift is one volunteer's server.
- No Reddit credentials touch this script, ever.

Recon backing: ~/Exobrain/recon/2026-08-23-reddit-access-paths.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API = "https://arctic-shift.photon-reddit.com/api"
UA = "exobrain-local-events/1.0 (personal, low-volume)"
PACE_SECONDS = 1.1
STALE_AFTER_HOURS = 48.0
# NB: "permalink" and "url" are rejected (400) by /api/posts/search's
# fields param; build the permalink from the id instead.
POST_FIELDS = (
    "id,title,selftext,author,link_flair_text,created_utc,num_comments,score"
)
# Title-based only: the "Things To Do" flair is shared by ~26 ordinary
# event posts a week, so flair alone would trigger a comment-tree fetch
# per post. Only recurring-thread titles mark a megathread.
MEGATHREAD_TITLE = re.compile(
    r"what'?s happening|weekly.*(thread|events)|this week(end)? in", re.I
)

_last_request_at = 0.0


def _get(url: str) -> Any:
    """Paced GET returning parsed JSON. Raises on HTTP/network failure."""
    global _last_request_at
    wait = PACE_SECONDS - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
    _last_request_at = time.monotonic()
    return json.loads(body)


def fetch_posts(subreddit: str, since_epoch: int) -> list[dict[str, Any]]:
    """Page through every post since `since_epoch`, oldest first."""
    posts: list[dict[str, Any]] = []
    cursor = since_epoch
    while True:
        params = urllib.parse.urlencode(
            {
                "subreddit": subreddit,
                "after": cursor,
                "sort": "asc",
                "limit": 100,
                "fields": POST_FIELDS,
            }
        )
        batch = _get(f"{API}/posts/search?{params}").get("data", [])
        if not batch:
            break
        posts.extend(batch)
        newest = max(int(p["created_utc"]) for p in batch)
        if len(batch) < 100:
            break
        cursor = newest  # 'after' is exclusive-ish; dedupe below handles overlap
    seen: set[str] = set()
    unique = []
    for p in posts:
        if p["id"] not in seen:
            seen.add(p["id"])
            p["permalink"] = f"https://reddit.com/r/{subreddit}/comments/{p['id']}/"
            unique.append(p)
    return unique


def is_megathread(post: dict[str, Any]) -> bool:
    return bool(MEGATHREAD_TITLE.search(post.get("title") or ""))


def fetch_comment_tree(link_id: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"link_id": f"t3_{link_id}", "limit": 9999})
    tree = _get(f"{API}/comments/tree?{params}").get("data", [])
    flat: list[dict[str, Any]] = []

    def walk(nodes: list[dict[str, Any]], depth: int) -> None:
        for node in nodes:
            data = node.get("data", node)
            body = data.get("body")
            if body and body not in ("[deleted]", "[removed]"):
                flat.append(
                    {
                        "author": data.get("author"),
                        "body": body,
                        "score": data.get("score"),
                        "depth": depth,
                    }
                )
            walk(node.get("children") or data.get("children") or [], depth + 1)

    walk(tree, 0)
    return flat


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0] if __doc__ else ""
    )
    ap.add_argument("--sub", default="kansascity")
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "data" / "kc-events-scan.json",
    )
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    since = int(now.timestamp() - args.days * 86400)
    snapshot: dict[str, Any] = {
        "subreddit": args.sub,
        "fetched_at": now.isoformat(),
        "window_days": args.days,
        "source": "arctic-shift",
    }

    try:
        posts = fetch_posts(args.sub, since)
        megathreads = [p for p in posts if is_megathread(p)]
        for mt in megathreads:
            mt["comments"] = fetch_comment_tree(mt["id"])

        newest_age_h = (
            (now.timestamp() - max(int(p["created_utc"]) for p in posts)) / 3600
            if posts
            else float("inf")
        )
        snapshot.update(
            {
                # Stale archive still 200s; assert on content age (INVARIANTS)
                "status": "stale" if newest_age_h > STALE_AFTER_HOURS else "ok",
                "newest_post_age_hours": round(newest_age_h, 1),
                "post_count": len(posts),
                "megathread_count": len(megathreads),
                "posts": posts,
            }
        )
    except Exception as exc:  # noqa: BLE001 -- silent-skip contract (INVARIANTS)
        snapshot.update({"status": "blocked", "error": str(exc)})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snapshot, indent=1))
    print(
        f"[{snapshot['status']}] {snapshot.get('post_count', 0)} posts, "
        f"{snapshot.get('megathread_count', 0)} megathreads, "
        f"newest {snapshot.get('newest_post_age_hours', '?')}h -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
