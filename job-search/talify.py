#!/usr/bin/env python3
"""Missouri Talify discovery lane for /job-search (missouri.talify.com).

Missouri's state talent board (the jobs.mo.gov front-end; apply flows route
through app.jobs.mo.gov). Rails/Turbo, server-rendered -- no Playwright needed.
The data path is `/jobs.json`, which returns {"html": <job cards>, "next_page": N}
at 20 cards a page, and accepts Ransack query params:

    q[work_mode_in][]        remote | hybrid | in_person
    q[employment_type_in][]  full_time | part_time | contract | seasonal | ...
    q[posted_within_days]    integer
    q[compensation_min_gteq] (the ONLY working comp predicate -- see below)
    q[compensation_type_eq]  hourly | monthly | annually

Three facts measured 2026-08-26 that shape the script:

- **The comp threshold normalizes across pay types.** annually=103000,
  hourly=49.5, and monthly=8583 returned the identical 52-job set, and a
  spot-checked hit was listed "annually" -- so one annually-typed query covers
  hourly- and monthly-listed jobs too. Comp is still re-verified client-side
  from each survivor's detail page.
- **`compensation_max_gteq` is silently IGNORED** (not Ransack-whitelisted):
  it returns the unfiltered board, which first showed up as Food Service
  Worker "clearing" a $103K filter. Never trust an unlisted predicate here
  without a positive control, and beware result counts that exactly equal
  your own pagination cap. Band rule is therefore done client-side: the
  server pre-filters at a REDUCED min (LOCAL_PREFILTER) to catch straddling
  bands cheaply, and the detail page's band top is gated at the real floor.
  Known caps: comp-unlisted jobs and bands whose bottom is under the
  pre-filter are invisible to the LOCAL pass.
- **The board is local-first, and that is the lane's value.** The entire board
  held exactly 1 remote job (vs ~1,400 posted in 7 days), so the REMOTE pass
  is expected-dry -- never read that as breakage. The real yield is the LOCAL
  pass: KC-metro seats gated at the onsite floor, same shape as usajobs.py's
  local pass. Honest expectation: the >=103K KC pool is mostly State of
  Missouri trades/corrections/social-services seats; IT titles are rare.

Detail pages are HTML-only (`/jobs/<id>.json` answers 406). They carry the
comp line ("$18.00 - $20.00 hourly" / "$107,085.36 annually") and the JD.

Usage:
    python3 talify.py [--days 3]
"""

import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request

BASE = "https://missouri.talify.com"
COMP_FLOOR = 75_000     # standard remote floor; see gitignored Claude Reference.md
ONSITE_FLOOR = 103_000  # binary on ANY office requirement (feedback_onsite_floor)
LOCAL_PREFILTER = 65_000  # server-side min; real gate is the band top vs ONSITE_FLOOR
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# KC metro, Missouri side. 640xx/641xx covers the metro proper (Belton 64012,
# Lee's Summit 64063, Liberty 64068...); 644xx/645xx is St. Joseph -- excluded.
KC_ZIP_PREFIXES = ("640", "641")

DROP = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|manager|director|chief|architect|"
    r"supervisory|supvy)\b", re.I)
KEEP = re.compile(
    r"\b(analyst|it support|it operations|it specialist|helpdesk|help desk|"
    r"service desk|security|identity|iam|grc|compliance|administrator|"
    r"information technology|m365|intune|endpoint|desktop support|"
    r"technical support)\b", re.I)

COMP_RE = re.compile(
    r"\$([\d,]+(?:\.\d+)?)\s*(?:-\s*\$([\d,]+(?:\.\d+)?)\s*)?"
    r"(hourly|monthly|annually)", re.I)


