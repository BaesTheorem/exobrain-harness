# job-search automation

Daily unattended discovery scan for the `/job-search` skill.

- **`run-job-scan.sh`** — launchd wrapper. Runs `claude --print` headless with the daily
  discovery prompt: Google X-ray of ATS boards + 80,000 Hours + LinkedIn (if the MCP is
  reachable headless), applies the 4 hard gates, verifies postings open, dedups against
  `~/Exobrain/Projects/Get new job/Job Listings/`, writes per-listing notes for survivors,
  appends a hub-note log entry, and fires a `mist-notify` ONLY when new verified candidates
  are added (silent on zero-survivor days). Inline scan (no parallel subagents) to keep
  daily token cost low. 30-min timeout guard.
- **`com.exobrain.job-scan.plist`** — source copy of the launchd job. Runs daily at 08:00.
  The live copy is a **real file** at `~/Library/LaunchAgents/com.exobrain.job-scan.plist`
  (never a symlink — see `feedback_launchd_symlinks`).

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
- `/tmp/exobrain-job-scan.log` / `.err` — launchd stdout/stderr
- `/tmp/exobrain-job-scan-<timestamp>.out/.err` — per-run Claude output
- `/tmp/exobrain-job-scan-failures.log` — timeouts and non-zero exits

## Caveat: LinkedIn MCP in headless runs
The LinkedIn MCP is interactively authenticated and may be absent in a launchd run. The scan
degrades gracefully to the web lanes (Google X-ray + 80k Hours), which always work, and notes
in the hub-note log which lanes actually ran.
