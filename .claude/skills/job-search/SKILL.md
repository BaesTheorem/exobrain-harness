---
name: job-search
description: Job search assistant -- audit postings for fit, research companies/people, tailor ATS-compliant cover letters, and track weekly application volume via email confirmations. Use when the user shares a job posting, asks to write a cover letter, wants company research, asks "how many apps this week", "audit this role", "is this a good fit", "help me apply", "job search status", "application tracker", or mentions applying to jobs.
---

# Job Search

Alex is actively job hunting. This skill handles the full pipeline: evaluating fit, researching the company, tailoring cover letters, and tracking application volume.

**Weekly goal**: 10-20 applications submitted per week.
**Compensation floor**: see gitignored `Projects/Get new job/Claude Reference.md` for the current floor. **Band rule (Alex 2026-08-10): a listed salary range passes gate 3 if the floor falls anywhere within it.** DQ only when the TOP of the band is below the floor. A band whose bottom is under the floor is a pass-with-flag: surface it and note the risk that the offer lands below the floor. A single listed number must meet the floor outright. If salary is unlisted, still include the role but flag the unknown comp.

**Two lanes, two gate sets.** The standard lane (remote-only, full-time permanent) covers everything below unless stated otherwise. Paid **AI safety fellowships** run location-agnostic on a modified gate set with a higher floor when relocation is required -- see "AI Safety Fellowship Lane" before scanning or auditing one.

## Sources of Job Listings

Use multiple sources and triangulate -- no single source is authoritative for "open and accepting applications." **Don't lean on a single source** -- title-only LinkedIn search misses listings on firm-careers portals and ATS boards that don't crosspost, and misses responsibility-matching roles whose titles wouldn't make the title pre-filter.

