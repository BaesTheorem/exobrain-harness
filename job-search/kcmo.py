#!/usr/bin/env python3
"""City of Kansas City, MO discovery lane for /job-search.

The city does not post on NEOGOV any more: governmentjobs.com/careers/kcmo
answers "No jobs at this time" while the real board holds 100+ openings.
The real board is a PeopleSoft Candidate Gateway at psweb.kcmo.org, which
kcmo.gov links as "Search Jobs". Executive recruitments (the CISO posting in
2026, the HR Director) can also appear on a kcmo.gov page, so this lane reads
both sources.

Two facts measured 2026-10-06 that shape the script:

- **The PeopleSoft list needs a browser.** The search page loads empty and
  "View All Jobs" is a PeopleSoft postback, so the lane drives a real Chrome
  (patchright, off screen). The list renders every posting in one page
  ("117 jobs found." held 117 cards). The script compares the parsed count
  against that header and prints a COVERAGE line when they differ.
- **Detail pages state a starting pay only** ("Pay Starting at: $5,910 per
  month"), never a band top. A starting pay under the onsite floor does not
  fail the band rule, because the top is unknown. Those rows print as LEADS
  with the starting pay. A starting pay at or above the floor is a survivor.

kcmo.gov sits behind a Cloudflare challenge that curl cannot pass. The same
browser clears it for the executive careers page.

Every posting is an onsite seat in Kansas City, so the onsite floor applies.
The snapshot in state/kcmo-snapshot.json gives the NEW tag; the first run is
a baseline and tags nothing as new.

WATCH titles (CISO and information security leadership) skip the senior
title drop and always print, because Alex asked to track that role
(2026-10-06), whatever the comp or seniority.

Usage:
    python3 kcmo.py            # full pass, then update the snapshot
    python3 kcmo.py --no-save  # read only, snapshot unchanged

INVARIANTS:
- One browser per run. The scan runs once a day; do not poll these sites.
- No compensation floor in this file; floors come from comp_floors.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

UV = os.environ.get("UV", str(Path.home() / ".local/bin/uv"))


def _ensure_patchright() -> None:
    """Re-run this script under uv with patchright when it is not importable."""
    try:
        import patchright  # noqa: F401  (import probe only)
    except ImportError:
        if os.environ.get("KCMO_REEXEC"):
            print("kcmo lane DID NOT RUN: patchright is not available under uv.")
            sys.exit(0)
        os.environ["KCMO_REEXEC"] = "1"
        os.execv(UV, [UV, "run", "--no-project", "--quiet", "--python", "3.12",
                      "--with", "patchright", "python", __file__, *sys.argv[1:]])


from comp_floors import onsite_floor  # noqa: E402  (sys.path set above)

PS = ("https://psweb.kcmo.org/psc/ps/MOBILE/MOBL/c/HRS_HRAM_FL.HRS_CG_SEARCH_FL.GBL"
      "?Action=U&FOCUS=Applicant&SiteId=1")
LIST_URL = PS + "&Page=HRS_APP_SCHJOB"
EXEC_URL = ("https://www.kcmo.gov/city-hall/departments/human-resources/"
            "job-opportunities-at-kcmo/kcmo-executive-careers")
SNAPSHOT = HERE / "state" / "kcmo-snapshot.json"


def detail_url(jid: str) -> str:
    return PS + f"&Page=HRS_APP_JBPST_FL&JobOpeningId={jid}&PostingSeq=1"


WATCH = re.compile(
    r"\b(ciso|chief information security|information security|cyber ?security|"
    r"chief technology|chief information officer)\b", re.I)
DROP = re.compile(
    r"\b(senior|sr\.?|lead|principal|manager|director|chief|architect|"
    r"supervisor|superintendent|division head)\b", re.I)
KEEP = re.compile(
    r"\b(it|information technology|security analyst|cyber|help ?desk|"
    r"service desk|desktop|technical support|systems? admin\w*|"
    r"server admin\w*|network admin\w*|identity|iam|endpoint|m365|"
    r"information services|computer)\b", re.I)
# "Airport Security Officer" and similar are physical-security seats, not IT.
# WATCH is checked first, so "Chief Information Security Officer" is not caught here.
PHYSICAL = re.compile(r"\b(airport|aviation) security\b|\bsecurity (officer|guard)\b", re.I)

CARD_RE = re.compile(
    r"Select\n(.+?)\nJob ID(\d+)\nLocation(.*?)\nDepartment(.*?)\n"
    r"Posted Date(.*?)\nClose Date(.*?)\n")
PAY_RE = re.compile(
    r"\$([\d,]+(?:\.\d+)?)\s*(?:-\s*\$([\d,]+(?:\.\d+)?)\s*)?(?:/|per\s+)?"
    r"(hour|hr|month|mo|year|annually|annual)", re.I)
MULT = {"hour": 2080, "hr": 2080, "month": 12, "mo": 12,
        "year": 1, "annually": 1, "annual": 1}


def classify(title: str, dept: str) -> str:
    if WATCH.search(title):
        return "watch"
    if PHYSICAL.search(title):
        return "offlane"
    if not (KEEP.search(title) or "information services" in dept.lower()
            or "information tech" in dept.lower()):
        return "offlane"
    if DROP.search(title):
        return "dropped"
    return "inlane"


def parse_pay(text: str) -> tuple[float | None, float | None, str]:
    """(lo, hi, raw) annualized from the Pay section. hi is None for a starting pay."""
    sect = text.split("Pay,Benefits", 1)[-1][:1500]
    m = PAY_RE.search(sect)
    if not m:
        return None, None, ""
    mult = MULT[m.group(3).lower()]
    lo = float(m.group(1).replace(",", "")) * mult
    hi = float(m.group(2).replace(",", "")) * mult if m.group(2) else None
    return lo, hi, m.group(0)


def gate(lo: float | None, hi: float | None, floor: int) -> tuple[str, str]:
    """Band rule with the onsite floor. Returns (bucket, note)."""
    if lo is None:
        return "leads", "comp unlisted"
    if hi is None:
        if lo >= floor:
            return "survivors", ""
        return "leads", f"starting pay ${int(lo):,}/yr under the ${floor:,} floor; band top not listed"
    if hi < floor:
        return "declined", f"band tops out at ${int(hi):,} (floor ${floor:,})"
    if lo < floor:
        return "survivors", f"BAND-STRADDLE: bottom ${int(lo):,} under ${floor:,} floor"
    return "survivors", ""


def wait_title(pg, bad: str = "Just a moment", tries: int = 30) -> None:
    for _ in range(tries):
        if bad not in pg.title():
            return
        pg.wait_for_timeout(1500)


def read_board(pg) -> tuple[list[dict], int | None]:
    pg.goto(LIST_URL, timeout=90000, wait_until="domcontentloaded")
    pg.wait_for_timeout(2500)
    pg.get_by_text("View All Jobs").first.click()
    pg.wait_for_timeout(5000)
    for _ in range(15):
        pg.mouse.wheel(0, 20000)
        pg.wait_for_timeout(600)
    text = pg.evaluate("() => document.body.innerText")
    m = re.search(r"(\d+) jobs? found", text)
    header = int(m.group(1)) if m else None
    rows = [{"id": jid, "title": " ".join(t.split()), "location": loc.strip(),
             "dept": " ".join(d.split()), "posted": po.strip(), "closes": cl.strip(),
             "url": detail_url(jid)}
            for t, jid, loc, d, po, cl in CARD_RE.findall(text)]
    return rows, header


def read_detail(pg, jid: str) -> str:
    pg.goto(detail_url(jid), timeout=90000, wait_until="domcontentloaded")
    pg.wait_for_timeout(4000)
    return pg.evaluate("() => document.body.innerText")


def read_exec(pg) -> list[str]:
    """Titles on the kcmo.gov executive careers page (a title line precedes 'Located at')."""
    pg.goto(EXEC_URL, timeout=90000, wait_until="domcontentloaded")
    wait_title(pg)
    pg.wait_for_timeout(2500)
    text = pg.evaluate("() => (document.querySelector('main') || document.body).innerText")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return [lines[i - 1] for i, ln in enumerate(lines) if ln.startswith("Located at") and i]


def show(tag: str, r: dict) -> None:
    extra = f" [{r['note']}]" if r.get("note") else ""
    print(f"  [{tag}] {r['title']} | {r['dept']}{extra}")
    print(f"        {r.get('comp') or '?'} | {r['location']} | posted {r['posted']} "
          f"closes {r['closes']} | job {r['id']} | {r['url']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-save", action="store_true", help="do not update the snapshot")
    args = ap.parse_args()
    _ensure_patchright()
    from patchright.sync_api import sync_playwright

    floor = onsite_floor()
    prev = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {}
    baseline = not prev
    print(f"City of KCMO (psweb.kcmo.org PeopleSoft + kcmo.gov executive page) | "
          f"onsite floor ${floor:,}" + (" | FIRST RUN = baseline" if baseline else "") + "\n")

    bucket: dict[str, list[dict]] = {k: [] for k in
                                     ("watch", "survivors", "leads", "declined", "dropped", "offlane")}
    exec_titles: list[str] = []
    exec_err = ""
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=False,
                              args=["--window-position=-2600,-2600", "--window-size=1200,900"])
        try:
            pg = b.new_page()
            try:
                rows, header = read_board(pg)
            except Exception as e:  # noqa: BLE001  (any browser failure = lane did not run)
                print(f"kcmo lane DID NOT RUN: PeopleSoft board failed: {e}")
                return
            if not rows:
                print(f"kcmo lane DID NOT RUN: 0 postings parsed (header said {header}).")
                return
            print(f"== PeopleSoft board: {len(rows)} posting(s) parsed, header says {header}")
            if header is not None and header != len(rows):
                print(f"~ COVERAGE: parsed {len(rows)} of {header}; the list did not fully render")
            for r in rows:
                r["new"] = not baseline and r["id"] not in prev
                kind = classify(r["title"], r["dept"])
                if kind in ("offlane", "dropped"):
                    bucket[kind].append(r)
                    continue
                lo, hi, raw = parse_pay(read_detail(pg, r["id"]))
                r["comp"] = raw or "unlisted"
                where, r["note"] = gate(lo, hi, floor)
                bucket["watch" if kind == "watch" else where].append(r)
            try:
                exec_titles = read_exec(pg)
            except Exception as e:  # noqa: BLE001
                exec_err = str(e)
        finally:
            b.close()

    print("\n%d watch, %d survivor(s), %d lead(s), %d declined, %d senior-title drop(s), %d off-lane"
          % tuple(len(bucket[k]) for k in
                  ("watch", "survivors", "leads", "declined", "dropped", "offlane")))
    new_n = sum(r["new"] for k in bucket for r in bucket[k])
    print(f"{new_n} posting(s) NEW since the last snapshot" + (" (baseline run)" if baseline else ""))

    if bucket["watch"]:
        print("WATCH (CISO / security leadership, always reported):")
        for r in bucket["watch"]:
            show("NEW WATCH" if r["new"] else "WATCH", r)
    else:
        print("WATCH: no CISO or security leadership posting on the PeopleSoft board.")
    for k, label in (("survivors", "SURVIVORS (starting pay clears the onsite floor):"),
                     ("leads", "LEADS (band top not listed; the JD read decides):"),
                     ("declined", "declined:")):
        if bucket[k]:
            print(label)
            for r in bucket[k]:
                show("NEW" if r["new"] else "seen", r)
    if bucket["dropped"]:
        print("senior IT title drops (Alex can overrule):")
        for r in bucket["dropped"]:
            print(f"  - {r['title']} | {r['dept']} | closes {r['closes']} | {r['url']}")

    if exec_err:
        print(f"\n~ executive careers page not read: {exec_err}")
    else:
        hits = [t for t in exec_titles if WATCH.search(t)]
        print(f"\n== kcmo.gov executive careers: {len(exec_titles)} posting(s): "
              + ("; ".join(exec_titles) or "none"))
        for t in hits:
            print(f"  [WATCH] {t} | {EXEC_URL}")

    if not args.no_save:
        today = date.today().isoformat()
        snap = {r["id"]: {"title": r["title"], "first_seen": prev.get(r["id"], {}).get("first_seen", today),
                          "last_seen": today}
                for k in bucket for r in bucket[k]}
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(snap, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
