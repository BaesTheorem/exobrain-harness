# job-search automation

Daily unattended discovery scan for the `/job-search` skill.

- **`run-job-scan.sh`** -- launchd wrapper. Runs `claude --print` headless with the daily
  discovery prompt across every lane that works unattended: Gmail job alerts (if the
  claude.ai connector is reachable), `hiringcafe.py` + `indeed.py` + `nicheboards.py` +
  `ats-watchlist.py` + `workday.py` + `usajobs.py` + `talify.py` scripted lanes,
  Greenhouse/Lever X-ray (Ashby/Workable dropped 2026-08-10 -- chronic wrong-domain false
  negatives, and hiring.cafe covers those ATS inventories), 80,000 Hours Algolia, LinkedIn
  (if the MCP is reachable), and the warm-connection + re-apply watchlists. Applies the 4
  hard gates (comp gate = band rule: a listed range passes if the floor falls inside it),
  verifies postings open, dedups STATUS-AWARE against
  `~/Exobrain/Projects/Get new job/Job Listings/` and `Archive/`, writes per-listing notes
  for survivors AND near-misses (`status: skipped`, so tomorrow doesn't re-read the same
  JD), appends a hub-note log entry, and fires a `mist-notify` ONLY when new verified
  candidates are added (silent on zero-survivor days). Inline scan (no parallel subagents)
  to keep daily token cost low. 40-min timeout guard per attempt, **one automatic retry**
  on failure (added 2026-08-10: half the 7/21-8/10 runs died on "Connection closed
  mid-response" with no retry and no visible trace), and a clickable `mist-notify` failure
  banner pointing at the failed attempt's log.
- **`nicheboards.py`** (added 2026-08-14) -- niche-board lane through the boards' own data
  paths instead of Google X-ray (whose lagged index + silent wrong-domain results kept the
  lane looking dry). Himalayas public JSON API (search param ignored, `limit` silently
  capped at 20 -- both handled), Remotive API, WeWorkRemotely RSS (no salary in feed, so
  its hits surface as LEADS, never survivors), BuiltIn server-rendered scrape. Applies the
  gates on structured fields; prints survivors / leads / declines.
- **`ats-watchlist.py`** (added 2026-08-14) -- polls the full live posting list of every
  employer that has ever gotten a `type: job-listing` note (tracker + Archive), straight
  from the Greenhouse/Lever/Ashby public APIs, and diffs against the previous snapshot.
  Zero index lag; covers postings that never crosspost. First poll per board is a baseline.
  State (snapshot + employer list) is gitignored under `state/` -- it reveals where Alex
  applies. Pin extra boards in `state/watchlist-extra.json`.
- **`workday.py`** (added 2026-08-26) -- the Workday half of the ATS-direct lane. `ats-watchlist.py`
  covers Greenhouse/Lever/Ashby; a large share of mid-market and enterprise employers host on
  Workday instead, and those postings often never crosspost. Polls each tenant's unauthenticated
  CXS endpoint (`/wday/cxs/<tenant>/<site>/jobs`), diffs against the last snapshot, then fetches
  each in-lane posting's detail page -- which carries the comp band in the JD, the real start
  date, the full JD text for the note's archive callout, and `canApply`/`posted`, the ATS's own
  answer to "still accepting applications" (the apply-flow signal the skill demands, not the
  weaker "listing page renders"). So survivors arrive gated on all four gates and already
  verified. Board list self-builds from `type: job-listing` notes (tracker + `Archive/`), same as
  `ats-watchlist.py`; pin a specific filtered board with
  `--add "<board URL>" --why "..."`. **A board URL's query params are gates 1 and 2 applied
  server-side**, so pinning a hand-filtered board is one command. Facet IDs are opaque per-tenant
  GUIDs and never portable between employers -- `--add` prints each one's resolved human label and
  open count as the positive control. Two gate bugs caught on the first live run and fixed:
  gating remote on the literal word "remote" silently killed a whole employer's inventory (Cigna
  posts remote reqs as "United States Work at Home"), and the location field contradicts the title
  often enough that a hybrid/onsite marker in either field now decides gate 1 (CrowdStrike lists
  "Analyst I ... (Hybrid, St Louis)" under location "USA - Remote").
  Boards for warm-connection employers are pinned with `--warm`: their rows carry a WARM REFERRAL tag
  in every bucket, and their off-lane titles are listed instead of dropped, since a referral is worth
  more than a title match. It grants no gate exception on its own.
