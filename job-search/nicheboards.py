#!/usr/bin/env python3
"""Niche-board discovery lane for /job-search: direct data paths, no search engine.

Replaces the Google X-ray approach to these boards, which kept logging the lane
as dry because the index lags and site: filters silently return other domains
(the 2026-08-13/14 failure mode). Every source here is the board's own data
path, verified live 2026-08-14:

  - Himalayas  https://himalayas.app/jobs/api?offset=&limit=   documented public
    JSON API, ~99k jobs, newest-first, full structured fields (salary, type,
    locationRestrictions, pubDate, expiryDate). The `search` param is IGNORED,
    so filtering happens client-side here.
  - Remotive   https://remotive.com/api/remote-jobs?search=    documented API,
    working search param. Salary is a freeform string; parsed best-effort.
  - WeWorkRemotely  plain RSS per category. No salary in the feed, so its hits
    can never pass gate 3 mechanically -- they surface as LEADS (needs JD read),
    never as survivors.
  - BuiltIn    server-rendered search page with a browser UA (no JS needed).
    Cards rarely show salary -> LEADS.

RemoteRocketship stays out: Cloudflare-blocked to curl, browser-only.

Division of labor matches hiringcafe.py: this script gates mechanically and
prints survivors/leads; the calling session dedups against the tracker and
verifies on the employer ATS before writing listing notes.

Usage:
    python3 nicheboards.py "IT analyst" "security analyst" --days 3
"""

import argparse
import concurrent.futures
import datetime as dt
import html
import json
import re
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

COMP_FLOOR = 75_000  # standard-lane floor; see gitignored Claude Reference.md

# Title pre-filter, mirroring the skill's LinkedIn-lane rules: seniority drops,
# specialist mismatches (tools Alex does not have), and sales/CSM shapes.
DROP = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|manager|director|head of|architect|"
    r"engineer (iii|iv|v)|vp|vice president|chief|supervisory|"
    r"epic|cerner|workday|oracle|salesforce|dynamics 365|mainframe|sap|zendesk|"
    r"pre-?sales|sales engineer|solutions engineer|account executive|"
    r"customer success)\b", re.I)
# A title must hit one of these to be worth surfacing at all (keeps the
# Himalayas firehose from flooding the output with sales/marketing roles).
KEEP = re.compile(
    r"\b(analyst|it support|it operations|it specialist|helpdesk|help desk|"
    r"service desk|security|identity|iam|grc|compliance|administrator|"
    r"m365|microsoft 365|intune|endpoint|desktop support|technical support)\b", re.I)

WWR_CATEGORIES = [
    "remote-devops-sysadmin-jobs",
    "remote-customer-support-jobs",
    "all-other-remote-jobs",  # NOT remote-all-other-remote-jobs; that slug 301s
]

HIMALAYAS_ROW_CAP = 4000  # hard cap per run; truncation is logged, never silent


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def title_ok(title):
    return bool(KEEP.search(title)) and not DROP.search(title)


def annualize(amount, period):
    """Normalize a salary figure to $/yr. Period strings vary per board."""
    if amount is None:
        return None
    p = (period or "").lower()
    if "hour" in p:
        return amount * 2080
    if "week" in p:
        return amount * 52
    if "month" in p:
        return amount * 12
    return amount  # yearly or unlabeled


def gate_comp(lo, hi):
    """Band rule (Alex 2026-08-10). Returns (verdict, note).
    verdict: 'pass' | 'lead' (unlisted -> needs JD read) | 'fail'."""
    if hi is None and lo is None:
        return "lead", "comp unlisted"
    top = hi if hi is not None else lo
    if top < COMP_FLOOR:
        return "fail", "band tops out at $%s" % f"{int(top):,}"
    if lo is not None and lo < COMP_FLOOR:
        return "pass", "BAND-STRADDLE: bottom $%s under floor" % f"{int(lo):,}"
    return "pass", ""


def parse_money(text):
    """Best-effort $ figures from a freeform salary string. Returns (lo, hi)."""
    nums = [float(n.replace(",", "")) * (1000 if k else 1)
            for n, k in re.findall(r"\$?\s*([\d,]+(?:\.\d+)?)\s*(k)?", text or "", re.I)
            if n.replace(",", "").replace(".", "").isdigit()]
    nums = [n for n in nums if n > 1000]  # discard hourly fragments and noise
    if not nums:
        return None, None
    return (min(nums), max(nums)) if len(nums) > 1 else (None, nums[0])


