#!/usr/bin/env python3
"""Dice discovery lane for /job-search.

Dice's search page is server-rendered: each result is a `data-testid="job-card"`
block carrying the title, company, location + age, employment-type tags and a
salary label, so no API key and no browser are needed. What it does need is a
Chrome TLS fingerprint (curl_cffi), same as hiringcafe.py; the script re-execs
under the harness .venv when the running interpreter lacks curl_cffi.

Gates applied mechanically: remote (card location), full-time and NOT contract
/ third-party / C2C (Dice's body-shop glut, gate 2), comp band rule (gate 3,
unlisted or "Depends on Experience" surfaces as a LEAD), and the title
pre-filter. Survivors still need the JD read + employer-ATS verification.

Dice relevance is loose (2026-09-28: "identity access analyst" returned data
engineers first), so the title filter does real work here.

Usage:
    python3 dice.py "identity access management" "security analyst" [--days 1|3|7]
"""

import argparse
import html
import os
import re
import sys
import urllib.parse
from pathlib import Path


from comp_floors import comp_floor, onsite_floor

COMP_FLOOR = comp_floor()  # standard-lane floor, from the harness .env
ONSITE_FLOOR = onsite_floor()  # any office requirement inside the KC metro; same source
# Dice ignores its own location=Remote filter (2026-09-28: most cards were onsite),
# so gate 1 runs here. KC-metro onsite/hybrid seats are in scope at ONSITE_FLOOR.
KC_METRO = re.compile(
    r"kansas city|overland park|lenexa|olathe|lee'?s summit|independence, mo|"
    r"shawnee|leawood|merriam|mission, ks|prairie village|north kansas city|"
    r"liberty, mo|blue springs|grandview|raytown|gladstone|riverside, mo", re.I)
POSTED = {1: "ONE", 3: "THREE", 7: "SEVEN"}

# Mirrors nicheboards.py / workday.py.
DROP = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|manager|director|head of|architect|"
    r"engineer (iii|iv|v)|vp|vice president|chief|supervisory|"
    r"epic|cerner|workday|oracle|salesforce|dynamics 365|mainframe|sap|zendesk|"
    r"pre-?sales|sales engineer|solutions engineer|account executive|"
    r"customer success|sales)\b", re.I)
KEEP = re.compile(
    r"\b(analyst|it support|it operations|it specialist|helpdesk|help desk|"
    r"service desk|resident consultant|associate consultant|security|identity|"
    r"iam|grc|compliance|administrator|m365|microsoft 365|intune|endpoint|"
    r"desktop support|technical support)\b", re.I)
BODY_SHOP = re.compile(r"contract|third party|c2c|corp[- ]to[- ]corp|1099|temp", re.I)


def _ensure_curl_cffi():
    """Re-exec under the harness .venv when this interpreter lacks curl_cffi.

    Only called from main(): doing this at import time replaced the pytest
    process that imports this module for the gate tests (2026-09-28).
    """
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"
        if venv.exists() and Path(sys.executable).resolve() != venv.resolve():
            os.execv(str(venv), [str(venv), __file__, *sys.argv[1:]])
        sys.exit("curl_cffi missing: uv pip install --python .venv/bin/python curl_cffi")


_SESSION = None


def _session():
    global _SESSION
    if _SESSION is None:
        from curl_cffi import requests as cffi_requests
        _SESSION = cffi_requests.Session(impersonate="chrome")
    return _SESSION


def _text(m):
    return html.unescape(re.sub(r"<!-- -->", "", m.group(1))).strip() if m else ""


