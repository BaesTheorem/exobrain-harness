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

Two passes per query (Alex standing instruction 2026-08-14):
  - REMOTE: RemoteIndicator=True nationwide, gated at the standard floor.
  - LOCAL:  LocationName + Radius around Kansas City, gated at the ONSITE
    floor. Alex's onsite floor is binary on any office requirement -- one day
    a week or five both trigger it (see feedback_onsite_floor memory) -- and
    every local federal seat carries at least some onsite, so the higher floor
    applies to the whole pass.

Other gates match the rest of the pipeline: full-time schedule, comp band rule
after annualizing per-hour rates, title pre-filter.

Usage:
    python3 usajobs.py "IT specialist" "security analyst" --days 7
"""

import argparse
import json
import os
import re
import urllib.parse
import urllib.request

COMP_FLOOR = 75_000    # standard remote floor; see gitignored Claude Reference.md
ONSITE_FLOOR = 103_000  # any office requirement at all triggers this, binary
LOCAL_LOCATION = "Kansas City, Missouri"
LOCAL_RADIUS_MILES = 30

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

DROP = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|manager|director|chief|architect|"
    r"supervisory|supvy)\b", re.I)
# USAJOBS keyword matching is loose (an "information technology" query returns
# transportation program roles), so require an in-lane title like other lanes.
KEEP = re.compile(
    r"\b(analyst|it support|it operations|it specialist|helpdesk|help desk|"
    r"service desk|security|identity|iam|grc|compliance|administrator|"
    r"information technology|m365|intune|endpoint|desktop support|"
    r"technical support)\b", re.I)


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


def search(key, email, query, days, local=False):
    p = {
        "Keyword": query,
        "HiringPath": "public",
        "DatePosted": str(days),
        "SortField": "opendate",
        "SortDirection": "desc",
        "ResultsPerPage": "100",
    }
    if local:
        p["LocationName"] = LOCAL_LOCATION
        p["Radius"] = str(LOCAL_RADIUS_MILES)
    else:
        p["RemoteIndicator"] = "True"
    params = urllib.parse.urlencode(p)
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


def gate(d, floor):
    # PositionSchedule Name often carries tour-of-duty prose ("Monday-Friday
    # 8:00am...") or is empty; the Code is the reliable field (1 = full-time).
    # Gate only on an explicit non-full-time code -- an absent/unparseable
    # schedule is not evidence of part-time.
    codes = [str(s.get("Code", "")) for s in d.get("PositionSchedule") or []]
    names = " ".join(s.get("Name", "") for s in d.get("PositionSchedule") or [])
    if codes and "1" not in codes and "full" not in names.lower():
        return False, "gate2 schedule codes %s" % ",".join(codes)
    lo, hi = annual_band(d.get("PositionRemuneration"))
    if hi is None:
        return False, "gate3 comp unlisted"
    if hi < floor:
        return False, "gate3 band tops out at $%s (floor $%s)" % (
            f"{int(hi):,}", f"{floor:,}")
    if lo is not None and lo < floor:
        return True, "BAND-STRADDLE: bottom $%s under $%s floor" % (
            f"{int(lo):,}", f"{floor:,}")
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

    print("remote floor $%s | LOCAL (%s, %dmi) onsite floor $%s | max age %dd\n"
          % (f"{COMP_FLOOR:,}", LOCAL_LOCATION, LOCAL_RADIUS_MILES,
             f"{ONSITE_FLOOR:,}", args.days))

    seen, survivors = set(), []
    passes = [("remote", False, COMP_FLOOR), ("LOCAL", True, ONSITE_FLOOR)]
    for q in args.queries:
        for pass_name, local, floor in passes:
            try:
                d = search(key, email, q, args.days, local=local)
            except OSError as e:
                print("== %-30s %-6s LANE DID NOT RUN: %s"
                      % ('"%s"' % q, pass_name, e))
                continue
            items = d.get("SearchResult", {}).get("SearchResultItems", [])
            print("== %-30s %-6s %d hits" % ('"%s"' % q, pass_name, len(items)))
            for it in items:
                desc = it.get("MatchedObjectDescriptor", {})
                jid = it.get("MatchedObjectId")
                title = desc.get("PositionTitle", "")
                if jid in seen or DROP.search(title) or not KEEP.search(title):
                    continue
                seen.add(jid)
                ok, note = gate(desc, floor)
                if not ok:
                    continue
                lo, hi = annual_band(desc.get("PositionRemuneration"))
                close = (desc.get("ApplicationCloseDate") or "")[:10]
                survivors.append((pass_name, title,
                                  desc.get("OrganizationName", ""), lo, hi, close,
                                  desc.get("PositionLocationDisplay", ""),
                                  desc.get("PositionURI", ""), note))

    print("\n%d survivor(s) of %d unique postings" % (len(survivors), len(seen)))
    for pass_name, title, org, lo, hi, close, loc, url, note in survivors:
        print("-" * 72)
        print("[%s] %s @ %s%s"
              % (pass_name, title, org, ("  [%s]" % note) if note else ""))
        print("  $%s - $%s | %s | closes %s"
              % (f"{int(lo or 0):,}", f"{int(hi or 0):,}", loc, close or "?"))
        print("  %s" % url)
    if survivors:
        print("\nNote: federal postings close on hard deadlines and often require "
              "USAJOBS-profile resumes -- read the How to Apply section per posting.")


if __name__ == "__main__":
    main()