# ---------------------------------------------------------------- Himalayas

def himalayas(cutoff):
    # The API silently caps limit at 20 regardless of what is requested, so a
    # day of the firehose is ~200 pages (verified 2026-08-14). Pages are
    # offset-addressable, so fetch them in concurrent waves and stop after the
    # first wave that crosses the cutoff -- sequential fetching took minutes.
    page = 20
    wave = 10  # pages per wave -> 200 rows per wave

    def fetch(offset):
        d = json.loads(_get(
            "https://himalayas.app/jobs/api?offset=%d&limit=%d" % (offset, page)))
        return d.get("jobs", [])

    rows, offset = [], 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=wave) as ex:
        while offset < HIMALAYAS_ROW_CAP:
            pages = list(ex.map(fetch, range(offset, offset + page * wave, page)))
            done = False
            for jobs in pages:
                if not jobs:
                    return rows, False
                for j in jobs:
                    pub = j.get("pubDate")
                    when = (dt.datetime.fromtimestamp(pub, dt.timezone.utc)
                            if pub else None)
                    if when and when < cutoff:
                        done = True  # newest-first; everything after is older
                        break
                    rows.append(j)
                if done:
                    return rows, False
            offset += page * wave
    return rows, True


def gate_himalayas(j):
    locs = j.get("locationRestrictions") or []
    if locs and "United States" not in locs:
        return "fail", "gate1 not US (%s)" % ",".join(locs[:3])
    if (j.get("employmentType") or "") != "Full Time":
        return "fail", "gate2 %s" % j.get("employmentType")
    lo = annualize(j.get("minSalary"), j.get("salaryPeriod"))
    hi = annualize(j.get("maxSalary"), j.get("salaryPeriod"))
    verdict, note = gate_comp(lo, hi)
    if not locs and verdict == "pass":
        note = (note + "; " if note else "") + "worldwide listing, US-eligibility unconfirmed"
    return verdict, note


# ----------------------------------------------------------------- Remotive

def remotive(query, cutoff):
    d = json.loads(_get(
        "https://remotive.com/api/remote-jobs?search=%s&limit=50"
        % urllib.parse.quote(query)))
    rows = []
    for j in d.get("jobs", []):
        pub = j.get("publication_date", "")
        try:
            when = dt.datetime.fromisoformat(pub).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            when = None
        if when and when < cutoff:
            continue
        rows.append(j)
    return rows


def gate_remotive(j):
    loc = j.get("candidate_required_location") or ""
    if loc and not re.search(r"\b(usa|united states|worldwide|anywhere)\b", loc, re.I):
        return "fail", "gate1 %s" % loc
    if j.get("job_type") not in ("full_time", None, ""):
        return "fail", "gate2 %s" % j.get("job_type")
    lo, hi = parse_money(j.get("salary"))
    verdict, note = gate_comp(lo, hi)
    if verdict == "pass" and re.search(r"\bworldwide|anywhere\b", loc, re.I):
        note = (note + "; " if note else "") + "worldwide listing"
    return verdict, note


# ------------------------------------------------------- WeWorkRemotely RSS

def weworkremotely(cutoff):
    rows = []
    for cat in WWR_CATEGORIES:
        try:
            xml = _get("https://weworkremotely.com/categories/%s.rss" % cat)
        except OSError as e:
            print("   ! WWR %s fetch failed: %s" % (cat, e))
            continue
        for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
            def field(tag, blob=item):
                m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), blob, re.S)
                return html.unescape(m.group(1).strip()) if m else ""
            pub = field("pubDate")
            try:
                when = dt.datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S").replace(
                    tzinfo=dt.timezone.utc)
            except ValueError:
                when = None
            if when and when < cutoff:
                continue
            region = field("region")
            rows.append({"title": field("title"), "url": field("link"),
                         "region": region, "category": cat})
    return rows


def gate_wwr(j):
    region = j.get("region") or ""
    if region and not re.search(r"\b(usa|united states|anywhere|north america)\b",
                                region, re.I):
        return "fail", "gate1 %s" % region
    return "lead", "comp unlisted (WWR RSS carries no salary)"


# ------------------------------------------------------------------ BuiltIn

