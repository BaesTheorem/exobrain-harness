#!/usr/bin/env python3
"""Harvest r/kansascity threads about USPS delays and the tracking screenshots in them.

Reads the Arctic Shift archive (no Reddit credentials). Writes
../data/threads.json (post metadata + comments that mention a KC plant)
and downloads every i.redd.it / preview.redd.it image in those comments
to ../data/img/. Paced for one volunteer's server.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://arctic-shift.photon-reddit.com/api"
UA = "exobrain-harness/1.0 (+https://github.com/BaesTheorem/exobrain-harness)"
OUT = Path(__file__).resolve().parent.parent / "data"
IMG = OUT / "img"
TERMS = ["USPS", "post office", "package", "mail", "postal", "distribution center", "KCK"]
KEEP = re.compile(r"usps|postal|post office|distribution|kck|package|parcel|mail", re.I)
PLANT = re.compile(r"kck|kcmo|distribution|distro|loop|bounc|speaker|cleveland|olathe|gardner", re.I)
IMG_RE = re.compile(r"https://(?:i\.redd\.it|preview\.redd\.it)/[A-Za-z0-9_.-]+\.(?:jpe?g|png|webp)[^\s)\]]*")


def get(url: str, tries: int = 5) -> dict:
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.load(r)
        except Exception as e:  # noqa: BLE001 - network errors retry
            d = {"error": str(e)}
        if d.get("data") is not None:
            return d
        wait = 30 * (i + 1)
        print(f"  retry in {wait}s: {d.get('error')}", file=sys.stderr)
        time.sleep(wait)
    return {"data": None}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    IMG.mkdir(exist_ok=True)
    posts: dict[str, dict] = {}
    for term in TERMS:
        q = urllib.parse.urlencode({"subreddit": "kansascity", "title": term, "limit": 100,
                                    "after": "2023-01-01", "sort": "desc",
                                    "fields": "id,title,created_utc,num_comments,score,selftext"})
        d = get(f"{API}/posts/search?{q}")
        for p in d.get("data") or []:
            if KEEP.search(p["title"]):
                posts[p["id"]] = p
        print(f"{term}: {len(posts)} posts so far", file=sys.stderr)
        time.sleep(30)
    rows = []
    for pid, p in sorted(posts.items(), key=lambda kv: kv[1]["created_utc"]):
        if p.get("num_comments", 0) == 0 and not PLANT.search(p.get("selftext") or ""):
            rows.append({**p, "comments": []})
            continue
        d = get(f"{API}/comments/tree?link_id=t3_{pid}&limit=9999")
        time.sleep(2)
        hits: list[dict] = []

        def walk(nodes: list, hits: list[dict] = hits) -> None:
            for n in nodes:
                c = n.get("data", n)
                body = c.get("body") or ""
                if body and (PLANT.search(body) or IMG_RE.search(body)):
                    hits.append({"id": c.get("id"), "created_utc": c.get("created_utc"),
                                 "score": c.get("score"), "body": body,
                                 "imgs": IMG_RE.findall(body)})
                kids = c.get("children") or []
                if kids and isinstance(kids[0], dict):
                    walk(kids, hits)
        walk(d.get("data") or [])
        rows.append({**p, "comments": hits})
        for h in hits:
            for u in h["imgs"]:
                name = re.sub(r"[^A-Za-z0-9_.-]", "_", urllib.parse.urlparse(u).path.strip("/"))
                dest = IMG / f"{pid}_{h['id']}_{name}"
                if dest.exists():
                    continue
                try:
                    req = urllib.request.Request(u.replace("&amp;", "&"), headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        dest.write_bytes(r.read())
                except Exception as e:  # noqa: BLE001
                    print(f"  img fail {u}: {e}", file=sys.stderr)
                time.sleep(1.2)
    (OUT / "threads.json").write_text(json.dumps(rows, indent=1))
    n_img = len(list(IMG.iterdir()))
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"done {stamp}: {len(rows)} posts, {sum(len(r['comments']) for r in rows)} plant comments, {n_img} images")


if __name__ == "__main__":
    main()
