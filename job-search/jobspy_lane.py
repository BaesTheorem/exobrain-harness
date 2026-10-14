#!/usr/bin/env python3
"""ZipRecruiter + Glassdoor discovery lane for /job-search, through JobSpy.

Both sites put Cloudflare in front of a plain curl (403, measured 2026-10-13),
which is why they only reached the pipeline as Gmail alerts. The open-source
JobSpy library (github.com/speedyapply/JobSpy, MIT) talks to their mobile and
GraphQL backends instead and returns structured rows: posted date, is_remote,
min/max pay with interval, job type, and the direct apply URL.

The script re-execs under uv with python-jobspy, so nothing is installed into
the harness venv. Two passes per query, the same shape as indeed.py:
REMOTE at JOB_COMP_FLOOR and Kansas City, MO + 35 mi at JOB_ONSITE_FLOOR.
JobSpy's Google Jobs scraper returned no data on the same day; it is not used.

Gates and the seen-file logic come from moreboards.py. Survivors still need the
JD read, dedup, and verification on the employer's own ATS.

Usage:
    python3 jobspy_lane.py "security analyst" "IT analyst" --days 3
"""

import argparse
import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
UV = os.environ.get("UV", str(Path.home() / ".local/bin/uv"))
STATE = Path(__file__).resolve().parent / "state" / "jobspy-seen.json"
SITES = ["zip_recruiter", "glassdoor"]
INTERVAL = {"yearly": 1, "monthly": 12, "weekly": 52, "daily": 260, "hourly": 2080}


def _ensure_jobspy() -> None:
    try:
        import jobspy  # noqa: F401  (import probe only)
    except ImportError:
        if os.environ.get("JOBSPY_REEXEC"):
            print("jobspy lane DID NOT RUN: python-jobspy is not available under uv.")
            sys.exit(0)
        os.environ["JOBSPY_REEXEC"] = "1"
        os.execv(UV, [UV, "run", "--no-project", "--quiet", "--python", "3.12",
                      "--with", "python-jobspy", "python", __file__, *sys.argv[1:]])


def num(v):
    """JobSpy returns pandas NaN for missing values."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="+")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--results", type=int, default=50, help="per site, per pass")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    _ensure_jobspy()
    from jobspy import scrape_jobs

    from comp_floors import comp_floor, onsite_floor
    from moreboards import gate, row

    floor, onsite = comp_floor(), onsite_floor()
    today = dt.date.today()
    seen = json.loads(STATE.read_text()) if STATE.exists() else {}
    seen = {u: d for u, d in seen.items() if dt.date.fromisoformat(d) >= today - dt.timedelta(days=60)}

    buckets: dict[str, list] = {k: [] for k in ("survivor", "lead", "decline", "drop")}
    urls: set[str] = set()
    already = 0
    for q in a.queries:
        for label, kw in (("REMOTE", {"location": "United States", "is_remote": True}),
                          ("LOCAL KC", {"location": "Kansas City, MO", "distance": 35})):
            for site in SITES:
                try:
                    df = scrape_jobs(site_name=[site], search_term=q, results_wanted=a.results,
                                     hours_old=a.days * 24, country_indeed="USA", verbose=0, **kw)
                except Exception as e:  # noqa: BLE001  (a blocked site is a reported gap)
                    print(f"== {q} [{label}] {site}: NOT RUN ({str(e)[:80]})")
                    continue
                note = "  ~ 0 rows: likely blocked, not dry" if len(df) == 0 else ""
                print(f"== {q} [{label}] {site}: {len(df)} rows{note}")
                for rec in df.to_dict("records"):
                    url = str(num(rec.get("job_url_direct")) or num(rec.get("job_url")) or "")
                    if not url or url in urls:
                        continue
                    urls.add(url)
                    if url in seen and not a.all:
                        already += 1
                        continue
                    mult = INTERVAL.get(str(num(rec.get("interval")) or "yearly"), 1)
                    lo, hi = num(rec.get("min_amount")), num(rec.get("max_amount"))
                    posted = num(rec.get("date_posted"))
                    r = row(f"jobspy-{site}", num(rec.get("title")), num(rec.get("company")),
                            num(rec.get("location")) or "", url,
                            # the KC pass trusts only the location text: JobSpy
                            # flags KC seats is_remote on Glassdoor (2026-10-13)
                            remote=bool(num(rec.get("is_remote"))) and label == "REMOTE",
                            lo=lo * mult if lo else None, hi=hi * mult if hi else None,
                            jtype=str(num(rec.get("job_type")) or ""),
                            posted=posted if isinstance(posted, dt.date) else None)
                    verdict, why = gate(r, floor, onsite)
                    buckets[verdict].append((r, why))

    print(f"\n{len(urls)} unique | {already} already shown | {len(buckets['survivor'])} survivors | "
          f"{len(buckets['lead'])} leads | {len(buckets['decline'])} declined | "
          f"{len(buckets['drop'])} title-dropped\n")
    for head, key in (("SURVIVORS -- JD read + employer-ATS verify", "survivor"),
                      ("LEADS -- comp unlisted, JD read decides", "lead")):
        print(head)
        for r, why in buckets[key]:
            comp = f"${int(r['lo'] or 0):,}-${int(r['hi'] or 0):,}" if r["lo"] or r["hi"] else "unlisted"
            print(f"  [{r['src']}] {r['title']} @ {r['company']} | {r['where']} | {comp} | "
                  f"{r['type'] or '?'} | {r['posted'] or '?'}  {why}")
            print(f"    {r['url']}")
        print()

    if not a.no_save:
        for u in urls:
            seen.setdefault(u, today.isoformat())
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(seen, indent=0, sort_keys=True))


if __name__ == "__main__":
    main()
