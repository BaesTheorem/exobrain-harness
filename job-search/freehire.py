#!/usr/bin/env python3
"""freehire.me discovery lane: one free API over many applicant tracking systems.

freehire.me (docs: https://freehire.me/docs/api) indexes postings from
Greenhouse, Lever, Ashby, Workday, iCIMS, UKG, ADP, Paycom, Oracle and other
systems, with no key and no browser. A probe on 2026-10-23 gave 8,348 remote US
results for one analyst title; the top 100 came from 20 sources, four of them
(iCIMS, UKG, ADP, Paycom) with no direct lane in this pipeline.

Three fields make it worth more than a plain board:
  enrichment.requirements  pre-parsed JD lines with priority=required, which map
                           onto the rows of the fit scorecard
  enrichment.salary_*      a structured band when the posting lists one
                           (about 3 rows in 10)
  reality                  repost_count, mass_posting_count and fake_freshness,
                           ghost-posting signals no other lane has

Measured behavior (the API's own quirks, see also the Seekter source notes):
  - `q` orders but does not narrow; a title search reports a huge total. Keep
    the default relevance order (date order floods off-topic titles) and run
    the profile's title filter as a second pass.
  - The `cities` facet is not a working filter. The local pass adds the metro
    city to `q` and then keeps rows whose location matches the profile metro.
  - Python's default User-Agent gets 403; an explicit one passes.

Gates applied here: title keep/drop/off-lane, closed postings, remote US or the
home metro, full-time, comp band rule (unlisted comp = LEAD), and the profile
knockouts (years, clearance, degree). A seen-file limits each run to postings it
has not shown before.

Usage:
    python3 job-search/freehire.py "security analyst" "IT analyst" --days 3
    python3 job-search/freehire.py "GRC analyst" --json state/freehire-today.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import jobprofile as P
import runlog
from comp_floors import comp_floor, onsite_floor

API = "https://freehire.me/api/v1/jobs/search"
UA = "exobrain-harness/1.0 (+https://github.com/BaesTheorem/exobrain-harness)"
PERIOD = {"year": 1, "month": 12, "week": 52, "day": 260, "hour": 2080}
SEEN = P.state_dir() / "freehire-seen.json"
BAD_TYPE = re.compile(r"\b(seasonal|contract|contractor|part[- ]time|temporary|temp|intern(ship)?|per diem|1099)\b", re.I)


def fetch(params: dict, tries: int = 3) -> dict:
    url = API + "?" + urllib.parse.urlencode(params, doseq=True)
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return {}


def annual(value, period: str | None) -> float | None:
    if not value:
        return None
    return float(value) * PERIOD.get(period or "year", 1)


def age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400


def reality_flags(j: dict) -> str:
    r = j.get("reality") or {}
    flags = []
    if (r.get("mass_posting_count") or 0) >= 3:
        flags.append("MASS-POSTED x%d" % r["mass_posting_count"])
    if r.get("fake_freshness"):
        flags.append("FAKE-FRESH")
    if (r.get("repost_count") or 0) > 1:
        flags.append("REPOSTED x%d" % r["repost_count"])
    return (" [" + ", ".join(flags) + "]") if flags else ""


def gate(j: dict, floor: int, onsite: int) -> tuple[str, str]:
    """Return (bucket, reason). bucket: survivor | lead | decline | drop."""
    title = j.get("title") or ""
    if not P.title_re("keep").search(title) or P.title_re("drop").search(title) \
            or P.off_lane_re().search(title):
        return "drop", "title pre-filter"
    if j.get("closed_at"):
        return "drop", "closed"
    if BAD_TYPE.search(title):
        return "decline", "gate2 title says %r" % BAD_TYPE.search(title).group(0)
    e = j.get("enrichment") or {}
    loc = j.get("location") or ""
    mode = j.get("work_mode")
    countries = [c.lower() for c in (j.get("countries") or [])]
    tag = ""
    if mode == "remote" and (not countries or "us" in countries):
        use_floor = floor
    elif P.has_metro() and P.metro_re().search(loc):
        use_floor, tag = onsite, f" [{P.metro_tag()}: ${onsite:,} onsite floor]"
    else:
        return "decline", "gate1 location %r (%s)" % (loc, mode or "mode unknown")
    etype = e.get("employment_type")
    if etype and etype not in ("full_time", "fellowship"):
        return "decline", "gate2 %s" % etype
    years, max_years = e.get("experience_years_min"), P.knockout("max_years")
    if years is not None and max_years is not None and years > max_years:
        return "decline", "gate4 wants %s+ yrs" % years
    if P.knockout("clearance") and (e.get("requires_clearance") is True):
        return "decline", "gate4 clearance required"
    if P.knockout("degree_required") and e.get("education_level") in ("master", "phd"):
        return "decline", "gate4 %s degree" % e["education_level"]
    lo = annual(e.get("salary_min"), e.get("salary_period"))
    hi = annual(e.get("salary_max"), e.get("salary_period")) or lo
    if e.get("salary_currency") not in (None, "USD"):
        return "lead", "comp in %s%s" % (e["salary_currency"], tag)
    if hi is None:
        return "lead", "comp unlisted" + tag
    if hi < use_floor:
        return "decline", "gate3 band tops out at $%s%s" % (f"{int(hi):,}", tag)
    flag = " [BAND-STRADDLE: bottom $%s under floor]" % f"{int(lo):,}" if lo and lo < use_floor else ""
    return "survivor", (flag + tag).strip() or "PASS"


def required_lines(j: dict) -> list[str]:
    reqs = (j.get("enrichment") or {}).get("requirements") or []
    return [r.get("text", "") for r in reqs if r.get("priority") == "required"]


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("queries", nargs="+")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--limit", type=int, default=100, help="rows per query per pass (max 100)")
    ap.add_argument("--all", action="store_true", help="ignore the seen-file")
    ap.add_argument("--verbose", action="store_true", help="also print declined rows")
    ap.add_argument("--json", help="write survivors and leads, with required JD lines, to this file")
    a = ap.parse_args()

    floor, onsite = comp_floor(), onsite_floor()
    cfg = P.get("lanes.freehire", {}) or {}
    country = cfg.get("country", "US")
    cats = list(cfg.get("categories") or [None])
    seen = {} if a.all or not SEEN.exists() else json.loads(SEEN.read_text())
    buckets: dict[str, list] = {k: [] for k in ("survivor", "lead", "decline", "drop")}
    rows: dict[str, dict] = {}
    already = stale = 0
    run = runlog.Run("freehire")

    passes = P.with_local(("REMOTE", {"work_mode": "remote"}, False),
                          lambda: ("LOCAL " + P.metro_tag(), {}, True))
    print(f"freehire | remote floor ${floor:,} | onsite floor ${onsite:,} | window {a.days}d\n")
    for q in a.queries:
        for label, extra, local in passes:
            n = 0
            for cat in cats:
                params = {"q": f"{q} {P.metro_city()}" if local else q, "countries": country,
                          "limit": min(a.limit, 100), **extra}
                if cat:
                    params["category"] = cat
                try:
                    data = fetch(params).get("data", [])
                except Exception as ex:  # noqa: BLE001  report the gap, keep the other passes
                    print(f"== {q} [{label}] category={cat} NOT RUN: {str(ex)[:90]}")
                    run.note(f"NOT RUN {q} {label} {cat}")
                    continue
                n += len(data)
                for j in data:
                    slug = j.get("public_slug") or j.get("url")
                    if not slug or slug in rows:
                        continue
                    age = age_days(j.get("posted_at"))
                    if age is not None and age > a.days:
                        stale += 1
                        continue
                    if slug in seen:
                        already += 1
                        continue
                    rows[slug] = j
                    bucket, why = gate(j, floor, onsite)
                    buckets[bucket].append((j, why + reality_flags(j)))
            print(f"== {q:35} [{label}] {n} rows")

    today = dt.date.today().isoformat()
    for slug in rows:
        seen[slug] = today
    SEEN.write_text(json.dumps(seen, indent=0, sort_keys=True))
    run.count(rows=len(rows), already=already, out_of_window=stale,
              **{k: len(v) for k, v in buckets.items()})
    run.save()

    print(f"\n{len(rows)} new in window | {already} already shown | {stale} older than {a.days}d | "
          + " | ".join(f"{len(v)} {k}" for k, v in buckets.items()) + "\n")
    sections = [("SURVIVORS -- verify on the employer ATS", "survivor"),
                ("LEADS -- comp unlisted, JD read decides", "lead")]
    if a.verbose:
        sections.append(("DECLINED", "decline"))
    for head, key in sections:
        print(head)
        for j, why in buckets[key]:
            print(f"  {j.get('title')} @ {j.get('company')} | {j.get('location')} | "
                  f"{j.get('source')} | {why}")
            if key != "decline":
                print(f"    {j.get('url')}")
                print(f"    https://freehire.me/jobs/{j.get('public_slug')}  "
                      f"({len(required_lines(j))} required lines parsed)")
        print()

    if a.json:
        out = [{"bucket": k, "why": why, "title": j.get("title"), "company": j.get("company"),
                "location": j.get("location"), "url": j.get("url"), "source": j.get("source"),
                "freehire": j.get("public_slug"), "reality": j.get("reality"),
                "required": required_lines(j), "description": j.get("description")}
               for k in ("survivor", "lead") for j, why in buckets[k]]
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
        print(f"wrote {len(out)} rows to {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
