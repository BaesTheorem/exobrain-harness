# mem-watchdog

A memory watchdog for the 8GB MacBook Air. Born after a runaway `python` app
(one of the pywebview/Flask fleet leaking in its WKWebView frontend over
multi-day uptime) crawled to ~40GB, exhausted RAM, thrashed swap, and froze the
machine hard enough to need a power-button reboot on 2026-06-26. A hard freeze
eats the unified log before any crash report is written, so we never learned
which process did it. This makes sure that never happens silently again.

## What it does

`mem-watchdog.py` runs as a persistent launchd daemon. Every `CHECK_SECS` (20s)
it reads the kernel's own pressure level (`kern.memorystatus_vm_pressure_level`:
1 normal, 2 warning, 4 critical), the free-memory percentage, swap, and the
page flow from `vm_stat` (compressions + decompressions per second, the thrash
rate). Those reads cost no fork beyond `vm_stat` and `ps`. The expensive
footprint scan (`top -l 1`, which includes compressed pages) runs on every tick
while pressure is not normal and every `TOP_EVERY` ticks otherwise.

Two kinds of trouble, two kinds of response.

**A runaway process** (the kill logic, unchanged since v3):

- **auto-kills** (SIGTERM, then SIGKILL after a 10s grace) any process that
  stays above `KILL_GB` (12GB) for `SUSTAINED` (2) consecutive checks, unless it
  is on the protected list (kernel_task, WindowServer, Finder, the watchdog
  itself; exact basename match). At 12GB on an 8GB machine a process is
  unambiguously a runaway.
- **emergency-kills** any unprotected process on the FIRST read above
  `EMERGENCY_GB` (16GB), because at that size the machine can freeze before a
  second read happens.
- **fast-kills stateless search tools** (`EXPENDABLE`, default `ugrep,bfs`) on
  the FIRST read above `EXPENDABLE_KILL_GB` (3GB), no streak, no banner. Claude
  Code shadows `grep`/`find` with its embedded ugrep/bfs, and ugrep's DFA regex
  engine has no memory cap (first seen 2026-08-14, 14GB before the streak path
  fired). A killed search loses nothing.
- The kill happens **before** its notification. Notifications run in a thread,
  so a stalled notifier never delays the next tick.

**Diffuse pressure** (new in v4). v3 alerted when swap USED crossed 5.5GB, a
stock that this machine sits above nearly always, so it fired once an hour for
weeks (692 banners between 2026-08-25 and 2026-10-11) and told Alex nothing.
v4 alerts on state, flow and growth. Since 2026-10-14 only the critical
and kill alerts raise a banner (`BANNER_KINDS`). The other kinds below go
to the event log only:

- **critical pressure**: the kernel level reaches 4. Banner with sound,
  re-alert at most every 30 min while it lasts.
- **sustained pressure**: level 2 for `PRESSURE_SUSTAIN_SECS` (10 min) with the
  10-minute thrash average above `THRASH_PAGES_PER_SEC` (3000 pages/s, about
  47 MB/s). Silent banner, at most once per 2 h and `PRESSURE_DAILY_CAP`
  (3) per day. One "cleared" message when pressure has been normal for 10 min.
- **swap high-water mark**: swap used above `SWAP_WARN_GB` (12GB; 13GB preceded
  the 2026-10-08 freeze), with hysteresis. Silent.
- **growth**: a process over `SLOPE_MIN_GB` (1GB) that gained `SLOPE_GB_10MIN`
  (0.5GB) in ten minutes. The banner names the process, the rate in GB/h and the
  time until it reaches physical RAM. One alert per process per hour. This is
  what catches a leak at 1 to 2GB instead of 5.
- **level**: a process over `WARN_GB` (5GB). One alert per process per hour
  (v3 repeated every 10 min), silent.

Every alert carries a `--context` block (pressure, swap, thrash, the top five by
footprint, the live Claude Code sessions and their MCP children) so the MIST
chat that opens on click has the numbers. This watcher sends no Discord DM: Alex
opted it out of the standing watcher rule on 2026-10-12.

