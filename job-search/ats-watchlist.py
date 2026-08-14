#!/usr/bin/env python3
"""ATS-direct watchlist for /job-search: poll employer boards, diff, surface new.

The point: cut search engines out of discovery entirely for employers we already
know about. Greenhouse, Lever, and Ashby all expose their FULL live posting list
through unauthenticated public APIs, so a daily poll has zero index lag and
complete coverage -- a posting that never crossposts anywhere still surfaces the
morning it goes up.

The watchlist builds itself from the vault: every note with `type: job-listing`
frontmatter (Job Listings folder AND Archive/) is scanned for board tokens in
its URLs. That automatically folds in the re-apply watchlist (`reapply: true`
employers are, by construction, in the tracker). Extra boards can be pinned in
state/watchlist-extra.json.

State lives in job-search/state/ (gitignored -- the employer list reveals where
Alex is applying). First poll of a board is a BASELINE: counts only, no "new"
spam. Subsequent polls print only postings not in the last snapshot.

Endpoints (all verified in use by this pipeline):
    greenhouse  https://boards-api.greenhouse.io/v1/boards/<board>/jobs
    lever       https://api.lever.co/v0/postings/<board>?mode=json
    ashby       https://api.ashbyhq.com/posting-api/job-board/<org>

Usage:
    python3 ats-watchlist.py                 # rescan vault, poll, diff, report
    python3 ats-watchlist.py --list          # just show the watchlist
    python3 ats-watchlist.py --full          # also dump current title-matched postings
"""

import argparse
import concurrent.futures
import json
import os
import re
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

VAULT = os.path.expanduser("~/Exobrain")
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
SNAPSHOT = os.path.join(STATE_DIR, "ats-snapshot.json")
EXTRA = os.path.join(STATE_DIR, "watchlist-extra.json")

# Boards that are aggregator middlemen, not employers -- polling them is noise.
BLOCKLIST = {"lever:jobgether", "greenhouse:jobgether"}

TOKEN_PATTERNS = [
    ("greenhouse", re.compile(r"boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([a-z0-9]+)")),
    ("greenhouse", re.compile(r"job-boards\.greenhouse\.io/([a-z0-9]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([a-zA-Z0-9-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9.-]+)")),
]

# Same include/drop title filter as nicheboards.py, so "new posting" output
# stays scoped to Alex's lane instead of every sales req a company opens.
DROP = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|manager|director|head of|architect|"
    r"engineer (iii|iv|v)|vp|vice president|chief|supervisory)\b", re.I)
KEEP = re.compile(
    r"\b(analyst|it support|it operations|it specialist|helpdesk|help desk|"
    r"service desk|security|identity|iam|grc|compliance|administrator|"
    r"m365|microsoft 365|intune|endpoint|desktop support|technical support|"
    r"fellow|fellowship)\b", re.I)


def _get_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def scan_vault():
    """Board tokens from every job-listing note, tracker and Archive alike."""
    boards = {}
    for root, dirs, files in os.walk(VAULT):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if not name.endswith(".md"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read(65536)
            except OSError:
                continue
            if "type: job-listing" not in text[:600]:
                continue
            for ats, pat in TOKEN_PATTERNS:
                for tok in pat.findall(text):
                    tok = tok.lower().rstrip("/.")
                    if tok in ("jobs", "v1", "embed"):
                        continue
                    key = "%s:%s" % (ats, tok)
                    if key not in BLOCKLIST:
                        boards.setdefault(key, set()).add(name[:-3])
    return {k: sorted(v) for k, v in sorted(boards.items())}


def load_extra():
    if os.path.exists(EXTRA):
        with open(EXTRA, encoding="utf-8") as f:
            return json.load(f)
    return {}


def poll(key):
    """Return {job_id: {title, loc, url}} for one board, or raise."""
    ats, tok = key.split(":", 1)
    out = {}
    if ats == "greenhouse":
        d = _get_json("https://boards-api.greenhouse.io/v1/boards/%s/jobs" % tok)
        for j in d.get("jobs", []):
            out[str(j["id"])] = {"title": j.get("title", ""),
                                 "loc": (j.get("location") or {}).get("name", ""),
                                 "url": j.get("absolute_url", "")}
    elif ats == "lever":
        d = _get_json("https://api.lever.co/v0/postings/%s?mode=json" % tok)
        for j in d:
            cats = j.get("categories") or {}
            out[j["id"]] = {"title": j.get("text", ""),
                            "loc": "%s | %s" % (cats.get("location", ""),
                                                cats.get("commitment", "")),
                            "url": j.get("hostedUrl", "")}
    elif ats == "ashby":
        d = _get_json("https://api.ashbyhq.com/posting-api/job-board/%s" % tok)
        for j in d.get("jobs", []):
            out[str(j.get("id"))] = {"title": j.get("title", ""),
                                     "loc": "%s | %s" % (j.get("location", ""),
                                                         j.get("employmentType", "")),
                                     "url": j.get("jobUrl", "")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="show watchlist and exit")
    ap.add_argument("--full", action="store_true",
                    help="also dump all current title-matched postings")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    os.makedirs(STATE_DIR, exist_ok=True)
    boards = scan_vault()
    for key, meta in load_extra().items():
        boards.setdefault(key, []).append("[pinned: %s]" % meta.get("why", "manual"))

    print("watchlist: %d boards (auto-built from job-listing notes + Archive)"
          % len(boards))
    if args.list:
        for key, sources in boards.items():
            print("  %-40s <- %s" % (key, "; ".join(sources[:2])))
        return

    prev = {}
    if os.path.exists(SNAPSHOT):
        with open(SNAPSHOT, encoding="utf-8") as f:
            prev = json.load(f)

    snap, failures = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(poll, key): key for key in boards}
        for fut in concurrent.futures.as_completed(futs):
            key = futs[fut]
            try:
                snap[key] = fut.result()
            except Exception as e:  # noqa: BLE001 -- one dead board must not kill the sweep
                failures.append((key, str(e)[:80]))

    new_rows, baselined = [], 0
    for key, jobs in sorted(snap.items()):
        if key not in prev:
            baselined += 1
            continue
        for jid, j in jobs.items():
            if jid not in prev[key]:
                flag = ("" if KEEP.search(j["title"]) and not DROP.search(j["title"])
                        else "  [off-lane title]")
                new_rows.append((key, j, flag))

    print("polled %d boards ok, %d failed, %d baselined (first poll, diff starts tomorrow)"
          % (len(snap), len(failures), baselined))
    for key, err in failures:
        print("   ! %-40s %s" % (key, err))

    if new_rows:
        print("\nNEW POSTINGS since last snapshot (%d) -- verify + gate before noting:"
              % len(new_rows))
        for key, j, flag in new_rows:
            print("-" * 72)
            print("[%s] %s%s" % (key, j["title"], flag))
            print("  %s" % j["loc"])
            print("  %s" % j["url"])
    else:
        print("\nno new postings since last snapshot")

    if args.full:
        print("\nCURRENT TITLE-MATCHED POSTINGS across the watchlist:")
        for key, jobs in sorted(snap.items()):
            for j in jobs.values():
                if KEEP.search(j["title"]) and not DROP.search(j["title"]):
                    print("  [%s] %s | %s | %s"
                          % (key, j["title"], j["loc"], j["url"]))

    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snap, f)
    print("\nsnapshot written: %s" % SNAPSHOT)


if __name__ == "__main__":
    main()
