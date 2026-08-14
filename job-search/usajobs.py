#!/usr/bin/env python3
"""USAJOBS discovery lane for /job-search: the official federal jobs API.

Federal remote IT/security postings mostly never touch commercial boards, and
many explicitly accept experience in lieu of a degree. Alex is Public
Trust-eligible, which several already-scanned postings (Cadmus, CVP, LTS)
treated as a requirement he clears.

The API is free but keyed: request a key at https://developer.usajobs.gov/apirequest/
(email form; the key arrives by email). Put it in the harness .env as:

    USAJOBS_API_KEY=<key>
    USAJOBS_EMAIL=<the email used to register>

Without a key the script prints instructions and exits 0 so the headless scan
treats the lane as skipped-with-reason rather than failed.

Gates applied mechanically: RemoteIndicator=True (server-side), full-time
schedule, comp band rule against the floor after annualizing per-hour rates.
Title pre-filter matches the other lanes.

Usage:
    python3 usajobs.py "IT specialist" "security analyst" --days 7
"""

import argparse
import json
import os
import re
import urllib.parse
import urllib.request

COMP_FLOOR = 75_000  # standard-lane floor; see gitignored Claude Reference.md

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

DROP = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|manager|director|chief|architect|"
    r"supervisory|supvy)\b", re.I)


def env_creds():
    creds = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("USAJOBS_") and "=" in line:
                    k, v = line.split("=", 1)
                    creds[k.strip()] = v.strip().strip('"').strip("'")
    return creds.get("USAJOBS_API_KEY"), creds.get("USAJOBS_EMAIL")


def search(key, email, query, days):
    params = urllib.parse.urlencode({
        "Keyword": query,
        "RemoteIndicator": "True",
        "HiringPath": "public",
        "DatePosted": str(days),
        "SortField": "opendate",
        "SortDirection": "desc",
        "ResultsPerPage": "100",
    })
    req = urllib.request.Request(
        "https://data.usajobs.gov/api/search?" + params,
        headers={"Host": "data.usajobs.gov",
                 "User-Agent": email,
                 "Authorization-Key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def annual_band(remuneration):
    """(lo, hi) in $/yr from PositionRemuneration, annualizing hourly rates."""
    lo = hi = None
    for r in remuneration or []:
        try:
            a, b = float(r.get("MinimumRange", 0)), float(r.get("MaximumRange", 0))
        except (TypeError, ValueError):
            continue
        if (r.get("RateIntervalCode") or "").upper() in ("PH", "PER HOUR"):
            a, b = a * 2080, b * 2080
        lo = a if lo is None else min(lo, a)
        hi = b if hi is None else max(hi, b)
    return lo, hi


def gate(d):
    sched = [s.get("Name", "") for s in d.get("PositionSchedule") or []]
    if sched and not any("full" in s.lower() for s in sched):
        return False, "gate2 %s" % ",".join(sched)
    lo, hi = annual_band(d.get("PositionRemuneration"))
    if hi is None:
        return False, "gate3 comp unlisted"
    if hi < COMP_FLOOR:
        return False, "gate3 band tops out at $%s" % f"{int(hi):,}"
    if lo is not None and lo < COMP_FLOOR:
        return True, "BAND-STRADDLE: bottom $%s under floor" % f"{int(lo):,}"
    return True, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="+")
    ap.add_argument("--days", type=int, default=7, help="max posting age")
    args = ap.parse_args()

    key, email = env_creds()
    if not key or not email:
        print("USAJOBS lane SKIPPED: no API key configured.")
        print("Request one (free) at https://developer.usajobs.gov/apirequest/")
        print("then add USAJOBS_API_KEY=... and USAJOBS_EMAIL=... to the harness .env")
        return

    print("floor $%s | max age %dd | remote-only, public hiring path\n"
          % (f"{COMP_FLOOR:,}", args.days))

    seen, survivors = set(), []
    for q in args.queries:
        try:
            d = search(key, email, q, args.days)
        except OSError as e:
            print("== %-30s LANE DID NOT RUN: %s" % ('"%s"' % q, e))
            continue
        items = d.get("SearchResult", {}).get("SearchResultItems", [])
        print("== %-30s %d hits" % ('"%s"' % q, len(items)))
        for it in items:
            desc = it.get("MatchedObjectDescriptor", {})
            jid = it.get("MatchedObjectId")
            title = desc.get("PositionTitle", "")
            if jid in seen or DROP.search(title):
                continue
            seen.add(jid)
            ok, note = gate(desc)
            if not ok:
                continue
            lo, hi = annual_band(desc.get("PositionRemuneration"))
            close = (desc.get("ApplicationCloseDate") or "")[:10]
            survivors.append((title, desc.get("OrganizationName", ""),
                              lo, hi, close, desc.get("PositionURI", ""), note))

    print("\n%d survivor(s) of %d unique postings" % (len(survivors), len(seen)))
    for title, org, lo, hi, close, url, note in survivors:
        print("-" * 72)
        print("%s @ %s%s" % (title, org, ("  [%s]" % note) if note else ""))
        print("  $%s - $%s | closes %s"
              % (f"{int(lo or 0):,}", f"{int(hi or 0):,}", close or "?"))
        print("  %s" % url)
    if survivors:
        print("\nNote: federal postings close on hard deadlines and often require "
              "USAJOBS-profile resumes -- read the How to Apply section per posting.")


if __name__ == "__main__":
    main()