**The Console's web view is a known offender.** Its WebContent process grows
with rendered content (every viewed chat's log stays in the page's DOM, hidden)
at about 1.5GB per active chat hour and gives nothing back until the page
reloads (measured 2026-10-11: 2.5 to 7.1GB in three hours, flat when idle). The
Console exposes `GET /ui/webview` (its web process pid, whether a chat is
mid-turn) and `POST /ui/reload`. Above `CONSOLE_RELOAD_GB` (2.5GB) the watchdog
asks for a reload when no chat is streaming; the page reloads once nobody has
typed for a minute, stashing the composer draft and restoring it after. Three
minutes later the watchdog measures the result. If the reload freed memory, the
log says how much. If it did not, that web view is marked and the next banner
offers "Restart Console when idle" (the Console's own `bin/restart-server-when-idle`)
instead of "Reload Console". Alerts about the web view carry that button.

Every warn, kill and reload is recorded in `events.log` with the offender's full
command, so the exact culprit is always identifiable after the fact. The tick
log records pressure level, free %, swap and thrash every 20s, so the next
audit has the flow and not just the stock.

## Tunables (env vars, set in the plist if you want to change them)

| Var | Default | Meaning |
|---|---|---|
| `MEMWD_CHECK_SECS` | 20 | seconds between checks |
| `MEMWD_TOP_EVERY` | 5 | run the footprint scan (`top`) every Nth tick while pressure is normal (every tick otherwise) |
| `MEMWD_WARN_GB` | 5.0 | level alert for one process (once per process per hour) |
| `MEMWD_SLOPE_MIN_GB` | 1.0 | growth alerts only for processes above this |
| `MEMWD_SLOPE_GB_10MIN` | 0.5 | growth alert when a process gains this much in 10 min |
| `MEMWD_PROC_ALERT_THROTTLE` | 3600 | seconds between alerts for the same process |
| `MEMWD_KILL_GB` | 12.0 | auto-kill above this footprint |
| `MEMWD_EMERGENCY_GB` | 16.0 | kill on the first read above this, no streak |
| `MEMWD_SUSTAINED` | 2 | consecutive over-threshold reads before killing |
| `MEMWD_AUTO_KILL` | 1 | set `0` for warn-only (no killing) |
| `MEMWD_EXPENDABLE` | `ugrep,bfs` | comm names killed on first read over the expendable threshold |
| `MEMWD_EXPENDABLE_KILL_GB` | 3.0 | instant-kill threshold for `MEMWD_EXPENDABLE` |
| `MEMWD_THRASH_PAGES_PER_SEC` | 3000 | compressions + decompressions per second that count as thrash |
| `MEMWD_PRESSURE_SUSTAIN_SECS` | 600 | how long level 2 must last before a pressure alert |
| `MEMWD_PRESSURE_REALERT_SECS` | 7200 | seconds between pressure alerts |
| `MEMWD_PRESSURE_DAILY_CAP` | 3 | pressure alerts per day |
| `MEMWD_CRITICAL_REALERT_SECS` | 1800 | seconds between critical alerts |
| `MEMWD_SWAP_WARN_GB` | 12.0 | swap high-water mark (hysteresis: clears 2GB lower) |
| `MEMWD_CONSOLE_PORT` | 5014 | the Console's port |
| `MEMWD_CONSOLE_DIR` | `~/Documents/mist-console` | where `bin/restart-server-when-idle` lives |
| `MEMWD_CONSOLE_RELOAD_GB` | 2.5 | ask the Console to reload its page above this; `0` disables |
| `MEMWD_CONSOLE_RELOAD_COOLDOWN` | 1800 | seconds between reload requests |
| `MEMWD_CONSOLE_RELOAD_CHECK_SECS` | 180 | when to measure the reload's effect |
| `MEMWD_NOTIFY` | 1 | set `0` to log alerts without delivering them |
| `MEMWD_TOP_N` | 5 | how many processes to log each footprint tick |

## Testing a change

```sh
/usr/bin/python3 mem-watchdog.py --once --dry-run
```

One tick, no kills, and every alert goes through `mist-notify --dry-run` (the
composed banner spec is printed, nothing is delivered and no Discord DM is
sent). Logs land next to the script you ran.

## Install / manage

Three macOS gotchas dictate the layout:

1. **The runtime copy lives in `~/Library/Application Support/mem-watchdog/`**,
   not in this repo, so the daemon survives a repo move and keeps its logs out
   of `~/Documents`. **This repo is the canonical source**; the install step
   copies the script into place.
2. **The plist must be a real copy** in `~/Library/LaunchAgents/`, not a symlink
   into this repo (launchd rejects symlinked agents).
3. **The job is declared through `~/.local/bin/mist-launch`** (the harness's
   team-signed launcher, `maintenance/mist-launch/`), then `/bin/bash -c`. TCC
   gives a launchd job the access of the program its plist declares; the
   launcher holds Full Disk Access, so the notifier under `~/Documents` is
   readable. The bash declaration before it worked for the same reason (bash
   has Full Disk Access here) and fixed v3's silent failure: declared as
   `/usr/bin/python3`, every banner, DM and bell-panel entry was lost between
   2026-09 and 2026-10-11 (82 KB of `Operation not permitted` in
   `launchd-stderr.log`). The launcher also makes Login Items show the job under
   MIST Console instead of as a row called "bash".

```sh
RT="$HOME/Library/Application Support/mem-watchdog"
mkdir -p "$RT"
cp mem-watchdog.py "$RT/mem-watchdog.py"          # runtime copy
(cd .. && pwd -P) > "$RT/harness-dir"             # lets the copy find mist-voice/bin/mist-notify
cp com.exobrain.mem-watchdog.plist ~/Library/LaunchAgents/
launchctl bootout gui/$(id -u)/com.exobrain.mem-watchdog 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.mem-watchdog.plist
launchctl enable gui/$(id -u)/com.exobrain.mem-watchdog

# status / stop
launchctl print gui/$(id -u)/com.exobrain.mem-watchdog | grep -E "state|pid"
launchctl bootout gui/$(id -u)/com.exobrain.mem-watchdog
```

**After editing `mem-watchdog.py` in this repo**, re-copy it into `$RT` and
`launchctl kickstart -k gui/$(id -u)/com.exobrain.mem-watchdog` to restart with
the new code. KeepAlive restarts it on crash but does not re-copy the file.

## Logs

Live in `~/Library/Application Support/mem-watchdog/` next to the runtime script:

- `mem-watchdog.log` -- one line per tick: pressure level, free %, swap, thrash
  rate, and the top 5 by footprint on footprint ticks
- `events.log` -- pressure transitions, alerts (`GROWTH`, `LEVEL`, `NOTIFY`,
  `NOTIFIED`), kills, Console reload requests and their measured results, start
  markers
- `launchd-stderr.log` -- launchd-captured stderr (should stay empty)

The repo `.gitignore` also excludes `*.log` so any stray logs created here while
testing never get committed (they contain process names/paths incl. the
username). The script and plist are generic and safe to commit.
