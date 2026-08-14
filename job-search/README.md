# job-search automation

Daily unattended discovery scan for the `/job-search` skill.

- **`run-job-scan.sh`** -- launchd wrapper. Runs `claude --print` headless with the daily
  discovery prompt across every lane that works unattended: Gmail job alerts (if the
  claude.ai connector is reachable), `hiringcafe.py` + `indeed.py` + `nicheboards.py` +
  `ats-watchlist.py` + `usajobs.py` scripted lanes,
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
