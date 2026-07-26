#!/usr/bin/env python3
"""Indeed discovery lane for /job-search.

Indeed 403s plain curl/requests/WebFetch, which is why this lane kept getting
logged as "bot-hostile, skipped". A headless Chromium with a real UA and the
AutomationControlled blink feature disabled does get through: HTTP 200 with the
full server-rendered result list.

Two gotchas worth knowing:
  * The page HTML contains the substring "captcha" even on a clean load (it is
    Indeed's challenge infrastructure being referenced, not served). Do NOT use
    a naive `"captcha" in html` check as a block signal -- it produces a false
    positive on every successful fetch. Count rendered job cards instead; that
    is the positive control that the fetch actually worked.
  * Results embed as JSON in a `window.mosaic.providerData` blob rather than
    being scrapeable from the card markup alone. The blob is the reliable path.

Indeed is a mirror, not a source of truth: it over-reports "remote" and goes
stale. Every hit here still needs confirming on the employer's own ATS before
it earns a listing note.

Usage:
    python3 indeed.py "IT analyst" --days 7
"""

import argparse
import json
import re
import urllib.parse

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Indeed's "Remote" work-attribute facet token.
REMOTE_FACET = "0kf:attr(DSQF7);"

TITLE_DROP = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|manager|director|head of|architect"
    r"|engineer i{3,}|epic|cerner|workday|sap|salesforce|mainframe|gis)\b", re.I)


def fetch(query, days, pages=2):
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        pg = b.new_context(viewport={"width": 1500, "height": 1000},
                           user_agent=UA).new_page()
        for i in range(pages):
            url = ("https://www.indeed.com/jobs?q=%s&l=Remote&sc=%s&fromage=%d&start=%d"
                   % (urllib.parse.quote(query),
                      urllib.parse.quote(REMOTE_FACET), days, i * 10))
            # Indeed throttles intermittently: the same script can 403 one query
            # and 200 the next. Back off and retry rather than writing the lane
            # off as blocked.
            html, cards, status = "", 0, None
            for attempt in range(3):
                r = pg.goto(url, wait_until="domcontentloaded", timeout=45000)
                status = r.status if r else None
                pg.wait_for_timeout(4000)
                html = pg.content()
                cards = html.count("job_seen_beacon")
                if cards:
                    break
                if attempt < 2:
                    wait = 8 * (attempt + 1)
                    print("  page %d: HTTP %s, 0 cards -- backing off %ds"
                          % (i + 1, status, wait))
                    pg.wait_for_timeout(wait * 1000)
            print("  page %d: HTTP %s, %d cards" % (i + 1, status, cards))
            if not cards:
                print("  still no cards after 3 tries -- treat this query as NOT RUN")
                break
            out.extend(parse(html))
        b.close()
    return out


def parse(html):
    """Pull job dicts out of the embedded mosaic provider blob."""
    jobs = []
    m = re.search(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});',
                  html, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            results = (data.get("metaData", {})
                           .get("mosaicProviderJobCardsModel", {})
                           .get("results", []))
            for j in results:
                # jobTypes entries come back as bare strings on some cards and
                # as {"label": ...} dicts on others; normalise both.
                types = []
                for t in (j.get("jobTypes") or []):
                    types.append(t.get("label") if isinstance(t, dict) else str(t))
                try:
                    jobs.append({
                        "title": j.get("displayTitle") or j.get("title"),
                        "company": j.get("company"),
                        "location": j.get("formattedLocation"),
                        "salary": ((j.get("extractedSalary") or {}).get("min"),
                                   (j.get("extractedSalary") or {}).get("max")),
                        "salary_text": (j.get("salarySnippet") or {}).get("text"),
                        "type": types,
                        "age": j.get("formattedRelativeTime"),
                        "url": "https://www.indeed.com/viewjob?jk=%s" % j.get("jobkey"),
                    })
                except Exception as e:
                    # one malformed card must not abort the whole page
                    print("  skipped a card: %s" % e)
        except Exception as e:
            print("  blob parse failed: %s" % e)
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="+")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--pages", type=int, default=2)
    args = ap.parse_args()

    seen, keep = set(), []
    for q in args.queries:
        print("== %s" % q)
        for j in fetch(q, args.days, args.pages):
            if not j["url"] or j["url"] in seen:
                continue
            seen.add(j["url"])
            if j["title"] and TITLE_DROP.search(j["title"]):
                continue
            # Indeed's remote facet leaks: it happily returns Minneapolis /
            # Herndon / Arlington rows for an l=Remote query. Trust the row's
            # own location string over the facet.
            loc = (j["location"] or "").lower()
            if not ("remote" in loc or loc.strip() in ("united states", "")):
                j["remote_suspect"] = True
            keep.append(j)

    print("\n%d post-title-filter of %d unique\n" % (len(keep), len(seen)))
    for j in keep:
        lo, hi = j["salary"]
        comp = j["salary_text"] or (("$%s-$%s" % (int(lo), int(hi))) if lo and hi else "unlisted")
        flag = "  [NOT REMOTE?]" if j.get("remote_suspect") else ""
        print("-" * 72)
        print("%s @ %s%s" % (j["title"], j["company"], flag))
        print("  %s | %s | %s | %s" % (j["location"], comp, ",".join(j["type"]) or "?", j["age"]))
        print("  %s" % j["url"])
    print("\nVerify each on the employer's own ATS before creating a listing note.")


if __name__ == "__main__":
    main()
