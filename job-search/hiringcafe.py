#!/usr/bin/env python3
"""Hiring.cafe discovery lane for /job-search.

The public site moved from hiring.cafe to hiringcafe.com. There is no documented
REST API; the working data path is the Next.js page-data route:

    https://hiringcafe.com/_next/data/<BUILD_ID>/index.json?searchState=<url-encoded JSON>

BUILD_ID rotates on every deploy, so it is scraped from the homepage each run
rather than pinned. Plain curl/requests with a browser UA is enough -- no
Playwright, no auth. (An earlier attempt used hiring.cafe/api/search-jobs, which
401s on GET and 405s on POST because that host is not the app.)

Each hit carries structured fields that map onto the four hard gates, so the
filtering here is exact rather than inferred from prose.

Usage:
    python3 hiringcafe.py "IT analyst" "identity access management" --days 7
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

COMP_FLOOR = 75_000  # standard-lane floor; see gitignored Claude Reference.md


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def build_id():
    m = re.search(r'"buildId":"([^"]+)"', _get("https://hiringcafe.com/"))
    if not m:
        sys.exit("could not scrape buildId -- site markup changed, re-probe with Playwright")
    return m.group(1)


def search(bid, query, page=0):
    state = {"searchQuery": query, "defaultToUserLocation": False}
    if page:
        state["page"] = page
    url = ("https://hiringcafe.com/_next/data/%s/index.json?searchState=%s"
           % (bid, urllib.parse.quote(json.dumps(state))))
    return json.loads(_get(url)).get("pageProps", {}).get("ssrHits", [])


def gate(hit, max_age_days):
    """Return (passed, reason). Mirrors the 4 hard gates in SKILL.md."""
    v = hit.get("v5_processed_job_data", {}) or {}

    if v.get("workplace_type") != "Remote":
        return False, "gate1 not remote (%s)" % v.get("workplace_type")
    if "US" not in (v.get("workplace_countries") or []):
        return False, "gate1 not US"

    commitment = v.get("commitment") or []
    if "Full Time" not in commitment:
        return False, "gate2 not full-time (%s)" % commitment

    hi = v.get("yearly_max_compensation")
    if not v.get("is_compensation_transparent") or hi is None:
        return False, "gate3 comp unlisted -> DQ by default"
    if hi < COMP_FLOOR:
        return False, "gate3 band tops out at $%s, under floor" % f"{int(hi):,}"

    # Gate 4: only the mechanically checkable parts. Degree and YoE are stated
    # bars Alex either clears or does not; responsibility match still needs eyes.
    if v.get("bachelors_degree_requirement") == "Required":
        return False, "gate4 bachelor's required (Alex has none)"
    if (v.get("min_industry_and_role_yoe") or 0) > 8:
        return False, "gate4 wants %s+ yrs" % v.get("min_industry_and_role_yoe")
    if v.get("security_clearance") not in (None, "None"):
        return False, "gate4 clearance: %s" % v.get("security_clearance")

    ms = v.get("estimated_publish_date_millis")
    if ms and max_age_days:
        import time
        age = (time.time() * 1000 - ms) / 86_400_000
        if age > max_age_days:
            return False, "stale (%d days old)" % age

    # Band rule (Alex 2026-08-10): a range containing the floor passes; a bottom
    # under the floor is a pass-with-flag so the offer risk is visible downstream.
    lo = v.get("yearly_min_compensation")
    if lo is not None and lo < COMP_FLOOR:
        return True, "PASS (BAND-STRADDLE: bottom $%s under floor)" % f"{int(lo):,}"
    return True, "PASS"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="+")
    ap.add_argument("--days", type=int, default=14, help="max posting age")
    ap.add_argument("--show-declines", action="store_true")
    args = ap.parse_args()

    bid = build_id()
    print("buildId %s | floor $%s | max age %sd\n" % (bid, f"{COMP_FLOOR:,}", args.days))

    seen, survivors = set(), []
    for q in args.queries:
        hits = search(bid, q)
        print("== %-38s %d hits" % (q, len(hits)))
        for h in hits:
            key = h.get("id")
            if key in seen:
                continue
            seen.add(key)
            ok, why = gate(h, args.days)
            v = h.get("v5_processed_job_data", {}) or {}
            label = "%s @ %s" % (v.get("core_job_title") or
                                 h.get("job_information", {}).get("title"),
                                 v.get("company_name"))
            if ok:
                survivors.append((label, v, h.get("apply_url"), why))
            elif args.show_declines:
                print("   x %-62s %s" % (label[:62], why))

    print("\n%d survivor(s) of %d unique postings" % (len(survivors), len(seen)))
    for label, v, url, why in survivors:
        print("-" * 72)
        print(label if why == "PASS" else "%s  [%s]" % (label, why))
        print("  $%s - $%s | %s | %s yrs+ | posted %s"
              % (f"{int(v.get('yearly_min_compensation') or 0):,}",
                 f"{int(v.get('yearly_max_compensation') or 0):,}",
                 v.get("seniority_level"),
                 v.get("min_industry_and_role_yoe"),
                 (v.get("estimated_publish_date") or "")[:10]))
        print("  %s" % url)


if __name__ == "__main__":
    main()