1. **Gmail job alerts** (Indeed, LinkedIn, Dice, ZipRecruiter) -- see `/email` for query syntax. Read full email bodies; dedupe across sources.

   **This is a first-class discovery lane, not a formality** (proven 2026-07-25: a scan that ran LinkedIn + ATS X-ray found 1 candidate; the alert lane then produced **31 distinct roles that appeared in none of those searches**, including the day's best find, ABS Kids IT Security Analyst at $85-115K). LinkedIn's alert engine matches on saved-search criteria the MCP `search_jobs` call does not reproduce, so the two lanes surface genuinely different pools. Never treat one as covering the other.

   **Do not confuse this with the tracker Gmail search.** Application confirmations and rejections are tracker maintenance; the *alert* emails are discovery. Running one does not cover the other. Both are required.

   **Method** (alert emails are ~180-350KB of HTML each and will blow up context if read directly):
   1. `search_threads` with `(from:indeed.com OR from:linkedin.com OR from:dice.com OR from:ziprecruiter.com) (jobs OR "job alert" OR "new jobs" OR recommended) newer_than:4d`, `pageSize` 30.
   2. `get_thread` on each hit. It will exceed the token cap and auto-save to a file -- that is the intended path, and the error message is cheap. Do **not** try to read the body inline.
   3. Extract job IDs paired with titles from the saved files:
   ```python
   import json,re,glob,os,html
   for f in sorted(glob.glob('mcp-claude_ai_Gmail-get_thread-*.txt'),key=os.path.getmtime):
       d=json.load(open(f))
       for m in d.get('messages',[]):
           body=m.get('htmlBody') or m.get('plaintextBody') or ''
           for jid,txt in re.findall(r'/jobs/view/(\d{8,12})[^>]*>\s*([^<]{3,90})',body):
               print(jid, html.unescape(re.sub(r'\s+',' ',txt)).strip()[:70])
   ```
   4. **Each alert email contains ~6 roles, not just the one in the subject line.** Harvest all of them; the subject-line role is often the weakest. Dedupe job IDs across emails (heavy repost overlap) and against the Job Listings folder, apply the title pre-filter, then `get_job_details` on survivors in paced batches of 2-4.

   **Expect heavy decay.** Alerts lag: of 8 roles JD-read on 2026-07-25, three were already "No longer accepting applications" (Ascension, Blackpoint Cyber) or removed entirely (ePlus, invalid job ID). Read the freshest alerts first and don't invest in anything older than ~3 days without confirming it's still open. Also expect the staffing-firm glut here (nTech Workforce's ICAM role was a 12-month W2 contract) -- Gate 2 catches these.
2. **LinkedIn MCP** (`mcp__linkedin__search_jobs`, `get_job_details`) -- see `/linkedin` for read-only rules and pacing. Good for discovery by keyword + location, and for cross-checking listings found elsewhere. Also the source for hiring-contact lookup (`get_company_employees`) on Strong-Fit roles.
3. **Google search via WebSearch** (NEW -- added 2026-05-19 after Alex flagged LinkedIn-only blind spot):
   - **X-ray search ATS boards**: `site:boards.greenhouse.io "<keyword>" remote`, `site:jobs.lever.co "<keyword>" remote`, `site:jobs.ashbyhq.com "<keyword>" remote`, `site:apply.workable.com "<keyword>" remote` -- these often surface listings not crossposted to LinkedIn
   - **Niche remote job boards -- do NOT X-ray these anymore** (superseded 2026-08-14): Himalayas, BuiltIn, WeWorkRemotely, and Remotive are now queried through their own data paths by `Exobrain harness/job-search/nicheboards.py` (see Source #10 below). Google's index of these boards lags and its `site:` filters silently return other domains, which is what kept logging the lane as dry. Only RemoteRocketship still needs the browser (Cloudflare-walled); surface its URLs for Alex to spot-check.
   - **Firm careers portals**: search by responsibility keyword without site filter to surface direct-to-employer postings (`"phishing remediation" "remote" careers`)
   - **Search by JD responsibility keywords, NOT just titles** (the killer feature -- see "Responsibility-keyword search" below). Alex's title-only filter misses roles whose JDs match his daily work but whose titles he'd otherwise skip.
4. **Firm careers portals direct** -- the firm's own site is the most reliable signal that a role is still open. Cross-check aggregator hits against the firm portal.
5. **ATS Boards APIs** (Greenhouse, Lever) -- strongest positive verification path. See mode 1 step 3 below for direct API URLs.
6. **Alex-provided URLs and pasted postings** -- treat as a starting point, still run the audit + verification.
7. **80,000 Hours job board** (https://jobs.80000hours.org) -- ALWAYS include in every search (Alex standing instruction 2026-06-17). Aggregates high-impact roles at EA / AI-safety / AI-policy orgs that don't crosspost to LinkedIn or mainstream ATS. Surface ops / IT / security / compliance / analyst roles (US/remote), not just research. Connects to Alex's EA / AI-governance pivot track.

   **Query it via Algolia, not the page** (solved 2026-07-25; earlier scans wrongly logged this lane as "JS-rendered, unreadable" and skipped it). The board is a Nuxt SPA, so WebFetch returns only the shell, and a `site:jobs.80000hours.org` X-ray **silently returns Built In results instead of failing** -- that false negative is what made the lane look dry. Its search is Algolia, and the public front-end keys live in the homepage HTML under `window.__NUXT__.config.public` (re-extract if these rotate):

   ```bash
   curl -s -X POST "https://W6KM1UDIB3-dsn.algolia.net/1/indexes/jobs_prod/query" \
     -H "X-Algolia-API-Key: d1d7f2c8696e7b36837d5ed337c4a319" \
     -H "X-Algolia-Application-Id: W6KM1UDIB3" \
     -H "Content-Type: application/json" \
     -d '{"query":"information security","hitsPerPage":25,"attributesToRetrieve":["title","company_name","tags_location_80k","tags_location_type","tags_role_type","tags_exp_required","salary","url_external","closes_at"]}'
   ```

   **Search the IT/ops lane, not just AI safety** (Alex standing instruction 2026-07-25). Free-text queries like `"IT analyst"` are near-useless here -- they return alignment researchers and security *engineers* because that's what dominates the corpus. Use the **facets** instead, which is the structural filter:

   ```bash
   -d '{"query":"","hitsPerPage":60,
        "facetFilters":[["tags_skill:Information security","tags_skill:Operations"],
                        ["tags_role_type:Full-time"],
                        ["tags_location_type:Remote"]],
        "attributesToRetrieve":["title","company_name","tags_location_80k","tags_exp_required","salary","url_external"]}'
   ```

   Facet vocabulary (probe with `"facets":["tags_skill","tags_role_type","tags_location_type"]`): `tags_skill` = Research 344, Software engineering 205, Policy 168, **Operations 166**, **Information security 118**, Strategy, Outreach, Management, Finance, Legal. `tags_role_type` = **Full-time 587**, **Fellowship 66**, Internship 56, Funding 33, Part-time 30, Volunteering 30, Course 16. That combination returns ~59 hits vs the handful keyword search finds.

   **Run the `Fellowship` facet as its own second query** (Alex standing instruction 2026-07-25). Paid AI safety fellowships are now in the pipeline on their own gate set -- see "AI Safety Fellowship Lane" below. Do **not** filter this query to `tags_location_type:Remote`; the lane is location-agnostic and the remote filter drops the in-person and relocation programs that are most of it (only 234 of ~800 listings carry any location-type tag at all).

   **Honest expectation for this lane**: the board carries essentially **no corporate IT-analyst / helpdesk / sysadmin roles** -- 7 IT-lane keyword queries on 2026-07-25 surfaced zero. What it does carry that fits Alex is the **Operations Associate/Coordinator** band and occasional infosec-adjacent analyst roles. Still run it every pass (cheap, one call), but expect ops-track hits rather than IT-track hits, and don't read a dry result as the lane being broken.

   For the standard (non-fellowship) lane, filter on `tags_location_type` containing `Remote` and `tags_location_80k` containing `USA`/`Remote, USA`. **Still verify against the primary posting** -- `url_external` usually points at Greenhouse/Ashby, so hit the ATS API to confirm open + read the real JD. The index blurb is not evidence: on 2026-07-25 the Anthropic AI Security entry looked like a strong entry-level remote-US hit, and the Greenhouse API showed it was a 4-month fixed-term fellowship requiring Python fluency. Under the standard gates that was a gate-2 DQ; under the fellowship lane (added later the same day) it is a **candidate** -- fixed-term is expected there, Python is claimable, and the stipend annualizes well past the floor. Re-audit it on the next pass rather than trusting the old DQ.
8. **Dice, Indeed, and Hiring.cafe** (ADDED 2026-07-22, Alex standing instruction) -- scan all three directly on every discovery pass, in addition to (not instead of) the Gmail alerts from them. These carry a different employer mix than LinkedIn/ATS X-ray and each other; triangulate.
   - **Dice** (https://www.dice.com) -- tech-heavy board, good for IT/security/identity. Search UI: `https://www.dice.com/jobs?q=<keywords>&location=Remote&filters.postedDate=SEVEN&filters.employmentType=FULLTIME`. Dice is JS-rendered but its search backend is reachable: try the `WebFetch` of the search URL first; if it doesn't return listings, use `WebSearch` `site:dice.com "<responsibility phrase>" remote`. **Watch for the staffing-agency/C2C recruiter glut** -- Dice is dense with corp-to-corp contract reqs and body-shop reposts (the AARATECH / RemoteHunter pattern). Aggressively apply Gate 2 (permanent, no contract/C2C/1099) and the body-shop smell test (tiny firm, req posted by a developer, no real JD).
   - **Indeed** (https://www.indeed.com) -- largest volume. WebFetch and plain curl 403, which is why this lane kept getting logged as "bot-hostile, skipped". **It is reachable.** Run `Exobrain harness/job-search/indeed.py "<query>" --days 7`, which drives headless Chromium with a real UA and `--disable-blink-features=AutomationControlled`; that returns HTTP 200 with the full result list. Three durable gotchas baked into that script (solved 2026-07-26):
     - **Never use `"captcha" in html` as a block signal.** The string is present in Indeed's markup on a *clean* 200 load, so that check false-positives on every successful fetch and is what made the lane look permanently walled. The positive control is the rendered **job-card count** (`job_seen_beacon`); zero cards means blocked, nonzero means you got real data.
     - **Throttling is intermittent, not permanent.** The same script routinely 403s one query and 200s the very next. The script retries 3x with backoff; only after that does a query count as NOT RUN. One 403 is not evidence the lane is dry.
     - **The remote facet leaks.** An `l=Remote` query happily returns Minneapolis / Herndon / Arlington rows, so trust each row's own location string over the facet. The script flags mismatches `[NOT REMOTE?]`.
     Indeed is still a mirror, not a source of truth: it over-reports "remote" and goes stale, so verify every hit on the **employer's own careers page / ATS**. If a role only exists on Indeed and can't be confirmed on a primary source, mark "verification incomplete -- Alex must spot-check."
   - **Hiring.cafe** -- fast aggregator with genuinely structured job data, the cleanest lane in the pipeline to gate mechanically. Run `Exobrain harness/job-search/hiringcafe.py "<query>" [...] --days 14`. Durable facts (solved 2026-07-26):
     - **The host is `hiringcafe.com`, NOT `hiring.cafe`.** The old domain redirects in a browser but is not the app; hitting `hiring.cafe/api/search-jobs` returns 401 on GET and 405 on POST, which is what made this lane look auth-walled. There is no such REST API.
     - The working data path is the **Next.js page-data route** `https://hiringcafe.com/_next/data/<BUILD_ID>/index.json?searchState=<url-encoded JSON>`. Plain curl with a browser UA is enough -- no auth, no Playwright. `BUILD_ID` rotates on every deploy, so scrape it from `"buildId":"..."` on the homepage each run rather than pinning it.
     - Each hit's `v5_processed_job_data` carries **structured fields that map directly onto the four hard gates**: `workplace_type`, `workplace_countries`, `commitment`, `yearly_min/max_compensation`, `is_compensation_transparent`, `bachelors_degree_requirement`, `min_industry_and_role_yoe`, `security_clearance`, `estimated_publish_date_millis`. Gate on those rather than parsing prose.
     - Expect a **low survivor rate and do not read that as breakage** -- 245 unique postings across 4 queries yielded 1 survivor on 2026-07-26. The volume is real; the gates are just strict.
     It's an aggregator, so it points to an underlying source -- **follow through to the primary posting (employer ATS/careers page) and verify there**, same as any aggregator mirror.
   - All three feed the **same 4-gate filter, dedup, and per-listing-note pipeline** as every other source. Rotate keyword angles across days like the other lanes.
9. **AI safety fellowship boards + program pages** (ADDED 2026-07-25, Alex standing instruction) -- see "AI Safety Fellowship Lane" below for the gate variant. Two sources, both verified live 2026-07-25:
   - **80,000 Hours Algolia, `tags_role_type:Fellowship` facet** (source #7 above, second query, no remote filter) -- 66 live entries. This is the highest-yield single call in the lane.
   - **AISafety.com/jobs** (https://aisafety.com/jobs, alias https://aisafety.careers) -- community-maintained board, 475 jobs + a separate 42-entry "Events & training" section that carries fellowships and residencies, timestamped "last updated" on the page. Server-rendered (~1.1MB HTML), so `curl` + a tag strip works; no JS needed.
   - **Hardcoded program sources -- check every pass** (Alex standing instruction 2026-07-25; all six verified HTTP 200 on that date). These are first-class sources alongside the 80k board, not a rotation. Do not substitute a board listing for the program's own page: the boards lag cohort openings, and these pages carry the real deadline.

     | Source | URL | Notes |
     |---|---|---|
     | GovAI | https://www.governance.ai/opportunities | Runs several distinct programs (DC Fellowship, Research Scholars, Research Fellows, Summer/Winter Fellowships) off one page -- read all of them, don't stop at the first. |
     | IAPS | https://www.iaps.ai/fellowship | AI Policy Fellowship. |
     | Horizon Institute | https://horizonpublicservice.org/programs/become-a-fellow | The one with an open fit-audit; wide posted band on a DC-metro relocation, so see the straddling-range rule below. |
     | Talos Network | https://www.talosnetwork.org/talos-fellowship | EU-focused AI policy fellowship -- check work authorization explicitly. (An earlier guessed `talosfellowship.eu` was dead; this is the live domain.) |
     | US policy fellowship database (Airtable, via BlueDot) | https://airtable.com/app3AlIYjrAVYhvIe/shr1dGfy6WQfJ5mei/tblD3ExDW2P8mtVlj | 35-row index of recurring US policy fellowships. Treat as a **directory of what to go check**, not a data source. |
     | RAND CAST | https://www.rand.org/global-and-emerging-risks/centers/ai-security-and-technology/fellows.html | Center on AI, Security, and Technology fellows. This is the canonical path -- do not guess a rand.org URL, an earlier guess 404'd. |

     **Reading the Airtable base** (it is JS-only and bot-hostile -- plain `curl` gets UA-sniffed to Airtable's marketing homepage, and the `readSharedViewData` API 401s without a session cookie). Playwright works; `networkidle` never fires because Airtable long-polls, so wait on `domcontentloaded` plus a fixed delay:

     ```python
     from playwright.sync_api import sync_playwright
     with sync_playwright() as p:
         b = p.chromium.launch()
         pg = b.new_page(viewport={"width": 1800, "height": 1200})
         pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
         pg.wait_for_timeout(12000)
         rows = []
         for _ in range(35):                       # grid is virtualized -- scroll to see all 35
             rows += pg.inner_text("body").split("\n")
             pg.mouse.wheel(0, 1500); pg.wait_for_timeout(600)
         b.close()
     ```

     Only the Name column renders at that viewport; other fields need horizontal scroll or a row click. That's fine for its actual job -- it tells you which programs exist (Horizon, TechCongress x2, RAND CAST, GovAI x4, IAPS, LawAI, AAAS, Scoville, Mirzayan, PIF, White House Fellows, and ~20 more), and you then verify each on its own site.
   - **Secondary program pages**, worth a rotating 2-3 per pass rather than all every day (verified 200 on 2026-07-25): [MATS](https://www.matsprogram.org), [Anthropic Fellows](https://alignment.anthropic.com/fellows-program), [Constellation Astra](https://www.constellation.org/programs/astra-fellowship), [TechCongress](https://www.techcongress.io), [Pivotal](https://www.pivotal-research.org), [ERA](https://www.erafellowship.org), [LASR Labs](https://www.lasrlabs.org), [Apart Research](https://www.apartresearch.com), [Successif](https://successif.org).
   - **Never state a deadline, stipend, or cohort date from memory.** These change every cycle and are exactly the kind of claim that gets hallucinated. Read the program's own page and quote it, or mark the field unknown.

10. **Niche boards via direct data paths** (ADDED 2026-08-14, replacing the Google X-ray of these boards) -- run `python3 "Exobrain harness/job-search/nicheboards.py" "<angle1>" "<angle2>" --days 3` every discovery pass. One script, four boards, no search engine in the loop. Verified data paths (2026-08-14):
   - **Himalayas** -- documented public JSON API at `himalayas.app/jobs/api?offset=&limit=`, ~99K jobs, newest-first, full structured fields (salary + period, employmentType, locationRestrictions, pubDate, expiryDate, applicationLink). Two gotchas baked into the script: the `search` param is **ignored** (filtering is client-side), and the API silently caps `limit` at 20, so offset must advance by the actual page size or you skip 4 of every 5 jobs.
   - **Remotive** -- documented API at `remotive.com/api/remote-jobs?search=`, working search param. Salary is freeform text, parsed best-effort; expect thin, mixed-quality results.
   - **WeWorkRemotely** -- plain RSS per category. The "all other" slug is `all-other-remote-jobs` (NOT `remote-all-other-remote-jobs`, which 301s). RSS carries no salary, so WWR hits can never pass gate 3 mechanically -- they surface as **LEADS**.
   - **BuiltIn** -- server-rendered search page (`builtin.com/jobs/remote?search=`) with a browser UA; job cards carry `data-builtin-track-job-id`. Cards rarely show comp -- **LEADS**.

   The script pre-applies the gates on structured fields (band rule included) and the title pre-filter, then prints three buckets: **survivors** (gated pass -- verify on the employer ATS like any aggregator hit), **leads** (pass except comp unlisted -- a JD read decides, per the unlisted-comp rule), and declines. Himalayas is a firehose (hundreds of postings per hour), so keep `--days` small (1-3) and treat its `TRUNCATED` warning as a real coverage gap, not noise.

11. **ATS-direct watchlist** (ADDED 2026-08-14 -- the anti-search-engine lane) -- run `python3 "Exobrain harness/job-search/ats-watchlist.py"` every discovery pass. Polls the **full live posting list** of every employer we have ever tracked, straight from the ATS APIs (Greenhouse `boards-api.greenhouse.io/v1/boards/<board>/jobs`, Lever `api.lever.co/v0/postings/<board>`, Ashby `api.ashbyhq.com/posting-api/job-board/<org>`), and diffs against yesterday's snapshot. Zero index lag; a posting that never crossposts anywhere surfaces the morning it goes up.
   - The watchlist **builds itself** from every `type: job-listing` note (Job Listings folder AND `Archive/`), so it automatically covers the re-apply watchlist (`reapply: true` employers are in the tracker by construction). Pin extra boards in `job-search/state/watchlist-extra.json` (`{"<ats>:<board>": {"why": "..."}}`) -- e.g. a warm-connection employer with no note yet.
   - First poll of a board is a **baseline** (counts only); the new-posting diff starts on the second run. State lives in the gitignored `job-search/state/` (the employer list reveals where Alex applies -- keep it out of the public repo).
   - New postings are pre-filtered by title but NOT gated -- each still needs the JD read + 4 gates + dedup before a note is written. A board that 404s may mean the company left that ATS; check where its careers page points now before deleting the listing-note reference.

12. **USAJOBS** (ADDED 2026-08-14) -- run `python3 "Exobrain harness/job-search/usajobs.py" "<angle1>" "<angle2>" --days 7` every discovery pass. The official federal API (`data.usajobs.gov/api/search`), free but keyed: `USAJOBS_API_KEY` + `USAJOBS_EMAIL` in the harness `.env` (request at https://developer.usajobs.gov/apirequest/). Without a key the script prints instructions and exits 0 -- report the lane as skipped-with-reason, never as failed. Why this lane earns its slot: federal remote IT/security postings mostly never reach commercial boards, many accept experience in lieu of a degree, and Public Trust eligibility (which Alex has) is a common bar. The script runs **two passes per query** (Alex standing instruction 2026-08-14): a nationwide REMOTE pass gated at the standard floor, and a LOCAL pass (Kansas City, MO + 30mi radius) gated at Alex's **onsite floor** -- his onsite floor is binary on any office requirement, one day a week or five, so the whole local pass gets the higher bar (both values live in the script constants; the onsite rationale in the `feedback_onsite_floor` memory). Local survivors are onsite/hybrid federal seats in his home metro, no relocation. Comp is gated mechanically after annualizing hourly bands. Two API quirks baked into the script: `PositionSchedule` Name carries tour-of-duty prose ("Monday-Friday 8:00am...") so full-time is gated on schedule **Code 1**, and keyword matching is loose enough to return transportation roles for "information technology", so an in-lane KEEP title filter applies. Federal postings close on **hard deadlines** and usually want the USAJOBS-profile resume format -- capture the close date on the note and flag anything closing inside 14 days.

   **Honest expectation for this lane (measured 2026-08-14, key live):** the federal remote market has collapsed under the return-to-office mandate -- `RemoteIndicator=True` with NO other filters returned **32 postings across the entire federal government** (vs 10,000+ unfiltered), nearly all physicians/radiologists/immigration judges, zero IT-series. The param was instrument-checked (positive control: same query without it returned 146 for one keyword), so a 0-survivor day here is the market, not a bug. Keep the lane (one API call, and agency exceptions or a policy change would reopen it overnight); just never read its dryness as breakage, same as the 80k IT-lane expectation. The LOCAL pass has its own measured squeeze (first read-through, 2026-08-14, 4-for-4): KC postings clearing the $103K onsite floor are GS-13/14, whose Selective Placement Factors and conjunctive specialized-experience blocks are senior-specialist walls Alex fails honestly, while the grades he could clear (GS-9/11/12 customer-support 2210s) top out under the floor. Expect thin local yield; the realistic local hit is an SPF-free customer-support 2210 at GS-13, or a GS-12 whose band top clears $103K (band rule).

13. **Workday-direct boards** (ADDED 2026-08-26) -- run `python3 "Exobrain harness/job-search/workday.py"` every discovery pass. Sibling of lane 11 against the ATS that lane cannot see: `ats-watchlist.py` covers Greenhouse/Lever/Ashby, but a large share of mid-market and enterprise employers host on Workday, and those postings frequently never crosspost. Every Workday tenant exposes an unauthenticated JSON endpoint behind the SPA:

    ```
    list    POST https://<host>/wday/cxs/<tenant>/<site>/jobs
            {"appliedFacets": {...}, "limit": 20, "offset": N, "searchText": ""}
    detail  GET  https://<host>/wday/cxs/<tenant>/<site><externalPath>
    ```

    Like lane 11, the watchlist **builds itself** from every `type: job-listing` note (tracker AND `Archive/`), so Workday employers already in the tracker are polled free and their reposts surface -- this is the concrete fix for the gap lane 10 names ("check boards OUTSIDE the three polled ATSes (Workday, iCIMS, SuccessFactors...)"). Pin a specific board, with filters, using `--add`.

    Why this lane is unusually cheap per posting:
    - **A board URL's query params ARE gates 1 and 2, applied server-side.** A filtered URL (`?Location_Country=<US>&timeType=<Full time>&locations=<Remote, USA>`) returns an already-filtered set instead of the employer's whole req list. `--add "<url>"` parses those params straight out of the URL, so pinning a recruiter-shared or hand-filtered board takes one command.
    - **The detail endpoint carries the comp band in the JD**, so gate 3 is mechanical (band rule + hourly annualization) with no browser.
    - **`canApply` / `posted` are the ATS's own answer to "still open."** That is the apply-flow signal the verification section demands, not the "listing page renders" signal it warns about -- so a Workday survivor arrives already verified, and the detail call also returns the full JD for the note's archive callout.

    **Facet IDs are opaque per-tenant GUIDs and are NOT portable between employers.** Never hand-copy one board's GUID onto another tenant. `--add` resolves and prints each facet's human label plus its open count, which is the positive control that the filter means what the URL implied -- run it and read the labels before trusting a pinned board.

    Two gate bugs found and fixed on the first live run (2026-08-26), both worth knowing because they generalize to any ATS lane:
    - **The location field is a coarse bucket, not the truth.** Gating remote on the literal word "remote" silently killed an employer's entire remote inventory: Cigna posts every remote req as "United States Work at Home". The regex now covers work-at-home / work-from-home / telecommute / home-based / WFH / virtual / anywhere.
    - **Title and location contradict each other, and the title wins.** CrowdStrike's "Analyst I, Falcon Complete GovCloud (Hybrid, St Louis)" sits under location "USA - Remote". A hybrid/onsite marker in *either* field is now a gate-1 decline with the contradiction quoted.

    **Warm-referral boards**: pin with `--add ... --warm` when the employer is in the warm-connection lane. Those rows print a `** WARM REFERRAL **` tag in every bucket (including declines, so Alex can overrule a gate he'd never overrule cold), and their **off-lane titles are listed rather than silently dropped** -- at an employer where Alex has an inside path, a referral outweighs a title match, so he triages those himself. Marking a board warm does NOT create a remote-gate exception; that still needs Alex's explicit per-firm opt-in, same as the documented one. Identities and referral context live in the gitignored vault reference, never here.

    Survivors still need status-aware dedup and a listing note; `--full` re-gates everything instead of only the diff, and first poll of a board is a baseline.

### Specific employer boards to watch (warm-connection lane)

Some employers get scanned directly on every discovery pass because Alex has an inside referral path there -- a warm intro is worth more than cold volume, so these clear a lower bar than the open market. **The specific employers, their careers-portal URLs, the referral context, and any per-employer gate exceptions live in the gitignored `Projects/Get new job/Claude Reference.md` under "Warm-Connection Watch Lane" -- read it at the start of every scan and scan each firm listed there on top of the open-market search.** Employer identities and referral details are kept out of this file because the repo is public.

Generic handling for this lane:
- Scan each listed firm's careers portal every discovery pass, in addition to the open-market boards. Apply the per-firm filtering notes from the reference (which roles to target, which org areas / locations to skip).
- A firm in this lane may carry a **documented remote-gate exception**: if the reference marks it as a warm-referral hybrid opt-in (Alex in-metro, no relocation, comp confirmed), do NOT auto-DQ its roles for being hybrid/in-office -- still apply the other three gates (full-time permanent, comp at or above the floor in the gitignored Claude Reference.md or strong inference, ≥80% strong fit) normally. Exceptions are per-firm and per-connection; they don't generalize to other hybrid employers. Watch the actual reporting location -- an "onsite" role reporting to an out-of-state project site is relocation, not local-hybrid; flag those.

### Responsibility-keyword search (the title-blind-spot fix)

Don't limit search keywords to titles like "IT Analyst" / "Security Analyst" / "GRC Analyst". Use **responsibility phrases** from Alex's actual day-to-day work, because employers describe roles in JD bullets even when the title is unusual. From the Claude Reference, Alex's transferable responsibility keywords:

- **Identity & Access**: "Entra ID security groups", "Azure AD group management", "access provisioning", "access reviews", "SSO/MFA configuration", "IAM provisioning"
- **Phishing & Email Security**: "phishing email analysis", "phishing remediation", "Exchange message trace", "compromised account response", "phishing triage"
- **Endpoint & Device**: "Microsoft Intune", "endpoint security", "lost/stolen device triage", "device wipe", "device lifecycle"
- **Cloud & Virtual Desktop**: "Azure Virtual Desktop support", "AVD support", "Citrix Virtual Desktop support", "M365 administration", "Microsoft 365 admin"
- **Cross-timezone IT**: "global IT support", "cross-timezone IT", "SLA-driven IT support", "follow-the-sun support"
- **Legal-tech (law firm angle)**: "iManage", "Elite 3E", "Intapp", "law firm IT"
- **Frameworks (GRC angle)**: "NIST CSF", "NIST AI RMF", "SOC 2 evidence", "vendor risk assessment", "phishing simulation"
- **Current title fair game**: "IT Analyst" -- Alex's current title, common at law firms and mid-market enterprises

These responsibility searches surface listings titled things like "Information Security Engineer", "Identity Administrator", "Endpoint Specialist", "Risk Analyst", "IT Coordinator" -- where the JD responsibilities map 80%+ to Alex's work even though the title would normally be filtered.

**Title pre-filter caveat**: the LinkedIn-search-result title pre-filter (drop Senior/Sr/Lead etc.) applies only when reading LinkedIn search snippets *before* JD reads -- to save MCP budget. For Google/WebSearch results, each search result IS a JD page, so read it directly and evaluate by the 4-gate filter without pre-screening titles.

## Resume Reference

**Resume PDF**: `/Users/alexhedtke/Exobrain/Projects/Get new job/Alex_Hedtke_Resume.pdf`
Read the PDF at the start of any audit or cover letter to ensure you're working from the latest version.

**Key background**: Read the resume PDF at the path above at runtime to get current experience, skills, certifications, and leadership history. Do not hardcode resume details in this skill -- the PDF is the source of truth and may be updated independently.

## Resume + Cover Letter Generation (use the builder)

Do NOT hand-build resume/cover-letter HTML per JD anymore. Use the reusable builder at `Exobrain harness/resume-builder/` (see its README):

**Artifact output location (standing rule, Alex 2026-06-24, broadened 2026-07-15): stash every generated artifact -- resume, cover letter, interview prep doc, research -- in the listing's own folder, NOT in `~/Downloads/` or loose in the project root.** Each job we apply to or build ANY artifact for gets a dedicated folder at `Projects/Get new job/Job Listings/<Company> - <Role>/` that holds the listing note plus all its artifacts (PDFs, interview prep `.md`s, research `.md`s) (see "Per-Listing Notes" below for the folder-promotion mechanics). Pass the builder's `--out` flag to write straight into that folder. Keep the human filename (`Alex_Hedtke_Resume_<Tag>.pdf` / `Alex_Hedtke_Cover_Letter_<Tag>.pdf`) -- it's part of the ATS defense and is what Alex uploads. Do not also leave a copy in Downloads.

- **Tailored resume**: write a surgical `tailoring/<company>.json` (overrides: `summary`, `skills_append` per row, `experience_bullets` per job id `clyde`/`geeksquad`), then `python3 build.py resume --tailor tailoring/<company>.json --out "/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings/<Company> - <Role>/Alex_Hedtke_Resume_<Tag>.pdf"`.
- **Cover letter**: write the letter body (date line down) to a `.md`, run `/de-ai` on it, then `python3 build.py cover --md <file>.md --company "<Name>" --tag <Tag> --out "/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings/<Company> - <Role>/Alex_Hedtke_Cover_Letter_<Tag>.pdf"`.
- The builder's `tailoring/*.json` and `*.md` inputs stay in the harness repo (gitignored); only the rendered PDF outputs go to the listing folder in the vault.
- Canonical resume content lives in `resume-builder/data/resume_data.json` (source of truth). Tailoring rules are still surgical-only per [[Claude Reference]]; the builder does not relax them.
- The builder bakes in the document-side ATS / AI-screening defenses (clean metadata, selectable single-column text, human filename, no Skia/Chrome fingerprint). The **prose** defense is still yours: run `/de-ai` on every tailored summary/bullet and cover letter. Full rationale: [[ATS & AI-Screening Playbook]] (`Projects/Get new job/`). Read it before tailoring.

## JD Scorecard Simulation (run before any tailoring)

Before writing a tailored resume or cover letter, have the model **predict the rubric the screener will score against**, then write to that rubric. This runs in mode 1 (audit) to sharpen the verdict and in mode 3 (cover letter) as a required input.

**The prompt** (feed it the full JD text plus the current resume PDF contents):

> Based on this resume and this job description, produce the scorecard a screener would most likely generate, across four attributes: **details** (logistics -- location, work authorization, availability, comp band, start date), **qualifications** (credentials, degree, certs, years of experience), **skills** (tools, platforms, technical and process competencies), and **traits** (working style and soft skills the JD names or implies). For each attribute, list what the JD asks for, how the resume currently answers it, and a gap severity. Then flag every JD attribute as either **required/knockout** or **nice-to-have**, quoting the JD line that makes it one or the other.

Then: rewrite only what the scorecard says is weak, within the surgical tailoring rules in [[Claude Reference]]. Do not invent experience to fill a gap; an honest gap goes in `## Gaps` on the listing note.

**What the output feeds:**
- **Knockouts drive the verdict.** A missing required/knockout attribute is a predicted auto-reject -- say so in the fit report and recommend skip or a targeted warm-intro path instead of a cold application. This is the cheapest possible filter and it runs before any package work.
- **Nice-to-haves drive tailoring priority.** They tell you which of Alex's real experience to surface first, and in what order.
- **The skills column populates `## ATS keywords`** on the listing note -- ordered by scorecard weight, not as a flat list.
- **The traits column is prose guidance, never resume content.** Alex's resume has no place to assert traits, and stuffing trait language produces exactly the generic prose that fails the human 20-second read. Demonstrate a trait through a concrete accomplishment bullet or don't address it.

**Provenance and limits -- state these if the method ever comes up:**
- The four categories are a **heuristic frame**, not a leaked artifact. They came from a 2026-08 social-media video (Beverly Dines) claiming to have obtained a real rubric from "one of the largest ATSs in the world." That claim is **unsourced and unverified** -- do not repeat it as fact anywhere, and do not let a downstream agent treat the categories as ground truth about any specific vendor. The frame earns its place because every JD really does separate required from optional, not because the provenance checks out.
- The same video also cited a "May 2026 study of 197,000 resumes" showing white-text keyword injection manipulates early-stage filtering. **Treat as zero evidence** -- no author, no venue, malformed statistic, and it contradicts the claim made 30 seconds earlier in the same video that no data supports injection working.
- **The video's fallback advice -- white-text keyword stuffing -- is explicitly rejected here.** PDF parsing strips color, so the screener sees hidden text in plain sight; it is detected, penalized, and prevalent enough (~1-10% per Greenhouse/ManpowerGroup) that recruiters look for it. Same verdict as prompt injection: own-goal. See [[ATS & AI-Screening Playbook]].
- This is a **content** lever only. It does nothing for document parseability, which is the #1 actual auto-fail cause. The builder owns that half and neither substitutes for the other.

## Contact Research (MANDATORY for every qualifying JD)

For **every** posting that clears the 4 hard gates (not just Strong Fits), research the people around the role and record them on the listing note. This is required at audit time, in scan mode, in the apply pipeline, and in the daily-briefing scan -- any time a listing note is created or promoted. Read `/linkedin` first (READ-ONLY, human-paced; never send or connect). For each qualifying JD, identify and capture:

1. **Recruiter(s) / Talent Acquisition** -- esp. anyone covering IT/security/technical reqs. `get_company_employees` filtered by ("recruiter" OR "talent").
2. **Hiring manager (and the chain above)** -- IT/Security Manager, IT Director, Information Security Manager, CISO, or whoever the role reports into. At smaller orgs security often rolls up under IT Infrastructure/Operations -- note that.
3. **Same-role employees** -- current people holding the same/similar title (signals team size and whether the seat is net-new).
4. **Likely teammates** -- others on the IT/Security/Infrastructure team Alex would work alongside.

Method: `search_companies` to confirm the company URN (disambiguate look-alikes), then `get_company_employees` across a few title-keyword passes, then `get_person_profile` to enrich the top ~3-5. Cross-reference every name against Alex's People/ notes (`Areas/Relationships & Community/People/`) and CRM for warm-intro paths. Record findings in the listing note: fill `contact` / `contact_url` frontmatter with the single highest-impact target, and list the rest under `## Highest-impact contact` (rename to "## People around this role" when there are several) with **Name | Title | LinkedIn | why-relevant**. For Strong-Fit roles (esp. high comp + remote), continue to mode 1 step 6 (draft outreach + `/crm potential` tasks). For weaker-but-qualifying roles, capturing the contacts on the note is enough -- no outreach task required unless Alex asks.

If the LinkedIn MCP is unavailable, note "contact research pending (LinkedIn MCP unavailable)" on the listing and fall back to the company careers page / company LinkedIn.

## AI Safety Fellowship Lane (gate variant)

Alex's standing instruction (2026-07-25): **paid AI safety fellowships are in the pipeline regardless of location.** They run on a modified gate set because the standard four gates would kill essentially all of them -- fellowships are fixed-term by design (gate 2) and most are in-person in the Bay Area, DC, or London (gate 1). Dropping the lane on those grounds is the failure mode this section exists to prevent. Canonical gate text lives in the gitignored `Projects/Get new job/Claude Reference.md` § "Carve-out: paid AI safety fellowships"; read it at scan time.

**Scope**: paid fellowships, residencies, and visiting-researcher programs in AI safety, AI governance, or AI policy. Adjacent-but-in ("AI security", "emerging tech policy" with a real AI component) counts. Not in scope: unpaid programs, courses, grants/funding calls (80k tags those `Course` and `Funding` separately), and general-purpose policy fellowships with no AI angle.

**The four gates, fellowship variant:**

| # | Standard | Fellowship lane |
|---|---|---|
| 1 | Fully remote | **Any location, worldwide.** Remote, in-person, and relocation all qualify. The region/TZ-lock DQ does not apply here. |
| 2 | Full-time permanent | **Fixed-term is expected and fine** (3-24 months). Still must be full-time and a real cohort seat -- a staffing agency calling a 12-month W2 contract a "fellowship" is still a gate-2 fail. |
| 3 | At or above the standard floor | **Two floors: the standard floor if the fellowship is remote, the higher relocation floor if it requires moving.** Both values live in the gitignored Claude Reference.md -- read them there, don't inline them here. |
| 4 | ≥80% of responsibilities | Score against **stated eligibility and the selection bar**, not a responsibilities list. |

**Annualize before comparing.** Stipends are quoted every way imaginable; normalize to a yearly number first:
- weekly × 52 (Anthropic Fellows posts $3,850/wk → ~$200K/yr, clears both floors comfortably)
- hourly × 2,080 (10a Labs' Red Teaming Fellowship posts $25-32.50/hr → ~$52-68K/yr, under the standard floor, DQ)
- program-total ÷ program-months × 12 (AI Alignment Foundation's flat "$12,000 stipend" needs its duration read off the program page before it can be scored at all)

Show the arithmetic in the listing note's `verification_signals` so the number is auditable and not re-derived from scratch next pass.

**Cash only counts toward the floor.** Housing, travel, relocation reimbursement, visa support, and compute credits are genuine value but do not close a comp gap. List them under sweeteners.

**Ranges straddling the floor are a conditional pass, never a silent DQ.** Horizon Fellowship posts a wide band on a DC-metro relocation, and the applicable floor cuts through the middle of it -- the bottom misses, the top clears easily. Surface it, flag the band risk in the note, and confirm the actual placement level before building artifacts. (There is already an open Horizon fit-audit with an Aug 30 date -- check the existing listing note before creating a new one.)

**Gate 4 in practice.** A fellowship's purpose is to train people who don't yet do the work, so "80% of the responsibilities" is the wrong instrument -- it would DQ nearly every one of them, including ones Alex could win. Score the *eligibility criteria* instead, and DQ only on a stated bar he actually fails: PhD or postdoc required, published ML research required, JD/law degree required, current-federal-employee-only, citizenship or clearance he lacks. Read the resume PDF and the Claude Reference's AI-safety credential list at runtime for what he can claim rather than assuming. Directionally: governance, policy, ops, and AI-security fellowships fit; pure ML-alignment-research fellowships generally do not, and saying so is not pessimism.

**Work authorization.** International programs are in scope if they clear the relocation floor, but check sponsorship explicitly and flag it rather than assuming. 80k marks the ones that sponsor as `USA (Confirmed Visas)` / `UK (Confirmed Visas)` in `tags_location_80k`.

**Listing notes**: fellowships get the same per-listing note and Bases row as any other role, plus `role_type: fellowship`, `term_months`, and `relocation` in the frontmatter (see the schema below). They count toward the weekly application goal like any other application.

## Re-Apply on Repost (status-aware dedup)

Alex's standing instruction (2026-07-25): **a role he didn't get is not permanently dead.** Employers repost months later with a fresh req, a new hiring manager, or a changed candidate pool, and he wants those surfaced so he can re-apply. The old blanket rule ("skip any company+role already noted, regardless of status") silently buried exactly these, which is the worst kind of miss: a role already known to fit, thrown away without being shown.

**Dedup decision table** -- when a discovered role matches an existing listing note:

| Existing note `status` | Action |
|---|---|
| `candidate`, `applied`, `interviewing` | **Skip.** True duplicate of live activity. |
| `rejected`, `closed`, `withdrawn` | **Do NOT skip.** Check whether the new posting is genuinely fresh (different LinkedIn job ID, or `posted` date materially newer than the note's `date_added`). If fresh → surface as a **re-apply candidate**. If it's the same stale posting still lingering, skip quietly. |
| `skipped` (near-miss note) | **Skip unless materially changed.** Re-surface only if the fresh posting's stated requirements or comp differ from what the note's `## Why skipped` recorded (e.g. the years bar dropped, the band moved). Same req, same bar → skip without re-reading the JD; that's the note's whole job. |
| `reapply: true` on the note | **Always surface on any repost**, and check the employer's board directly each pass even absent a hit. Highest priority. |

**Marking a note for re-apply.** Add `reapply: true` to the frontmatter. Set it when the role cleared all 4 gates when found AND the loss was *not* due to a permanent disqualifier. Concretely:
- **Do mark**: lost to volume/competition ("300+ applicants"), went another direction, req closed or was pulled before decision, timing, or Alex reached interview stage and lost late. Interview-stage losses are the **strongest** re-apply case -- he's a known quantity there and got real traction.
- **Do NOT mark**: rejected against a bar that won't change (needs 5+ yrs GRC, needs a bachelor's, needs a clearance, named tool he lacks), or the role fails a gate today (comp under floor, hybrid, contract).

**Watchlist behavior.** Every discovery pass, in addition to passive dedup, actively check the careers boards of employers with `reapply: true` notes -- same as the warm-connection lane. A repost won't always reach LinkedIn or the alert emails.

**Respect stated re-interview cooldowns.** Some employers set one explicitly at rejection. Record it as `reinterview_cooldown_months` + `reinterview_eligible: YYYY-MM-DD` and do **not** re-apply before that date -- doing so burns a warm relationship. TRM Labs is the live example (rejected warm, 6-month cooldown, eligible 2026-12-23). Keep watching the board during the cooldown so the re-approach can be timed, but don't submit.

**Search `Archive/` too, not just the Job Listings folder.** Alex moves concluded roles to `Exobrain/Archive/<Company> - <Role>/`, which sits *outside* `Projects/Get new job/Job Listings/`. Any dedup or watchlist sweep that only looks in the Job Listings folder is blind to them -- that is exactly how TRM Labs (final-round, warm rejection, $105-115K) and Coefficient Giving IT Associate ($130.5-155.8K) went missing from the first watchlist pass. Sweep by frontmatter, not by folder:
```bash
grep -rl "^type: job-listing" /Users/alexhedtke/Exobrain/ | grep -v "/Job Listings/"
```
The `.base` filter was corrected on 2026-07-25 to drop its `file.inFolder(...)` clause and match on `type == "job-listing"` alone, so archived listings now appear in the tracker's All and Re-apply views. The Active view still excludes them by status, so nothing pollutes the working list.

**When surfacing a re-apply candidate**, do not overwrite the old note's history. Keep the original note (it holds the archived JD and the rejection record) and add a dated `## Repost <YYYY-MM-DD>` section with the new apply URL and job ID, flipping `status` back to `candidate` and clearing `applied`. Preserve `rejection_date` -- the prior outcome is context worth carrying into the new cover letter, not something to erase.

## Source Coverage Checklist (run before claiming a scan is "full")

A scan is **not** a full scan until every lane below has either run or been explicitly recorded as skipped-with-reason. Failure mode this exists to stop (recurred 2026-07-25): running 4 LinkedIn angles plus a couple of ATS X-rays, then labeling it a "full scan." That pass missed Indeed, Dice, Hiring.cafe, 80,000 Hours, the niche boards, and the Gmail alerts. The Gmail lane alone then produced ~12 names that appeared in none of the searches, so the gap was not marginal.

| # | Lane | Ran? | Notes |
|---|---|---|---|
| 1 | Gmail job alerts (`from:` linkedin/indeed/dice/ziprecruiter, `newer_than:4d`) | | **Distinct from the tracker Gmail search.** Confirmations/rejections are tracker maintenance; the *alert* emails are discovery. Running one does not cover the other. |
| 2 | LinkedIn MCP, 3-4 rotating angles | | Serial only, human-paced. |
| 3 | Greenhouse / Lever / Ashby X-ray | | One query per board. Do **not** `OR` two boards into a single query -- the engine drops one half silently. |
| 4 | Dice | | Discard the C2C/contract/body-shop glut. |
| 5 | Indeed | | Bot-hostile; verify on the employer ATS. |
| 6 | Hiring.cafe | | Follow through to the primary posting. |
| 7 | 80,000 Hours | | Algolia endpoint, see Source #7. |
| 8 | Niche boards via `nicheboards.py` (Himalayas API / Remotive API / WWR RSS / BuiltIn scrape) | | Direct data paths, NOT Google X-ray (superseded 2026-08-14). Survivors verify on the employer ATS; LEADS need a JD read for comp. RemoteRocketship stays browser-only; surface the URL and mark "Alex must spot-check." |
| 9 | Warm-connection lane (Claude Reference) | | Per-firm careers portals. |
| 10 | Re-apply watchlist (`reapply: true` notes) | | Largely absorbed by lane 12's automatic employer coverage, but still check for reposts on boards OUTSIDE the three polled ATSes (Workday, iCIMS, SuccessFactors, company-native pages). |
| 11 | AI safety fellowships: 80k `Fellowship` facet + AISafety.com/jobs + the **six hardcoded program sources** (GovAI, IAPS, Horizon, Talos, Airtable policy-fellowship base, RAND CAST) | | Location-agnostic, modified gates. Do NOT apply the remote filter or the permanent-role gate here. All six hardcoded sources run every pass. See "AI Safety Fellowship Lane". |
| 12 | ATS-direct watchlist via `ats-watchlist.py` | | Polls every tracked employer's Greenhouse/Lever/Ashby board and diffs. First run per board is a baseline; new postings still need JD read + gates + dedup. |
| 13 | USAJOBS via `usajobs.py` (remote pass + LOCAL KC pass) | | Keyed lane; if the key is missing the script says so and exits 0 -- report skipped-with-reason. Remote pass gates at the standard floor, local pass at the onsite floor. Federal deadlines are hard; flag anything closing inside 14 days. |
| 14 | Workday-direct via `workday.py` | | Polls every pinned + auto-discovered Workday tenant and diffs. Covers the ATS lane 11 can't see. Survivors arrive with comp gated and `canApply` verified, but still need dedup + a note. |

**Report the tally honestly**, including the skipped lanes. A scan that ran 4 of the lanes below is a partial scan; say so in the hub-note log and to Alex rather than labeling it full. Under-running is recoverable; a false "I checked everything" is not, because it silently retires leads.

**Two search-engine false negatives to distrust** (both cost a lane on 2026-07-25):
- A `site:` X-ray that returns results from a *different* domain than the one filtered means the filter failed. Treat as "lane did not run," not "lane is dry."
- WebSearch's prose summary is never evidence for a gate decision. Salary-aggregator pages (ZipRecruiter/Glassdoor medians) answering a specific-company query means the posting was not found. Open the real JD or leave the role unscored.

## Modes

### 1. Audit: `/job-search audit` (or paste a job posting)
When Alex shares a job posting URL or text, evaluate fit:

1. **Parse the posting** -- extract: title, company, location/remote, salary (if listed), required qualifications, preferred qualifications, key responsibilities, tech stack, and any red flags (unrealistic requirements, vague scope, etc.)

2. **Fit assessment** -- score against Alex's profile:
   - **Skills match**: Compare required/preferred qualifications against Alex's background (check resume if available, plus known priorities: Sec+, AZ-900, MD-102, AI governance, technical project work)
   - **Priority alignment**: Does this role align with Alex's current priorities and career direction?
   - **Growth potential**: Does it offer upskilling or advancement in areas Alex cares about?
   - **Red flags**: Unreasonable requirements, high turnover signals, MLM/scam indicators, "unicorn" postings (wanting 10 years experience for entry pay), mismatched seniority

3. **Verify the posting is still open** (stale leads waste Alex's time -- and 2026-05-08 showed they happen often):

   **CRITICAL -- these signals do NOT prove a listing is open:**
   - The careers page renders without error
   - The LinkedIn job ID is recent (43xxxxx+)
   - The role is cross-listed on aggregators (Built In, Himalayas, RemoteRocketship, Glassdoor, Indeed, ZipRecruiter, etc.)
   - The company has many other open jobs
   - The careers index lists the role
   - Recent "posted X days ago" labels on aggregator mirrors
   - **The full job description renders intact when Alex pastes it** (some ATS systems, notably UltiPro, render expired postings with the complete JD content and no visible expiry banner -- the expiry date is in metadata only). Discovered 2026-05-08 with Husch Blackwell: posting expired 2026-04-28 but the listing page still rendered the full JD ten days later, fooling both an automated agent and Alex's direct visual check.

   These all persisted on closed roles in 2026-05-08 verification (4 of 5 initially-promoted Tier 1 roles were actually closed on direct check, including one -- Husch Blackwell -- where Alex pasted the full JD believing it was open). The signals above prove the listing PAGE EXISTS, not that it ACCEPTS APPLICATIONS.

   **Always check explicit posting/expiry date metadata.** Look for:
   - "Posted on" / "Date posted" labels (anything >30 days old without a refresh signal is a yellow flag)
   - Explicit "expires on" or "deadline" labels
   - "Job is open for no less than N days" language (Netflix uses this -- strong positive signal of an active window)
   - For UltiPro specifically: there is often an expiry date buried in the URL parameters or metadata; if you can't find one and the role is older than 30 days, treat as suspect.

   **The ONLY definitive signal: load the apply flow and confirm a working submission form.**

   For each candidate role, agents must:
   - Click through to the apply URL (not the listing URL -- the application/submission URL).
   - Confirm the page returns a usable application form: input fields for name/email/resume upload, a working "Submit" button, no banner saying "no longer accepting applications" or "position filled" or "closed."
   - For ATS systems (Greenhouse, Lever, Ashby, Workday, iCIMS, Rippling), navigate the "Apply" button to the actual form and verify it loads.
   - If the apply button redirects to the careers homepage, an error page, a "thanks for your interest" page, or a 404, the role is closed.

   If the apply flow cannot be confirmed via WebFetch (JavaScript-heavy SPAs may not render server-side), explicitly flag the role as **"verification incomplete -- Alex must spot-check the apply form before any package work."** Do NOT promote the role into Tier 1-3 until Alex has confirmed.

   **Other useful signals (corroborating only, never sufficient on their own):**
   - Click through to the actual application form. If it 404s, redirects to a general page, or says "no longer accepting applications," it's dead.
   - LinkedIn job ID age (37xxxxx = 2023-2024; 41-42xxxxx = late 2025; 43xxxxx+ = 2026). Old IDs are a red flag.
   - Cross-reference headcount: if multiple people already hold the exact title, the role may be filled.
   - Posting date >60 days old without refresh indicators is a red flag.

   **Strongest positive verification path (use whenever possible):**
   - Greenhouse: hit the Boards API directly at `https://boards-api.greenhouse.io/v1/boards/<board>/jobs/<id>`. A 200 with content body = open. A 404 = closed. The user-facing `job-boards.greenhouse.io/<board>/jobs/<id>` URL silently redirects to the company index page when a posting is closed, which is misleading.
   - Lever: `api.lever.co/v0/postings/<board>` returns the live JSON list of open postings.
   - Workable: individual job pages are JS-rendered and only return metadata to WebFetch -- flag for Alex spot-check.
   - UltiPro: browser-blocks bot fetchers AND renders expired postings with full content. Always look for an explicit "posted" or "expires" date in the listing -- if absent and >30 days from posting, treat as suspect.

   **Reporting**: When agents return verified-open roles, the verification_signals frontmatter must include the apply-form check explicitly: e.g., "Apply form loaded successfully on Greenhouse 2026-05-08 with active Submit button." If the apply form check was not performed, the role is "verification incomplete" -- not "verified open."

3b. **Run the scorecard simulation** (see "JD Scorecard Simulation" above). Do this before writing the fit report, because the knockout flags decide the verdict: a required/knockout attribute Alex cannot answer is a predicted auto-reject, and the honest recommendation is skip-or-warm-intro rather than a cold application. Carry the skills column into `## ATS keywords` on the listing note.

4. **Output a fit report**:
   ```
   ## [Job Title] -- [Company]
   **Location**: [location] | **Salary**: [if listed]
   **Apply here**: [direct link to posting]
   **Status**: [Verified open / Possibly filled / Unable to verify]

   ### Fit Score: [Strong Fit / Moderate Fit / Weak Fit / Skip]

   **Knockouts**:
   - [Each required/knockout attribute from the scorecard, marked met or unmet. "None unmet" if clean.]

   **Matches**:
   - [Bullet each matching qualification with Alex's relevant experience]

   **Gaps**:
   - [Bullet each gap -- note if it's learnable vs. hard blocker, and whether the scorecard called it required or nice-to-have]

   **Red Flags**:
   - [Any concerns]

   **Verdict**: [1-2 sentence recommendation: apply, apply with caveats, or skip with reason. Any unmet knockout must be named here.]
   ```

5. If the verdict is "apply" or "apply with caveats," ask if Alex wants a cover letter and/or company research.

6. **Cold outreach trigger** (Strong Fit only, especially when compensation and remote opportunity are both good):
   - **LinkedIn people search** (via `linkedin` MCP -- read `/linkedin` for read-only rules and pacing): Find the hiring manager, team lead, or department head at the company. Use `get_company_employees` with the company LinkedIn URL and a keyword filter for titles like "IT Manager", "Hiring Manager", "IT Director", "CISO". Pull richer detail on individuals with `get_person_profile`. Draft any outreach as text for Alex to send manually -- never send through the MCP.
   - Cross-reference results against Alex's People/ notes and CRM for warm intro paths
   - Create Things 3 tasks for cold outreach via `/crm potential [name]` for each identified person, with context about the role and why reaching out matters
   - Include in the task notes: the role title, why it's a strong fit, LinkedIn profile URL, and a suggested outreach angle
   - This is highest priority when the role offers strong compensation AND remote/hybrid flexibility -- that combination warrants extra effort beyond just submitting an application

### 1b. Bulk Scan: `/job-search scan [list of companies]`
When Alex provides a list of companies to investigate for open positions:

1. **Search each company's careers page** and major job boards for IT/technology openings
2. **Filter for fit**: Only report roles that are a plausible match for Alex's skills and experience. Skip roles that are clearly out of scope (e.g., senior developer requiring 5+ years of Python, DBA requiring Oracle expertise, CISO-level roles requiring 15+ years management). Use the resume reference above as the baseline.
3. **Verify each posting is still open** (same rules as mode 1, step 3):
   - Check multiple sources -- firm's careers portal AND job board listings. Triangulate with at least 2 signals.
   - Cross-reference LinkedIn job ID age (37xxxxx = 2023-2024; 43xxxxx+ = 2026). Old IDs are a red flag.
   - Search for people already holding the title at that firm -- multiple holders suggests it's filled.
   - Click through to the application form to confirm it's live and accepting submissions.
   - Be skeptical of listings older than 60 days with no signs of refresh.
4. **Every reported role MUST include**:
   - Job title and company
   - Location (and remote/hybrid status)
   - Salary if listed (band rule: DQ only if the band's top is below the comp floor, whose value lives in the gitignored Claude Reference.md; flag band risk when the bottom is below the floor; omit if unlisted but note it)
   - A direct link to the posting -- preferably the firm's own careers portal, not just a job board mirror
   - A brief fit assessment (1-2 lines: why it matches, any notable gaps)
   - Verification method (e.g., "confirmed on firm portal 2026-04-01" or "LinkedIn ID 43xxxxx, posted March 2026")
5. **Do NOT report** roles that score "Weak Fit" or "Skip" -- only surface roles worth Alex's time (Strong or Moderate fit)
6. **Do NOT report** roles that cannot be verified as currently open -- list them in a brief "Stale/Filled" section at the end for awareness only
7. Group results by fit strength, with strongest matches first

### 2. Research: `/job-search research [company]`
Deep-dive on a company before applying:

1. **Company overview**: What they do, size, funding stage, recent news
2. **Culture signals**: Glassdoor themes, LinkedIn presence, tech blog, open-source contributions
3. **Key people** (via `linkedin` MCP -- see `/linkedin` for full conventions; read-only, paced like a human):
   - Search for hiring manager / team lead / department head: `get_company_employees` with the company LinkedIn URL and a keyword filter for titles like "IT Manager", "Hiring Manager", "IT Director", "CISO", "Security Manager".
   - For specific people by name: `search_people` with `firstName`/`lastName` and `currentCompany` set to the target company. Use `get_person_profile` to enrich a known profile URL.
   - Check Alex's People/ notes and CRM for any existing connections at the company
4. **Network angle**: Check if anyone in Alex's network works there or has connections (search People/ notes, CRM digest). Cross-reference LinkedIn MCP results against People/ notes for mutual connections. A warm intro is 10x more valuable than a cold app
5. **AI/tech stance**: For tech roles, note the company's position on AI, security, governance (relevant to Alex's interests)
6. **Interview intel**: Any publicly available interview process info (Glassdoor, Blind, etc.)

Output a briefing, then run `/verify` as a background agent to fact-check claims.

### 3. Cover Letter: `/job-search cover-letter`
Generate an ATS-compliant, tailored cover letter:

**ATS Compliance Rules** (apply to ALL cover letters):
- Plain text formatting -- no tables, columns, headers/footers, images, or special characters
- Standard section structure: contact info, date, greeting, body paragraphs, sign-off
- Use keywords and phrases directly from the job posting (ATS keyword matching)
- Spell out acronyms on first use, then abbreviate (e.g., "Application Tracking System (ATS)")
- Standard fonts implied (the content itself should not rely on formatting to convey meaning)
- No fancy bullet characters -- use standard dashes or asterisks if needed
- Keep to one page (~300-400 words)

**Tailoring Process**:
1. **Required input**: the scorecard from "JD Scorecard Simulation" above. If the audit already produced one, reuse it; if this mode is entered cold, run it first. Then extract the top 5-7 keywords/phrases from the posting, **ordered by scorecard weight** -- knockout attributes first, nice-to-haves after. Every knockout Alex genuinely meets must appear somewhere in the letter.
2. Map each to a concrete example from Alex's experience
3. Mirror the company's language and values (from research if available)
4. Structure:
   - **Opening**: Specific role + company name + why this role specifically (not generic)
   - **Body 1**: Strongest qualification match with a concrete achievement/example
   - **Body 2**: Secondary match + how Alex's unique background (AI governance, security upskilling, technical projects) adds value beyond the basic requirements
   - **Body 3** (optional): Culture/mission alignment if the company has clear values
   - **Closing**: Enthusiasm + availability + call to action
5. Run through `/de-ai` principles -- the letter must sound like a real human, not ChatGPT. No "I am writing to express my interest," no "I am excited to leverage my synergies," no corporate fluff. Alex's voice: direct, genuine, slightly informal, knowledgeable.

**Output**: The cover letter text, plus a list of ATS keywords embedded and where they appear. After Alex approves the text, generate the PDF via the builder (`build.py cover --md ... --company ... --tag ...` with `--out` pointed at the listing's folder `Job Listings/<Company> - <Role>/`, see "Resume + Cover Letter Generation" above) so it lands in that folder with clean metadata, NOT in `~/Downloads/`. Generate a tailored resume alongside it (`build.py resume --tailor ...`) whenever the role meaningfully benefits per [[Claude Reference]].

### 4. Tracker: `/job-search status`
Weekly application tracking via email confirmations:

1. Search Gmail for application confirmation emails from the past 7 days:
   ```
   gmail_search_messages with queries like:
   - "application received" OR "application confirmed" OR "thank you for applying"
   - "we received your application" OR "application submitted"
   - "your application for" OR "successfully applied"
   ```
2. Parse each confirmation for: company name, role title, date applied
3. Cross-reference against previous tracker entries to avoid double-counting
4. Present a weekly summary:
   ```
   ## Application Tracker -- Week of [date]
   **Total this week**: [N] / 10-20 goal
   **Status**: [On track / Behind / Ahead]

   | # | Company | Role | Date Applied | Source |
   |---|---------|------|-------------|--------|
   | 1 | [Co]    | [Role] | [Date]    | [Email subject] |
   ...

   **Pace check**: [If behind, calculate how many per remaining days to hit 10]
   ```
5. Append the summary to today's daily note under a `## Job Search` section
6. Append the same summary to the job hub note (`Projects/Get new job/Get new job.md`) under `## Job Search Log` as a dated `Applications` entry
7. If behind pace (fewer than ~1.5/day average to hit 10), flag it proactively

### 5. Full Pipeline: `/job-search apply [URL or pasted posting]`
Runs modes 1→2→3 in sequence:
1. Audit the posting for fit
2. If fit is "Strong" or "Moderate," automatically research the company
3. Generate a tailored cover letter
4. Surface any network connections at the company
5. Create a Things 3 task: "Apply to [Role] at [Company]" with the cover letter and research in the notes field. If routing to a project (e.g., "Job hunting"), verify the project has an Obsidian backlink in its notes field (`obsidian://open?vault=Exobrain&file=Projects/...`). If missing, add it via `update_project`.

## Per-Listing Notes & Bases Tracker (canonical)

**Folder**: `/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings/`
**Bases file**: `/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings.base`

Every researched, audited, or scanned job listing **MUST get a dedicated note** in the Job Listings folder. The `.base` file aggregates them into a checkable tracker. This is the canonical surface -- not the hub-note tables, which are dated snapshots that drift.

### When to create or update a listing note

- `/job-search audit`: create a note for every audited posting (any verdict -- Strong, Moderate, Weak, or Skip; status reflects the verdict)
- `/job-search scan`: create a note for every reported role (skip the dead/aggregator section)
- **Any discovery scan (daily or full): create a note for near-misses too** (ADDED 2026-08-10, trigger widened same day). **The trigger is "consumed a full JD read," not which gate killed it**: any role that cost a full JD read and then died on ANY gate gets a note with `status: skipped`, `declined: true`, and a `## Why skipped` section stating the exact failed bar (quote the JD line). Purpose: tomorrow's scan dedups against it instead of re-reading the same JD, and Alex can see what's being killed and overrule. (The first version only covered gate-3/4 deaths; the 2026-08-10 scan then paid full reads on two gate-1 fails, Axos and Centric, that would have come straight back through the alert emails.) Roles killed on the title pre-filter or before a JD read do NOT get notes -- only ones that consumed real evaluation.
- **Contradictory-requirements rule** (ADDED 2026-08-10, the Terumo pattern): when poster-side screening filters contradict the JD body's own stated requirements (e.g. LinkedIn screener demands 6+ years while the JD's Education and Experience section says 2-6), that is a **surface-with-flag, Alex's call** -- not a silent DQ. Create the note as `status: candidate` with the contradiction spelled out under `## Gaps`, and flag it in the scan report.
- `/job-search apply`: create a note as part of the pipeline; set `applied: true` + `application_date` when Alex confirms submission
- `/job-search research`: update the contact, posted date, verification status on the existing note (or create one if research preceded an audit)
- Alex says "I applied to X": set `applied: true`, `application_date: <today>`, `status: applied`

### Note location and naming

- Base folder: `Projects/Get new job/Job Listings/`
- **Plain listing (scanned/candidate, no artifacts, not applied)**: a flat note `Job Listings/<Company> - <Role>.md` (e.g., `Nerdio - Support Engineer.md`). If a company has multiple roles, list them as separate files. Strip illegal filename characters.
- **Active listing (we built ANY artifact for it, or applied)** -- folder convention (Alex 2026-06-24, broadened 2026-07-15): the moment we create *any* artifact for a listing -- tailored resume, cover letter, **interview prep doc**, company/interviewer **research**, notes, anything -- promote it to its own dedicated folder `Job Listings/<Company> - <Role>/` and put **everything** for that role inside: the note `<Company> - <Role>.md` PLUS every artifact (resume + cover letter PDFs, interview prep `.md`s, research `.md`s). Do NOT scatter interview prep or research loose in `Projects/Get new job/` or the Job Listings root. When promoting an existing flat note, move the `.md` into the new same-named folder. This keeps everything for one application in one place. (One folder per role; a separate declined/inactive role at the same company keeps its own flat note or folder.)
- The Bases tracker is unaffected by the flat-vs-folder split: its filter `file.inFolder("Projects/Get new job/Job Listings")` is **recursive** (matches subfolders), and the `file.ext == "md"` + `type == "job-listing"` clauses exclude the PDFs, so artifacts never pollute the table and foldered notes still aggregate. Wikilinks resolve by basename, so `[[<Company> - <Role>]]` keeps working after a note moves into its folder.

### Frontmatter schema (REQUIRED)

```yaml
---
type: job-listing
company: <string>
role: <string>
status: candidate          # candidate | applied | interviewing | rejected | offer | withdrawn | closed | skipped
applied: false             # boolean -- used as the .base checkbox
comp_min: 65000            # USD/yr; null if unlisted
comp_max: 80000            # USD/yr; null if unlisted
comp_listed: true
remote: true
location: "Remote US"
role_type: standard        # standard | fellowship -- fellowship triggers the modified gate set
term_months:               # fellowship only: program length in months; null for standard roles
relocation: false          # true if the seat requires moving; selects the higher relocation floor in the fellowship lane
apply_url: "https://..."
contact: "[Name], Sr Technical Recruiter"
contact_url: "https://linkedin.com/in/..."
verified: true             # boolean -- survived 2-signal verification
verification_signals: "Live on Rippling ATS; LinkedIn job ID 43xx; application form active"
date_added: 2026-05-08     # date this note first entered the tracker; stamp <today> at creation, NEVER edit after
posted: 2026-05-08         # date the listing was first surfaced or research was done
application_date:          # date Alex submitted; null until applied
rejection_date:            # date a rejection was received; null otherwise
last_research: 2026-05-08
source: rippling-ats       # short tag: greenhouse, lever, ashby, workday, icims, rippling, linkedin, indeed, etc.
---
```

Truthful nulls: omit `comp_min` / `comp_max` if unlisted (set `comp_listed: false`); leave `application_date` blank until Alex submits. For fellowships, record `comp_min` / `comp_max` as the **annualized** figures (show the arithmetic in `verification_signals`) so the Bases comp sort stays comparable across lanes.

**Always stamp `date_added: <today>` when creating a new listing note** (whether from a scan, an apply, or an "I applied to X" mention). It records when the listing entered the tracker and is write-once: never change it on later edits or when a flat note is promoted to its own folder. (Historical notes were backfilled from earliest known engagement date since the vault has no git history.)

### Note body (concise, Alex-readable)

```markdown
# <Company> -- <Role>

**Apply**: [<URL>](<URL>)

## Snapshot
- **Comp**: <range or "unlisted">
- **Location**: <details, remote/hybrid posture>
- **Status**: <verified-open / possibly stale / etc.>
- **Verified via**: <signals>

## Why this fits
- <2-4 bullets mapping JD requirements to Alex's experience>

## Gaps
- <2-3 bullets -- concede honestly, note learnable vs hard blocker>

## Highest-impact contact
**<Name>**, <Title> -- [<LinkedIn>](<URL>)
<1-2 sentence outreach angle>

## ATS keywords
<comma-separated list of the top JD keywords this role hits, ordered by scorecard weight -- knockout attributes first, then nice-to-haves. Mark unmet knockouts with (UNMET).>

## Notes
<freeform -- interview prep, follow-up reminders, cold-outreach status, etc.>

> [!info]- Raw JD (archived verbatim)
> <source URL + archive date>
>
> <the FULL job description text, copied verbatim, every line prefixed with `> `>
```

**Always archive the full raw JD inline.** Postings get pulled, ATS pages 404, and recruiter screens happen weeks after the listing disappears (Nerdio 2026-06-02: original Rippling page was down by interview day; had to recover the JD from a Built In mirror). At create/audit time, copy the complete posting text verbatim into a **collapsible callout** (`> [!info]- Raw JD (archived verbatim)`) at the bottom of the listing note -- intro/about, all responsibilities, required + preferred qualifications, comp, benefits. The `-` after the callout type makes it collapsed by default so it doesn't clutter the note. Do not summarize or trim; the "Why this fits" / "Gaps" bullets are the summary, this callout is the source of truth. Lead the callout with the source URL and archive date. Keep it **inline in the listing note** -- do not split it into a sibling file.

### Bases file conventions

The `.base` lives at `Projects/Get new job/Job Listings.base` (sibling of the folder, not inside). It must filter on `file.inFolder("Projects/Get new job/Job Listings")` and `type == "job-listing"`. Standard views to include:

- **Active**: `applied == false AND declined != true AND status not in (closed, withdrawn, rejected, skipped)`, sorted by comp DESC
- **Applied**: `applied == true`, sorted by `application_date` DESC
- **All**: ungrouped, all listings, sorted by file.name ASC

The `applied` boolean is the inline checkbox in the Bases table view -- flipping it updates the note's `applied` frontmatter property in place. Obsidian Bases is a view layer with no property-trigger automation, so flipping the checkbox does NOT directly cascade to other fields. The cascade is handled by a launchd file watcher in the Exobrain harness:

- **Watcher**: `com.exobrain.job-listings-sync` (plist at `~/Library/LaunchAgents/`)
- **Script**: `Exobrain harness/job-listings-sync/reconcile.py`
- **Trigger**: file changes in `Projects/Get new job/Job Listings/` + 5-minute periodic safety net
- **Logic**:
  - `applied=true` AND `status=candidate` (the "checkbox just flipped" case) → set `status=applied` and stamp `application_date=<today>` if empty
  - `status=rejected` AND no `rejection_date` → stamp `rejection_date=<today>`
  - All other states are left alone (avoids back-stamping migrated records or interviewing-stage roles with today's date)

When Alex says "I applied to X" in conversation, Claude can update the frontmatter directly with the same logic. The watcher will then no-op since the state is already correct (the script is idempotent).

For interviewing/offer/withdrawn transitions, Alex updates `status` manually -- the watcher does not infer those state changes.

## Job Hub Note -- "Get new job"

**Path**: `/Users/alexhedtke/Exobrain/Projects/Get new job/Get new job.md`

This note is the one-stop dashboard for all job hunting activity. **Every job-search action must append a log entry to this note** (after the existing Things 3 data / Notes section). Don't touch the existing task sections -- only append below them.

**Relationship to per-listing notes**: the hub note holds dated narrative log entries (research dives, cover letter text, networking touches). The Job Listings folder + `.base` file holds the live, queryable, checkable tracker. Both are canonical for different purposes -- keep them in sync but don't duplicate. Hub-note tables are snapshots; the `.base` is the live source.

### What to log (append under a `## Job Search Log` section, most recent first):

- **Application tracker** (`/job-search status`): Append the weekly summary table with counts and pace check
- **Audits** (`/job-search audit`): Append a compact entry -- role, company, fit score, verdict, link to posting
- **Cover letters** (`/job-search cover-letter`): Append the full cover letter text under a dated sub-heading with the role/company
- **Company research** (`/job-search research`): Append key findings -- company overview, culture signals, network angles, interview intel
- **Full pipeline** (`/job-search apply`): Append the complete pipeline output (audit + research + cover letter) as one dated entry
- **Upskilling milestones**: When cert study sessions are completed, exams passed, or training attended, log it (e.g., "Completed AZ-900 Virtual Training Day Part 2")
- **Interview activity**: Any interview scheduling, prep, or outcomes
- **Networking for job search**: Cold outreach sent, warm intros made, informational interviews conducted

### Log entry format:
```markdown
### [YYYY-MM-DD] [Type]: [Brief description]
[Content -- tables, summaries, cover letters, etc.]
```

Types: `Applications`, `Audit`, `Cover Letter`, `Research`, `Pipeline`, `Upskilling`, `Interview`, `Networking`

## Integration with Other Skills

- **`/daily-briefing`**: Include application count for the current week and pace check. Log daily app count to the job hub note.
- **`/weekly-review`**: Full application tracker summary, trends, and suggestions for next week's targets. Append the weekly job search summary to the job hub note.
- **`/crm`**: Cross-reference company employees with Alex's network for warm intros. For Strong Fit roles (especially high comp + remote), auto-create `/crm potential` tasks for cold outreach to relevant people at the company
- **`/linkedin`**: Canonical reference for the LinkedIn MCP. READ-ONLY -- discovery and lookup only, never send messages or connection requests. Used as one source of job listings (`search_jobs`, `get_job_details`) and for hiring-contact identification (`get_company_employees`)
- Ad-hoc questions like "how's my job search going?" can be answered via tracker mode
- **`/verify`**: Background fact-check on company research claims
- **`/de-ai`**: Applied to all cover letter output to ensure human voice
- **`/evening-winddown`**: Include daily application count in the recap

## Daily Briefing

When called as part of the daily briefing (every day, weekends included):

1. **Tracker maintenance**: The canonical tracker is the `Job Listings` Bases file at `/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings.base` plus the per-listing notes in `Projects/Get new job/Job Listings/`. Search Gmail for new application confirmations and rejection emails since the last entry. For each new confirmation: if a listing note already exists for that company+role, set `applied: true`, `status: applied`, and `application_date: <today>`. If no note exists, create one per the schema in the "Per-Listing Notes & Bases Tracker" section above. For rejections: set `status: rejected` and `rejection_date: <date>`.

2. **Google/WebSearch discovery scan** (added 2026-05-19; NARROWED 2026-08-14 -- the niche boards moved to their direct data paths in `nicheboards.py`, so never X-ray Himalayas/BuiltIn/WWR/Remotive anymore):
   - Rotate 1-2 Google X-ray searches per day across the ATS boards only. Suggested rotation (alternate which to skip):
     - `site:boards.greenhouse.io "<responsibility phrase>" remote` -- pick a different responsibility phrase each day (Entra ID, phishing remediation, access provisioning, M365 admin, compromised account, Intune endpoint, etc.)
     - `site:jobs.lever.co "<responsibility phrase>" remote`
     - `site:jobs.ashbyhq.com "<keyword>" remote`
   - The X-ray's remaining job is discovering employers NOT yet in the tracker; once a company gets a listing note, `ats-watchlist.py` polls its whole board daily and the X-ray adds nothing for it.
   - Vary which responsibility phrase you search each day (see "Responsibility-keyword search" in Sources section). Rotating across days makes the activity pattern look like a human exploring rather than a script.
   - For each promising search result: open with `/defuddle` or WebFetch to read the JD directly (no need for separate "verify the title" step -- the page IS the JD).
   - **Staleness check**: Google's index lags real-time. Lever (`jobs.lever.co/*`) silently returns 404 when a listing is removed. If `defuddle` returns empty content or `WebFetch` returns 403, fall back to `curl -sL -A "<browser UA>"` to confirm -- many JS-rendered pages need a real UA, but a 404 page means the listing is dead. Discard 404s.
   - **Cloudflare-protected aggregators**: RemoteRocketship and a few others 1010-block curl with a Cloudflare challenge. Those are not blockers for Alex (he can open them in a browser), so still surface the URL -- just note "verification incomplete, Alex must spot-check JD" in the listing note.
   - Apply the 4-gate hard requirements (remote / FT permanent / comp band reaching the floor per the band rule (value lives in the gitignored Claude Reference.md) or strong inference / ≥80% strong fit). **Exception**: if the hit is a paid AI safety fellowship, switch to the fellowship gate variant instead of DQ'ing it -- see "AI Safety Fellowship Lane".
   - Dedupe against `Projects/Get new job/Job Listings/` folder.
   - Create per-listing notes for survivors with `source: greenhouse` / `source: lever` / `source: company-portal` / etc. as appropriate.

2b. **Dice / Indeed / Hiring.cafe scan** (ADDED 2026-07-22 -- see Source #8 above for URLs, query syntax, and per-board gotchas):
   - Hit all three each pass. Rotate the keyword angle day-to-day like the other lanes (title + responsibility phrases).
   - **Dice**: full-time + remote + last-7-days filter; discard the C2C/contract/body-shop glut hard (Gate 2 + smell test).
   - **Indeed**: bot-hostile -- surface URLs via `WebSearch site:indeed.com`, then verify on the employer's own ATS/careers page; mark "verification incomplete" if only the Indeed mirror exists.
   - **Hiring.cafe**: use its structured filters (Remote + US + min salary at the comp floor + full-time + recent); follow through to the primary posting and verify there.
   - Same 4-gate filter + dedup against the Job Listings folder. Create per-listing notes for survivors with `source: dice` / `source: indeed` / `source: hiringcafe` (or the underlying employer-ATS tag if the aggregator resolves to one).

2b2. **Niche boards + ATS watchlist + USAJOBS scripted lanes** (ADDED 2026-08-14 -- see Sources #10-12 for the per-board gotchas):
   - `python3 "Exobrain harness/job-search/nicheboards.py" "<angle1>" "<angle2>" --days 3` -- rotate angles like the other lanes. Survivors: verify on the employer ATS, then the normal note pipeline. Leads (comp unlisted): spend a JD read only when the title is squarely in-lane; the unlisted-comp DQ still applies after the read.
   - `python3 "Exobrain harness/job-search/ats-watchlist.py"` -- new postings since yesterday's snapshot across every tracked employer's Greenhouse/Lever/Ashby board. Each new posting: JD read, 4 gates, status-aware dedup, note. Report polled/failed/baselined counts honestly in the hub log.
   - `python3 "Exobrain harness/job-search/usajobs.py" "IT specialist" "security analyst" --days 7` -- skips itself with instructions if the API key is absent; log the lane as skipped-with-reason in that case.
   - `python3 "Exobrain harness/job-search/workday.py"` (see Source #13) -- new postings across every pinned + auto-discovered Workday tenant. Survivors come pre-gated on all four gates with `canApply` verified and the JD already fetched, so they go straight to status-aware dedup and a note; LEADS have no comp in the JD and need the usual judgment call. Report polled/failed/baselined counts honestly. To pin a new board Alex hands over, `--add "<board URL with its filters>"` and read back the resolved facet labels before trusting it.

2c. **AI safety fellowship scan** (ADDED 2026-07-25 -- see Source #9 and "AI Safety Fellowship Lane" for the gate variant):
   - One 80k Algolia call on `facetFilters: [["tags_role_type:Fellowship"]]` with **no** location filter, plus a pass over AISafety.com/jobs (including its "Events & training" section).
   - **Hit all six hardcoded program sources every pass** (GovAI, IAPS, Horizon, Talos, the Airtable policy-fellowship base, RAND CAST -- table in Source #9). Rotate 2-3 of the secondary program pages on top of that; don't run all of them daily.
   - Apply the **fellowship gates**, not the standard four: any location; fixed-term OK; annualized comp at or above the standard floor if remote, at or above the relocation floor if it requires moving (both in the gitignored Claude Reference.md); eligibility-based fit. Annualize the stipend before scoring and record the arithmetic.
   - Dedup against the Job Listings folder and `Archive/` like any other lane. Create per-listing notes for survivors with `role_type: fellowship`, `term_months`, `relocation`, and `source: 80000hours` / `aisafety-com` / `program-page`.
   - **Deadlines matter more here than in the open market.** Fellowships run on cohort cycles with hard application windows, so capture `closes_at` (80k returns it) or the program page's stated deadline in the note and flag anything closing inside 14 days to Alex the same morning.

3. **LinkedIn discovery scan** (verified workflow -- never skip the JD read or the comp DQ check):
   - Read `/linkedin` first for read-only rules, pacing, and the `references[]` mapping gotcha.
   - Run 3-4 `mcp__linkedin__search_jobs` calls across rotating angles to vary the daily activity pattern. Suggested rotation (pick 3-4 each day, alternate which to skip):
     - `IT analyst` / `IT operations`
     - `identity access management` / `IAM analyst`
     - `security analyst` / `cybersecurity analyst`
     - `GRC compliance analyst` / `information security GRC`
     - `IT auditor` / `compliance auditor`
     - **`Cybersecurity Analyst I` / `Security Analyst I` / `Associate Cybersecurity Analyst` / `Junior Security Analyst`** (Alex standing instruction 2026-07-25 -- explicitly include the numbered/entry-level variants). These are his target band and the plain-keyword searches miss them: "cybersecurity analyst" alone ranks Senior/Principal/Engineer titles above the `I` roles, so the entry tier never surfaces. Pair with `experience_level=entry,associate`. Note this cuts the other way from the title pre-filter: **`I` and `Associate` titles are KEEPS, not drops** -- only `II` needs the JD experience-cap check.
   - Filters: `work_type=remote`, `job_type=full_time`, `date_posted=past_24_hours` (so we don't re-scan yesterday's pool), `sort_by=date`.
   - **Use ONLY job_id→title mappings from each response's `references[]` block.** Discard any job_ids from `job_ids[]` not present in `references[]` -- positional alignment is unreliable. (See [[feedback-linkedin-search-job-id-mapping]].)
   - **Title pre-filter** (before any JD read -- saves MCP budget on guaranteed-decline candidates per [[feedback-entry-level-target]]):
     - Drop titles containing: Senior, Sr., Sr, Lead, Principal, Staff, Manager, Director, Head of, Architect, Engineer III/IV/V
     - Drop obvious specialist mismatches: Epic, Cerner, Workday HRIS, Oracle ERP, SAP, Salesforce admin, Dynamics 365, Mainframe, Geospatial/GIS, AI/ML Engineer, EE/ME engineering, sourcing/procurement (Ariba/Coupa/Jaggaer), Tier I (too junior in tools Alex doesn't have)
     - Drop obvious sales/CSM: Account Executive, Customer Success, Solutions Engineer (pre-sales), Sales Engineer, Sales Development Rep
     - Keep: plain Analyst/Administrator/Specialist, Junior/Associate, "I"/"II" (with JD-verify experience cap, see below)
     - For "II" titles: if JD requires ≥6 years specialty tenure, treat as stretch and skip.
   - Dedupe candidates against the existing `Projects/Get new job/Job Listings/` folder (filename `<Company> - <Role>.md`) -- **status-aware, NOT blanket-skip. See "Re-Apply on Repost" below.**
   - For each fresh candidate from references[]:
     a. Call `mcp__linkedin__get_job_details` -- **read the actual JD before any fit label**. No title-only audits.
     b. Apply the 4-gate hard requirements (`feedback-job-hard-requirements`) -- or, if the posting is a paid AI safety fellowship, the fellowship variant in "AI Safety Fellowship Lane":
        - Fully remote (JD says remote, not just LinkedIn label -- Cyderes 2026-05-19 was hybrid despite "Remote" label)
        - Full-time permanent (not contract, contract-to-hire, 1099, temp)
        - **Comp band reaches the floor** (band rule, Alex 2026-08-10: a listed range passes if the floor falls anywhere within it -- DQ only when the band's top is below the floor; a bottom under the floor is a pass-with-flag. The floor's value lives in the gitignored Claude Reference.md), OR brief market-data check (Glassdoor/Salary.com/ZipRecruiter median for that title) shows strong evidence the role's band reaches the floor -- *if unlisted and you can't reach high confidence in <2 min of research, DQ*
        - Strong fit ≥80% (no failed JD hard reqs -- degree, years, named tools, clearance, bilingual -- AND ≥80% of top responsibilities/qualifications match Alex's resume)
     c. Create a per-listing note **only** if all 4 gates pass. Use the schema in "Per-Listing Notes & Bases Tracker" above. Set `verified: true` and record the comp-evidence inference (if applicable) in `verification_signals`.
   - Pacing: no numerical cap, but follow `/linkedin` qualitative rules -- batch JD reads in small groups (2-4 per turn) with reasoning between, vary keyword angles day-to-day, no tight loops. The natural ceiling is "I've exhausted reasonable search angles," not an arbitrary count.
   - Target volume: 2-5 new verified candidates per day → hits the 10-20 weekly app goal.

4. **Contact research + cold outreach surfacing**: For **every** new verified candidate, run the mandatory Contact Research (see "Contact Research" section above) -- recruiter(s), hiring manager(s), same-role employees, likely teammates -- and record them on the listing note. Then, for candidates scoring Strong Fit (especially high comp + remote), follow mode 1 step 6: draft outreach and create `/crm potential <name>` Things 3 tasks for the top 1-2 targets. Cap outreach-task creation at the top 1-2 candidates per day to keep MCP pacing reasonable; the contact *capture* on the note applies to all qualifying candidates.

5. **Weekly pace check**: Count apps submitted since Monday vs 10-20 goal. If behind mid-week, suggest time blocks from calendar gaps.

6. **Upcoming interviews**: Surface any job-related events from today's calendar.

7. **Return for briefing** (per `feedback-briefing-compact` -- jobs/contacts go to Things 3, not the briefing body):
   - Under `#### New tasks created`: any Things 3 tasks created during this run (cold outreach, advance-to-package, etc.) with `things:///show?id=ID` deep links.
   - Under `#### Flags`: only mention job-search items if exceptional -- behind pace mid-week, interview today, or a stand-out Strong Fit posting that warrants same-day action. The candidate count goes here ("3 new verified candidates added to tracker -- see Bases for triage") not the candidate list itself.
   - Append a `## Job Search Log` entry to the hub note (`Projects/Get new job/Get new job.md`) summarizing: scan counts (titles searched / JD-verified / passed all gates), new candidate names with apply URLs, declined names with one-line reason. Be honest about counts -- don't pad the survivor list.

## Proactive Behaviors

- During `/daily-briefing`, if it's midweek and Alex is behind on applications, flag it with suggested time blocks from calendar gaps
- When processing transcripts that mention job leads, companies, or networking contacts relevant to job search, surface them
- If Alex hasn't submitted any applications in 3+ days, mention it constructively in ad-hoc interactions
- Track which types of roles Alex applies to most -- surface patterns that might help narrow or broaden the search