def fetch(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def cards(params):
    """Yield parsed job cards across all result pages of one query."""
    page = 1
    while page:
        d = json.loads(fetch("/jobs.json", {**params, "page": page}))
        for jid, body in re.findall(
                r'href=["\']/jobs/(\d+)["\'](.*?)</a>', d["html"], re.S):
            yield parse_card(jid, body)
        page = d.get("next_page")
        if page:
            time.sleep(0.5)


def parse_card(jid, body):
    def grab(pat):
        m = re.search(pat, body)
        return html.unescape(m.group(1)).strip() if m else ""
    meta = grab(r"<span>([^<]*·[^<]*)</span>")
    parts = [p.strip() for p in meta.split("·") if p.strip()]
    city = state = zipc = emp_type = mode = ""
    for p in parts:
        m = re.search(r"^(.*?)\s+([A-Z]{2})\s+(\d{5})$", p)
        if m:
            city, state, zipc = m.group(1), m.group(2), m.group(3)
        elif p in ("Full-Time", "Part-Time", "Contract", "Seasonal",
                   "Temporary", "Internship"):
            emp_type = p
        elif p in ("In Person", "Remote", "Hybrid"):
            mode = p
    return {
        "id": jid,
        "company": grab(r"tw-text-blue-gray-700['\"]>([^<]+)<"),
        "title": grab(r"heading ellipsed-text[^>]*>([^<]+)<"),
        "city": city, "state": state, "zip": zipc,
        "emp_type": emp_type, "mode": mode,
        "url": f"{BASE}/jobs/{jid}",
    }


def detail_comp(jid):
    """(lo, hi, raw_text) annualized from the detail page; (None, None, '') if unlisted."""
    try:
        page = fetch(f"/jobs/{jid}")
    except OSError:
        return None, None, "detail fetch failed"
    m = COMP_RE.search(page)
    if not m:
        return None, None, ""
    lo = float(m.group(1).replace(",", ""))
    hi = float(m.group(2).replace(",", "")) if m.group(2) else lo
    unit = m.group(3).lower()
    mult = {"hourly": 2080, "monthly": 12, "annually": 1}[unit]
    return lo * mult, hi * mult, html.unescape(m.group(0))


def gate_comp(lo, hi, floor):
    """Band rule: pass if the band TOP clears the floor; straddle is a flag."""
    if hi is None:
        return None, "comp unlisted"
    if hi < floor:
        return False, "band tops out at $%s (floor $%s)" % (
            f"{int(hi):,}", f"{floor:,}")
    if lo < floor:
        return True, "BAND-STRADDLE: bottom $%s under $%s floor" % (
            f"{int(lo):,}", f"{floor:,}")
    return True, ""


def evaluate(card, floor, bucket):
    """Title filter + detail comp gate; append to the right bucket list."""
    title = card["title"]
    if DROP.search(title):
        bucket["dropped"].append(card)
        return
    if not KEEP.search(title):
        bucket["offlane"].append(card)
        return
    time.sleep(1.0)
    lo, hi, raw = detail_comp(card["id"])
    ok, note = gate_comp(lo, hi, floor)
    card["comp"] = raw or "unlisted"
    card["note"] = note
    if ok is None:
        bucket["leads"].append(card)
    elif ok:
        bucket["survivors"].append(card)
    else:
        bucket["declined"].append(card)


def show(tag, c):
    extra = " [%s]" % c["note"] if c.get("note") else ""
    print("  [%s] %s @ %s%s" % (tag, c["title"], c["company"], extra))
    print("        %s | %s %s %s | %s | %s" % (
        c.get("comp", "?"), c["city"], c["state"], c["zip"],
        c["mode"] or "?", c["url"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="max posting age")
    args = ap.parse_args()
    print("Missouri Talify | remote floor $%s | KC-local onsite floor $%s | max age %dd\n"
          % (f"{COMP_FLOOR:,}", f"{ONSITE_FLOOR:,}", args.days))

    bucket = {"survivors": [], "leads": [], "declined": [],
              "offlane": [], "dropped": []}
    seen = set()

    # Pass 1 -- REMOTE, standard floor. Expected-dry (1 remote job on the whole
    # board when this lane was built); a 0 here is the market, not a bug.
    remote_q = {"q[work_mode_in][]": "remote",
                "q[employment_type_in][]": "full_time",
                "q[posted_within_days]": args.days}
    n = 0
    for c in cards(remote_q):
        n += 1
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        c["pass"] = "REMOTE"
        evaluate(c, COMP_FLOOR, bucket)
    print("== REMOTE pass: %d posting(s)" % n)

    # Pass 2 -- LOCAL KC metro at the onsite floor. Server pre-filter at the
    # reduced min catches straddling bands; the real band-rule gate (top vs
    # ONSITE_FLOOR) runs client-side on the detail page's comp line. Jobs with
    # unlisted comp or a band bottom under the pre-filter never reach this
    # pass -- that coverage cap is real, and it is printed below.
    local_total = 0
    q = {"q[compensation_min_gteq]": LOCAL_PREFILTER,
         "q[compensation_type_eq]": "annually",
         "q[employment_type_in][]": "full_time",
         "q[posted_within_days]": args.days}
    for c in cards(q):
        local_total += 1
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        if c["mode"] == "Remote":
            continue  # pass 1's turf; don't gate remote seats at the onsite floor
        if not (c["zip"].startswith(KC_ZIP_PREFIXES) or
                c["city"].lower() == "kansas city"):
            continue
        c["pass"] = "LOCAL"
        evaluate(c, ONSITE_FLOOR, bucket)
    print("== LOCAL pass: %d posting(s) statewide with listed comp min >= $%s "
          "(comp-unlisted jobs and bands starting lower are invisible here)"
          % (local_total, f"{LOCAL_PREFILTER:,}"))

    print("\n%d survivor(s), %d lead(s), %d declined, %d off-lane, %d senior-title drop(s)"
          % tuple(len(bucket[k]) for k in
                  ("survivors", "leads", "declined", "offlane", "dropped")))
    for c in bucket["survivors"]:
        show(c["pass"], c)
    if bucket["leads"]:
        print("LEADS (comp unlisted on detail page -- JD read decides):")
        for c in bucket["leads"]:
            show(c["pass"], c)
    if bucket["declined"]:
        print("declined:")
        for c in bucket["declined"]:
            show(c["pass"], c)
    if bucket["offlane"]:
        print("off-lane titles (KC metro, cleared comp pre-filter -- Alex can overrule):")
        for c in bucket["offlane"]:
            print("  - %s | %s | %s %s | %s" % (
                c["title"], c["company"], c["city"], c["zip"], c["url"]))
    if bucket["dropped"]:
        print("senior-title drops:")
        for c in bucket["dropped"]:
            print("  - %s | %s | %s" % (c["title"], c["company"], c["url"]))
    if bucket["survivors"] or bucket["leads"]:
        print("\nSurvivors/leads still need status-aware dedup + a listing note; "
              "apply flows route through the Talify page ('Apply Externally').")


if __name__ == "__main__":
    main()