def cards(query, days, page):
    params = {"q": query, "location": "Remote", "filters.postedDate": POSTED[days],
              "filters.employmentType": "FULLTIME", "page": page}
    r = _session().get("https://www.dice.com/jobs?" + urllib.parse.urlencode(params), timeout=45)
    r.raise_for_status()
    out = []
    for c in r.text.split('data-testid="job-card"')[1:]:
        guid = re.search(r'href="/job-detail/([0-9a-f-]{36})"', c)
        if not guid:
            continue
        company = _text(re.search(r'job-card-company-name">([^<]+)<', c)) or \
            _text(re.search(r'<img [^>]*alt="([^"]+)"', c))
        out.append({
            "id": guid.group(1),
            "title": _text(re.search(r'job-search-job-detail-link"[^>]*>([^<]+)<', c)),
            "company": company or "?",
            "where": _text(re.search(r'text-foreground-light">(.*?)</p>', c)),
            "type": _text(re.search(r'id="employmentType-label"[^>]*>([^<]+)<', c)),
            "salary": _text(re.search(r'id="salary-label"[^>]*>([^<]+)<', c)),
        })
    return out


def parse_band(s):
    """'USD 100,000.00 - 110,000.00 per year' -> (100000, 110000); hourly x 2080."""
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s)]
    if not nums:
        return None, None
    mult = 2080 if re.search(r"hour|/hr", s, re.I) else 1
    lo, hi = nums[0] * mult, nums[-1] * mult
    return lo, hi


def gate(j):
    if not KEEP.search(j["title"]) or DROP.search(j["title"]):
        return "drop", "title pre-filter"
    floor, local = COMP_FLOOR, ""
    if "remote" not in j["where"].lower():
        if not KC_METRO.search(j["where"]):
            return "decline", "gate1 location %r" % j["where"]
        floor, local = ONSITE_FLOOR, f" [KC-LOCAL onsite/hybrid: ${ONSITE_FLOOR:,} floor]"
    if "full-time" not in j["type"].lower() or BODY_SHOP.search(j["type"]):
        return "decline", "gate2 employment type %r" % j["type"]
    lo, hi = parse_band(j["salary"])
    if hi is None:
        return "lead", "comp unlisted (%s)%s" % (j["salary"] or "none", local)
    if hi < floor:
        return "decline", "gate3 band tops out at $%s%s" % (f"{int(hi):,}", local)
    flag = " [BAND-STRADDLE: bottom $%s under floor]" % f"{int(lo):,}" if lo and lo < floor else ""
    return "survivor", flag + local


def main():
    _ensure_curl_cffi()
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="+")
    ap.add_argument("--days", type=int, choices=sorted(POSTED), default=3)
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--verbose", action="store_true", help="list every declined card")
    a = ap.parse_args()

    seen, buckets = {}, {"survivor": [], "lead": [], "decline": [], "drop": []}
    for q in a.queries:
        n = 0
        for p in range(1, a.pages + 1):
            try:
                got = cards(q, a.days, p)
            except Exception as e:  # noqa: BLE001 -- report the gap, keep the other queries
                print("== %-35s page %d FAILED: %s" % (q, p, str(e)[:80]))
                break
            n += len(got)
            for j in got:
                if j["id"] not in seen:
                    seen[j["id"]] = j
                    verdict, why = gate(j)
                    buckets[verdict].append((j, why))
            if len(got) < 20:
                break
        print("== %-35s %d cards" % (q, n))

    print("\n%d unique | %d survivors | %d leads | %d declined | %d title-dropped\n"
          % (len(seen), *(len(buckets[k]) for k in ("survivor", "lead", "decline", "drop"))))
    sections = [("SURVIVORS -- verify on employer ATS", "survivor"),
                ("LEADS -- comp unlisted, JD read decides", "lead")]
    if a.verbose:
        sections.append(("DECLINED", "decline"))
    for label, key in sections:
        print(label)
        for j, why in buckets[key]:
            print("  %s @ %s | %s | %s | %s %s" % (j["title"], j["company"], j["where"],
                                                  j["type"], j["salary"] or "-", why))
            if key != "decline":
                print("    https://www.dice.com/job-detail/%s" % j["id"])
        print()


if __name__ == "__main__":
    main()