def builtin(query):
    try:
        page = _get("https://builtin.com/jobs/remote?search=%s"
                    % urllib.parse.quote(query))
    except OSError as e:
        print("   ! BuiltIn fetch failed: %s" % e)
        return []
    rows, seen = [], set()
    for m in re.finditer(
            r'href="(/job/[^"]+/(\d+))"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{4,90})', page):
        path, jid, title = m.group(1), m.group(2), html.unescape(m.group(3)).strip()
        if jid in seen or not title:
            continue
        seen.add(jid)
        rows.append({"title": title, "url": "https://builtin.com" + path})
    return rows


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="+")
    ap.add_argument("--days", type=int, default=3, help="max posting age")
    ap.add_argument("--show-declines", action="store_true")
    args = ap.parse_args()

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    print("floor $%s | max age %dd | cutoff %s\n"
          % (f"{COMP_FLOOR:,}", args.days, cutoff.strftime("%Y-%m-%d %H:%M UTC")))

    survivors, leads, declines = [], [], []
    seen_urls = set()

    def sort_hit(source, label, url, verdict, note):
        # The Himalayas feed carries duplicate records for one posting (once
        # with the companyName="name" quirk, once without) -- dedup on URL.
        if url in seen_urls:
            return
        seen_urls.add(url)
        row = (source, label, url, note)
        {"pass": survivors, "lead": leads, "fail": declines}[verdict].append(row)

    # Himalayas: one firehose pull, client-side filter (search param is ignored)
    try:
        rows, truncated = himalayas(cutoff)
        print("== himalayas       %d rows in window%s"
              % (len(rows), " (TRUNCATED at %d -- shrink --days)" % HIMALAYAS_ROW_CAP
                 if truncated else ""))
        for j in rows:
            if not title_ok(j.get("title", "")):
                continue
            verdict, note = gate_himalayas(j)
            # companyName is literally the string "name" on some records (API
            # quirk); the slug is always real.
            company = j.get("companyName")
            if not company or company == "name":
                company = j.get("companySlug", "?")
            label = "%s @ %s" % (j.get("title"), company)
            sal = ("$%s-$%s %s" % (j.get("minSalary"), j.get("maxSalary"),
                                   j.get("salaryPeriod") or "")
                   if j.get("maxSalary") else "unlisted")
            sort_hit("himalayas", "%s | %s" % (label, sal),
                     j.get("applicationLink"), verdict, note)
    except OSError as e:
        print("== himalayas       LANE DID NOT RUN: %s" % e)

    # Remotive: search param works, one call per query
    for q in args.queries:
        try:
            rows = remotive(q, cutoff)
            print("== remotive %-26s %d hits" % ('"%s"' % q, len(rows)))
            for j in rows:
                if not title_ok(j.get("title", "")):
                    continue
                verdict, note = gate_remotive(j)
                sort_hit("remotive", "%s @ %s | %s"
                         % (j.get("title"), j.get("company_name"),
                            j.get("salary") or "unlisted"),
                         j.get("url"), verdict, note)
        except OSError as e:
            print("== remotive %-26s LANE DID NOT RUN: %s" % ('"%s"' % q, e))

    # WeWorkRemotely: RSS, no salary -> leads only
    rows = weworkremotely(cutoff)
    print("== weworkremotely  %d items in window across %d categories"
          % (len(rows), len(WWR_CATEGORIES)))
    for j in rows:
        if not title_ok(j["title"]):
            continue
        verdict, note = gate_wwr(j)
        sort_hit("wwr", j["title"], j["url"], verdict, note)

    # BuiltIn: scraped search page, cards carry no reliable salary -> leads
    for q in args.queries:
        rows = builtin(q)
        print("== builtin %-27s %d cards" % ('"%s"' % q, len(rows)))
        for j in rows:
            if not title_ok(j["title"]):
                continue
            sort_hit("builtin", j["title"], j["url"], "lead",
                     "comp not on card -- read the posting")

    print("\n%d survivor(s), %d lead(s) needing a JD read, %d mechanical decline(s)"
          % (len(survivors), len(leads), len(declines)))
    for label, rows in (("SURVIVORS (gated pass -- verify on employer ATS)", survivors),
                        ("LEADS (pass except comp unlisted -- JD read decides)", leads)):
        if rows:
            print("\n%s" % label)
            for source, text, url, note in rows:
                print("-" * 72)
                print("[%s] %s%s" % (source, text, ("  [%s]" % note) if note else ""))
                print("  %s" % url)
    if args.show_declines:
        print("\nDECLINES")
        for source, text, _url, note in declines:
            print("   x [%s] %-55s %s" % (source, text[:55], note))


if __name__ == "__main__":
    main()
