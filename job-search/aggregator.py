#!/usr/bin/env python3
"""ATS-wide discovery lane for /job-search, from an open daily dataset.

github.com/Feashliaa/job-board-aggregator (MIT) scrapes every public board it
knows on seven ATS platforms (Workday, iCIMS, Greenhouse, Paylocity, BambooHR,
Ashby, Lever) and publishes the result once a day on GitHub Pages:

    https://riley-dorrington.github.io/job-board-data/data/chunks/jobs_manifest.json
    -> {"chunks": [...59 .json.gz...], "totalJobs": ~1.47M, "last_updated": ...}

The data repo moved from Feashliaa to Riley-Dorrington on 2026-10-18 and the
old Pages URL returns 404. If the manifest 404s again, read the clone URL in
the aggregator repo's workflow to find the new owner.

Each row: title, company, ats, location (free text), url (the employer's own
ATS posting), first_seen, skill_level, is_recruiter, salary. This lane reaches
employers that ats-watchlist.py and workday.py never see, because those only
poll boards already in the tracker.

Facts measured 2026-10-13:
  * `salary` is the project's lookup-table ESTIMATE (p25/median/p75 for the
    title), not the employer's posted band. It never counts for gate 3, so
    every row here is a LEAD until the posting itself is read.
  * There is no remote flag. Gate 1 reads the location text: "Remote" in the
    US at the standard floor, a KC-metro city at the onsite floor.
  * ~77 MB per full pass. Chunks are streamed and filtered one at a time; the
    8 GB Mac must never hold all 1.4M rows at once.

A seen-file (state/aggregator-seen.json, gitignored) keeps a run to postings it
has not shown before. Title, location and type gates come from moreboards.py.

Usage:
    python3 aggregator.py --days 3
    python3 aggregator.py --days 30 --all     # re-show rows seen before
"""

import argparse
import datetime as dt
import gzip
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comp_floors import comp_floor, onsite_floor  # noqa: E402
from moreboards import KC_METRO, REMOTE, gate, row  # noqa: E402

BASE = "https://riley-dorrington.github.io/job-board-data/data/chunks/"
STATE = Path(__file__).resolve().parent / "state" / "aggregator-seen.json"
SEEN_TTL_DAYS = 60


def fetch(name: str) -> bytes:
    req = urllib.request.Request(BASE + name, headers={"User-Agent": "job-search-lane"})
    for attempt in range(3):
        try:
            return urllib.request.urlopen(req, timeout=60).read()
        except OSError:
            if attempt == 2:
                raise
    return b""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="first_seen within N days")
    ap.add_argument("--all", action="store_true", help="print rows already shown on earlier runs")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()

    floor, onsite = comp_floor(), onsite_floor()
    today = dt.date.today()
    seen = json.loads(STATE.read_text()) if STATE.exists() else {}
    seen = {u: d for u, d in seen.items()
            if dt.date.fromisoformat(d) >= today - dt.timedelta(days=SEEN_TTL_DAYS)}
    # A failed run leaves a gap. Widen the window back to the last run that
    # wrote the seen-file; the seen-file still drops rows shown before.
    if seen and not a.all:
        gap = (today - dt.date.fromisoformat(max(seen.values()))).days + 1
        if gap > a.days:
            print(f"~ CATCH-UP: last run {max(seen.values())}, window widened {a.days}d -> {gap}d")
            a.days = gap
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=a.days)).isoformat()

    manifest = json.loads(fetch("jobs_manifest.json"))
    chunks = manifest["chunks"]
    print(f"job-board-aggregator | {manifest['totalJobs']:,} jobs | updated {manifest['last_updated'][:16]} | "
          f"{len(chunks)} chunks | window {a.days}d")
    stale = (dt.datetime.now(dt.timezone.utc)
             - dt.datetime.fromisoformat(manifest["last_updated"].replace("Z", "+00:00"))).days
    if stale > 2:
        print(f"~ STALE: dataset last updated {stale} days ago; new postings since then are missing")

    buckets: dict[str, list] = {k: [] for k in ("survivor", "lead", "decline", "drop")}
    failed, in_window, already = [], 0, 0
    shown: set[str] = set()
    for i, name in enumerate(chunks):
        try:
            rows = json.loads(gzip.decompress(fetch(name)))
        except Exception as e:  # noqa: BLE001  (one chunk failing is a reported gap, not a dead lane)
            failed.append(f"{name}: {str(e)[:60]}")
            continue
        for j in rows:
            if (j.get("first_seen") or "") < cutoff or j.get("is_recruiter"):
                continue
            loc = j.get("location") or ""
            if not (REMOTE.search(loc) or KC_METRO.search(loc)):
                continue
            in_window += 1
            url = j.get("url")
            if not url or url in shown:
                continue
            shown.add(url)
            if url in seen and not a.all:
                already += 1
                continue
            r = row("aggregator", j.get("title"), j.get("company"), loc, url,
                    remote=bool(REMOTE.search(loc)) and not KC_METRO.search(loc) or None,
                    posted=dt.date.fromisoformat(j["first_seen"][:10]),
                    extra=f"{j.get('ats')}, {j.get('skill_level') or '?'} level")
            verdict, why = gate(r, floor, onsite)
            buckets[verdict].append((r, why))
        del rows
        if (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{len(chunks)} chunks", flush=True)

    print(f"\n{in_window} remote/KC rows first seen in window | {already} already shown | "
          f"{len(buckets['lead'])} leads | {len(buckets['decline'])} declined | "
          f"{len(buckets['drop'])} title-dropped")
    for f in failed:
        print(f"~ COVERAGE GAP: {f}")
    print("\nLEADS -- the posting decides comp (aggregator salary is an estimate)")
    for r, why in sorted(buckets["lead"], key=lambda x: (x[0]["where"], x[0]["company"])):
        print(f"  {r['title']} @ {r['company']} | {r['where']} | first seen {r['posted']} | "
              f"{r['extra']}  {why}")
        print(f"    {r['url']}")

    if not a.no_save:
        for u in shown:
            seen.setdefault(u, today.isoformat())
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(seen, indent=0, sort_keys=True))


if __name__ == "__main__":
    main()
