#!/usr/bin/env python3
"""Indeed discovery lane for /job-search.

Indeed 403s plain curl/requests/WebFetch. Real Chrome (patchright, channel
"chrome", new headless mode, a normal non-Headless UA) gets HTTP 200 with the
full server-rendered result list. The script re-execs itself under uv with
patchright, same as kcmo.py, and never opens a visible window.

Facts measured 2026-10-13, baked in below:
  * **Logged-out search shows page 1 only.** `start=10` and later redirect to
    "Sign In | Indeed Accounts" with HTTP 200 and zero cards. That is what the
    old script logged as "page 2 403 three times". It is a login wall, not
    throttling, so retries cannot fix it. The lane therefore runs page 1 per
    query with `sort=date` (newest 15-16 cards), and widens coverage with more
    query angles and a short `--days` window instead of pagination. Each query
    prints "shown N of TOTAL" so the coverage gap is visible.
  * **A cold first load can hit Cloudflare** ("Just a moment...", HTTP 403).
    Waiting on the same page and then reloading clears it; the next queries in
    the same browser session load clean.
  * `limit=50` triggers the Cloudflare challenge; do not add it.
  * The page HTML contains "captcha" on a clean load. The positive control is
    the rendered card count (`job_seen_beacon`), never a string search.
  * The remote facet leaks onsite rows, so gate 1 reads each row's own location.

Two passes per query, same shape as usajobs.py / dice.py:
  REMOTE  l=Remote + the remote work-attribute facet, gated at JOB_COMP_FLOOR
  LOCAL   Kansas City, MO + 35 mi, gated at JOB_ONSITE_FLOOR (any office day)

Indeed is a mirror, not a source of truth: verify every hit on the employer's
own ATS before it earns a listing note.

Usage:
    python3 indeed.py "IT analyst" "identity access" --days 3 [--no-local]
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
UV = os.environ.get("UV", str(Path.home() / ".local/bin/uv"))


def _ensure_patchright() -> None:
    """Re-run this script under uv with patchright when it is not importable."""
    try:
        import patchright  # noqa: F401  (import probe only)
    except ImportError:
        if os.environ.get("INDEED_REEXEC"):
            print("indeed lane DID NOT RUN: patchright is not available under uv.")
            sys.exit(0)
        os.environ["INDEED_REEXEC"] = "1"
        os.execv(UV, [UV, "run", "--no-project", "--quiet", "--python", "3.12",
                      "--with", "patchright", "python", __file__, *sys.argv[1:]])


from comp_floors import comp_floor, onsite_floor  # noqa: E402  (sys.path set above)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
REMOTE_FACET = "0kf:attr(DSQF7);"  # Indeed's "Remote" work-attribute token
KC_LOCATION = "Kansas City, MO"
KC_RADIUS = 35
KC_METRO = re.compile(
    r"kansas city|overland park|lenexa|olathe|lee'?s summit|independence, mo|"
    r"shawnee|leawood|merriam|mission, ks|prairie village|north kansas city|"
    r"liberty, mo|blue springs|grandview|raytown|gladstone|riverside, mo|"
    r"belton|gardner|raymore|parkville|kearney|smithville", re.I)

TITLE_DROP = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|manager|director|head of|architect"
    r"|engineer i{3,}|vp|vice president|chief|epic|cerner|workday|sap|salesforce"
    r"|mainframe|gis|sales|account executive|customer success)\b", re.I)
# Mirrors dice.py: an in-lane title word is required, because Indeed relevance
# is loose (2026-10-13: "security analyst" returned behavior analysts).
KEEP = re.compile(
    r"\b(analyst|it support|it operations|it specialist|helpdesk|help desk|"
    r"service desk|security|identity|iam|grc|compliance|administrator|m365|"
    r"microsoft 365|intune|endpoint|desktop support|technical support)\b", re.I)
OFF_LANE = re.compile(r"\b(behavior analyst|bcba|financial analyst|data analyst|"
                      r"business analyst|credit analyst|research analyst)\b", re.I)
BODY_SHOP = re.compile(r"contract|temporary|temp|internship|per diem|seasonal", re.I)


def search_url(query: str, days: int, local: bool) -> str:
    params = {"q": query, "fromage": str(days), "sort": "date"}
    if local:
        params |= {"l": KC_LOCATION, "radius": str(KC_RADIUS)}
    else:
        params |= {"l": "Remote", "sc": REMOTE_FACET}
    return "https://www.indeed.com/jobs?" + urllib.parse.urlencode(params)


def load(pg, url: str) -> tuple[str, int, str]:
    """Load one results page. Returns (html, card count, status note)."""
    note = ""
    for attempt in range(3):
        r = pg.goto(url, wait_until="domcontentloaded", timeout=45000)
        status = r.status if r else None
        # A Cloudflare interstitial can resolve on its own: poll for cards.
        for _ in range(8):
            pg.wait_for_timeout(2500)
            html = pg.content()
            cards = html.count("job_seen_beacon")
            if cards:
                return html, cards, f"HTTP {status}"
        title = pg.title()
        if "sign in" in title.lower():
            return html, 0, "LOGIN WALL (Indeed sign-in page)"
        note = f"HTTP {status} {title[:30]!r}"
        if attempt < 2:
            pg.wait_for_timeout(10000 * (attempt + 1))
    return "", 0, note + " after 3 tries"


def parse(html: str) -> tuple[list[dict], int | None]:
    """Pull job dicts and the total-count field out of the mosaic blob."""
    total = None
    m = re.search(r'"totalJobCount":(\d+)', html)
    if m:
        total = int(m.group(1))
    m = re.search(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});',
                  html, re.S)
    if not m:
        return [], total
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"  blob parse failed: {e}")
        return [], total
    jobs = []
    for j in (data.get("metaData", {}).get("mosaicProviderJobCardsModel", {})
              .get("results", [])):
        # jobTypes entries are bare strings on some cards, {"label": ...} on others.
        types = [t.get("label") if isinstance(t, dict) else str(t)
                 for t in (j.get("jobTypes") or [])]
        sal = j.get("extractedSalary") or {}
        mult = {"hourly": 2080, "weekly": 52, "monthly": 12}.get(sal.get("type", ""), 1)
        smin, smax = sal.get("min"), sal.get("max")
        lo = smin * mult if smin else None
        hi = smax * mult if smax else None
        jobs.append({
            "key": j.get("jobkey"),
            "title": j.get("displayTitle") or j.get("title") or "",
            "company": j.get("company") or "",
            "location": j.get("formattedLocation") or "",
            "remote_flag": bool(j.get("remoteLocation")),
            "lo": lo, "hi": hi,
            "salary_text": (j.get("salarySnippet") or {}).get("text") or "",
            "type": types,
            "age": j.get("formattedRelativeTime") or "",
            "url": f"https://www.indeed.com/viewjob?jk={j.get('jobkey')}",
        })
    return jobs, total


def gate(j: dict, local: bool, floor: int, onsite: int) -> tuple[str, str]:
    if (TITLE_DROP.search(j["title"]) or not KEEP.search(j["title"])
            or OFF_LANE.search(j["title"])):
        return "drop", "title pre-filter"
    loc = j["location"].lower()
    tag = ""
    if local or "remote" not in loc:
        if not KC_METRO.search(loc):
            return "decline", f"gate1 location {j['location']!r}"
        if "remote" not in loc:
            floor, tag = onsite, f" [KC-LOCAL: ${onsite:,} onsite floor]"
    if any(BODY_SHOP.search(t) for t in j["type"]):
        return "decline", f"gate2 type {','.join(j['type'])}"
    if j["hi"] is None:
        return "lead", f"comp unlisted{tag}"
    if j["hi"] < floor:
        return "decline", f"gate3 band tops at ${int(j['hi']):,}{tag}"
    flag = f" [BAND-STRADDLE: bottom ${int(j['lo']):,}]" if j["lo"] and j["lo"] < floor else ""
    return "survivor", flag + tag


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="+")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--no-local", action="store_true", help="skip the KC-local pass")
    ap.add_argument("--verbose", action="store_true", help="list declined rows")
    args = ap.parse_args()
    _ensure_patchright()
    from patchright.sync_api import sync_playwright

    floor, onsite = comp_floor(), onsite_floor()
    passes = [False] + ([] if args.no_local else [True])
    seen: dict[str, dict] = {}
    buckets: dict[str, list] = {k: [] for k in ("survivor", "lead", "decline", "drop")}
    not_run = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True, args=["--headless=new"])
        try:
            pg = b.new_context(user_agent=UA, viewport={"width": 1500, "height": 1000}).new_page()
            for q in args.queries:
                for local in passes:
                    label = f"{q} [{'LOCAL KC' if local else 'REMOTE'}]"
                    html, cards, note = load(pg, search_url(q, args.days, local))
                    if not cards:
                        print(f"== {label}: NOT RUN ({note})")
                        not_run.append(label)
                        continue
                    jobs, total = parse(html)
                    # totalJobCount is Indeed's own estimate and runs below the
                    # row count on small result sets, so print both as-is.
                    shown = f"{len(jobs)} rows, Indeed total {total if total is not None else '?'}"
                    gap = ("  ~ COVERAGE: page 1 only (login wall)"
                           if total and total > len(jobs) else "")
                    print(f"== {label}: {note}, {shown}{gap}")
                    for j in jobs:
                        if not j["key"] or j["key"] in seen:
                            continue
                        seen[j["key"]] = j
                        verdict, why = gate(j, local, floor, onsite)
                        buckets[verdict].append((j, why))
                    pg.wait_for_timeout(3000)
        finally:
            b.close()

    print(f"\n{len(seen)} unique | {len(buckets['survivor'])} survivors | "
          f"{len(buckets['lead'])} leads | {len(buckets['decline'])} declined | "
          f"{len(buckets['drop'])} title-dropped | {len(not_run)} query-passes NOT RUN\n")
    sections = [("SURVIVORS -- verify on employer ATS", "survivor"),
                ("LEADS -- comp unlisted, JD read decides", "lead")]
    if args.verbose:
        sections.append(("DECLINED", "decline"))
    for head, key in sections:
        print(head)
        for j, why in buckets[key]:
            comp = j["salary_text"] or "unlisted"
            print(f"  {j['title']} @ {j['company']} | {j['location']} | {comp} | "
                  f"{','.join(j['type']) or '?'} | {j['age']}{(' ' + why) if key != 'decline' else ' -- ' + why}")
            print(f"    {j['url']}")
        print()
    print("Verify each on the employer's own ATS before creating a listing note.")


if __name__ == "__main__":
    main()