- **`talify.py`** (added 2026-08-26) -- Missouri's state talent board at missouri.talify.com
  (the jobs.mo.gov front-end; apply flows route through app.jobs.mo.gov). Rails/Turbo but
  server-rendered: `/jobs.json` returns `{"html": <20 cards>, "next_page": N}` and takes
  Ransack params. Two passes: remote at the standard floor (expected-dry -- the whole board
  held one remote job at build time) and KC-metro local at the onsite floor, which is the
  lane's actual value. The comp threshold normalizes across pay types (hourly/monthly/annual
  encodings of one floor return the identical set), but `compensation_max_gteq` is silently
  ignored -- not Ransack-whitelisted, it returns the unfiltered board, first spotted when a
  Food Service Worker "cleared" a $103K filter -- so the band rule runs client-side: server
  pre-filter at a reduced min, then gate each detail page's band top at the real floor.
  Detail pages are HTML-only (`.json` answers 406). Off-lane KC titles that cleared the comp
  pre-filter are printed for overrule rather than silently dropped.
- **`usajobs.py`** (added 2026-08-14) -- official federal API, remote-only public-hiring-path
  search with mechanical comp gating. Needs `USAJOBS_API_KEY` + `USAJOBS_EMAIL` in the
  harness `.env` (free key: https://developer.usajobs.gov/apirequest/); without them it
  prints instructions and exits 0 so the headless scan logs the lane as skipped, not failed.
- **`com.exobrain.job-scan.plist`** -- source copy of the launchd job. Runs daily at 09:00
  (deliberately staggered after the other morning jobs).
  The live copy is a **real file** at `~/Library/LaunchAgents/com.exobrain.job-scan.plist`
  (never a symlink -- see `feedback_launchd_symlinks`).

## Install / reload
```bash
cp com.exobrain.job-scan.plist ~/Library/LaunchAgents/
launchctl bootout  "gui/$(id -u)/com.exobrain.job-scan" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.exobrain.job-scan.plist
```

## Change the time
Edit `StartCalendarInterval` (Hour/Minute) in both the repo copy and the LaunchAgents copy,
then reload as above.

## Logs
- `~/Library/Logs/exobrain/job-scan.log` / `.err` -- launchd stdout/stderr
- `~/Library/Logs/exobrain/job-scan-<timestamp>.out/.err` -- per-run Claude output
- `~/Library/Logs/exobrain/job-scan-failures.log` -- timeouts and non-zero exits

## Caveat: interactively-authenticated MCPs in headless runs
The LinkedIn MCP and the claude.ai Gmail connector are interactively authenticated and may
be absent in a launchd run. The scan degrades gracefully to the lanes that always work
(scripted hiring.cafe/Indeed, Google X-ray, 80k Hours) and notes in the hub-note log which
lanes actually ran.

### Lane backfill flags (LinkedIn + Gmail)
When a headless run can't reach one of those MCPs, it raises a flag so the next *interactive*
session backfills that lane before anything else:

- The headless run prints `GMAIL_LANE: RAN|SKIPPED` then `LINKEDIN_LANE: RAN|SKIPPED` as its
  last two lines.
- `run-job-scan.sh` parses the markers and owns the sentinels
  `job-search/.linkedin-scan-pending` and `job-search/.gmail-scan-pending` (gitignored,
  transient): `SKIPPED` stamps today's date into the file, `RAN` clears it, a missing marker
  (timeout/crash) leaves it untouched.
- `.claude/hooks/session-start.sh` checks for each sentinel and, if present, prints a loud
  "ACTION FIRST" banner at the very top of the session telling it to run that lane, then
  `rm` the flag. A later successful scan (headless or interactive) also clears it.

So a missed lane is self-healing: either the next day's headless run reaches it, or the next
interactive session is told to fill the gap manually. The Gmail lane matters most -- alert
emails decay in ~3 days and it has historically been the highest-yield discovery lane.
