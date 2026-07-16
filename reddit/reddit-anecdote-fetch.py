#!/usr/bin/env python3
"""Fetch posts + comment threads from a subreddit into an anonymized JSON corpus.

Generic anecdote-mining tool: point --sub at any topic community. Uses Reddit's public
`.json` endpoints (no PRAW, no API key) with a browser User-Agent, the same pattern
the local-events skill uses. Usernames are ANONYMIZED at ingest (one-way hash) so the
corpus can hold public post text without storing who wrote it. The corpus is written
under reddit/data/ which is gitignored.

Usage:
  python3 reddit-anecdote-fetch.py --sub <subreddit>
  python3 reddit-anecdote-fetch.py --sub <subreddit> --sort top --time year --pages 6
  python3 reddit-anecdote-fetch.py --sub <subreddit> --dry-run --pages 1   # ~25 posts, no comment fetch, sanity check

This is a read-only public-data pull. It does not log in and never posts.
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

HARNESS_DIR = Path(__file__).parent
DATA_DIR = HARNESS_DIR / "data"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) exobrain-anecdote-miner/1.0"

# Anonymization: one-way hash of author -> stable pseudonym within the corpus.
# We do NOT store a reverse map. A random per-machine salt would break cross-run
# stability, so we use a fixed project salt: good enough to avoid casual rainbow
# lookups of short handles while keeping the same author consistent across pages.
_SALT = "exobrain-as-anecdote-v1"


def anon(author):
    if not author or author in ("[deleted]", "[removed]"):
        return author or "[unknown]"
    h = hashlib.sha256((_SALT + author).encode()).hexdigest()[:10]
    return f"anon_{h}"


def get_json(url, tries=4):
    """GET a Reddit .json url, retrying on 429/5xx with backoff."""
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < tries - 1:
                wait = 2 ** attempt + 1
                print(f"  {e.code} on {url} — backing off {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  HTTP {e.code} on {url}", file=sys.stderr)
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < tries - 1:
                time.sleep(2 ** attempt + 1)
                continue
            print(f"  network error on {url}: {e}", file=sys.stderr)
            return None
    return None


def fetch_listing(sub, sort, tval, pages, pause):
    """Paginate a subreddit listing; return list of post-data dicts."""
    posts, after = [], None
    for page in range(pages):
        url = f"https://www.reddit.com/r/{sub}/{sort}.json?limit=100&raw_json=1"
        if tval and sort in ("top", "controversial"):
            url += f"&t={tval}"
        if after:
            url += f"&after={after}"
        data = get_json(url)
        if not data or "data" not in data:
            break
        children = data["data"].get("children", [])
        for c in children:
            if c.get("kind") == "t3":
                posts.append(c["data"])
        after = data["data"].get("after")
        print(f"  page {page+1}: +{len(children)} posts (total {len(posts)})", file=sys.stderr)
        if not after:
            break
        time.sleep(pause)
    return posts


def fetch_comments(sub, post_id, pause, top_n=40):
    """Fetch a post's comment thread; return flat list of anonymized comment dicts."""
    url = f"https://www.reddit.com/r/{sub}/comments/{post_id}.json?limit={top_n}&depth=3&raw_json=1"
    data = get_json(url)
    time.sleep(pause)
    if not data or len(data) < 2:
        return []
    out = []

    def walk(children):
        for c in children:
            if c.get("kind") != "t1":
                continue
            d = c.get("data", {})
            body = d.get("body", "")
            if body and body not in ("[deleted]", "[removed]"):
                out.append({
                    "author": anon(d.get("author")),
                    "body": body,
                    "score": d.get("score", 0),
                    "created_utc": d.get("created_utc"),
                })
            replies = d.get("replies")
            if isinstance(replies, dict):
                walk(replies.get("data", {}).get("children", []))

    walk(data[1].get("data", {}).get("children", []))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sub", required=True)
    ap.add_argument("--sort", default="top", choices=["top", "hot", "new", "controversial"])
    ap.add_argument("--time", dest="tval", default="year",
                    help="top/controversial window: hour|day|week|month|year|all")
    ap.add_argument("--pages", type=int, default=6, help="listing pages (100 posts each)")
    ap.add_argument("--also-all", action="store_true",
                    help="also pull top/all in addition to the primary sort")
    ap.add_argument("--pause", type=float, default=1.2, help="seconds between requests")
    ap.add_argument("--comments", type=int, default=40, help="top comments per post")
    ap.add_argument("--dry-run", action="store_true",
                    help="listing only, no comment threads (fast sanity check)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else DATA_DIR / f"{args.sub}-corpus.json"

    print(f"Fetching r/{args.sub} {args.sort} (t={args.tval}), {args.pages} pages...", file=sys.stderr)
    raw = fetch_listing(args.sub, args.sort, args.tval, args.pages, args.pause)
    if args.also_all:
        print("Also fetching top/all...", file=sys.stderr)
        raw += fetch_listing(args.sub, "top", "all", args.pages, args.pause)

    # Dedup by post id.
    seen, posts = set(), []
    for d in raw:
        pid = d.get("id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        posts.append(d)
    print(f"{len(posts)} unique posts.", file=sys.stderr)

    corpus = []
    for i, d in enumerate(posts):
        rec = {
            "id": d.get("id"),
            "title": d.get("title", ""),
            "selftext": d.get("selftext", ""),
            "author": anon(d.get("author")),
            "score": d.get("score", 0),
            "num_comments": d.get("num_comments", 0),
            "created_utc": d.get("created_utc"),
            "flair": d.get("link_flair_text"),
            "permalink": d.get("permalink"),
            "comments": [],
        }
        if not args.dry_run:
            rec["comments"] = fetch_comments(args.sub, rec["id"], args.pause, args.comments)
            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{len(posts)} threads fetched", file=sys.stderr)
        corpus.append(rec)

    payload = {
        "subreddit": args.sub,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sort": args.sort,
        "time": args.tval,
        "post_count": len(corpus),
        "comment_count": sum(len(c["comments"]) for c in corpus),
        "anonymized": True,
        "posts": corpus,
    }
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {out_path} — {payload['post_count']} posts, "
          f"{payload['comment_count']} comments.", file=sys.stderr)


if __name__ == "__main__":
    main()
