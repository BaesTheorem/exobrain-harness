# mem-watchdog

A tiny memory watchdog for the 8GB MacBook Air. Born after a runaway `python`
app (one of the pywebview/Flask fleet leaking in its WKWebView frontend over
multi-day uptime) crawled to ~40GB, exhausted RAM, thrashed swap, and froze the
machine hard enough to need a power-button reboot on 2026-06-26. A hard freeze
eats the unified log before any crash report is written, so we never learned
which process did it. This makes sure that never happens silently again.

## What it does

`mem-watchdog.py` runs as a persistent launchd daemon and every 60s:

- logs the top 5 processes by resident memory to `mem-watchdog.log`
- **warns** (macOS notification + sound) when any single process crosses
  `WARN_GB` (default 5GB), throttled to once per process per 10 min
- **auto-kills** (SIGTERM, then SIGKILL after a 10s grace) any process that
  stays above `KILL_GB` (default 12GB) for 2 consecutive checks, unless it is on
  the protected list (kernel_task, WindowServer, Finder, the watchdog itself,
  etc.). At 12GB on an 8GB machine a process is unambiguously a runaway.

Every warn/kill is recorded in `events.log` with the offender's full command, so
the exact culprit is always identifiable after the fact.

## Tunables (env vars, set in the plist if you want to change them)

| Var | Default | Meaning |
|---|---|---|
| `MEMWD_CHECK_SECS` | 60 | seconds between checks |
| `MEMWD_WARN_GB` | 5.0 | notify above this RSS |
| `MEMWD_KILL_GB` | 12.0 | auto-kill above this RSS |
| `MEMWD_SUSTAINED` | 2 | consecutive over-threshold reads before killing |
| `MEMWD_AUTO_KILL` | 1 | set `0` for warn-only (no killing) |
| `MEMWD_TOP_N` | 5 | how many processes to log each tick |

## Install / manage

Two important macOS gotchas dictate the layout:

1. **The script does NOT run from this repo.** This repo lives under
   `~/Documents`, which is TCC-protected. A plain `/usr/bin/python3` launched by
   launchd has no Full Disk Access and gets `Operation not permitted` trying to
   read a `.py` there. So the runtime copy lives in
   `~/Library/Application Support/mem-watchdog/` (not TCC-gated), and its logs
   sit next to it there. **This repo is the canonical source**; the install step
   copies the script into place.
2. **The plist must be a real copy** in `~/Library/LaunchAgents/`, not a symlink
   into this repo (launchd rejects symlinked agents).

```sh
RT="$HOME/Library/Application Support/mem-watchdog"
mkdir -p "$RT"
cp mem-watchdog.py "$RT/mem-watchdog.py"          # runtime copy (out of TCC's way)
cp com.exobrain.mem-watchdog.plist ~/Library/LaunchAgents/
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

- `mem-watchdog.log` -- rolling top-5 snapshot, one line per check
- `events.log` -- warns, kills, and start markers
- `launchd-stderr.log` -- launchd-captured stderr (should stay empty)

The repo `.gitignore` also excludes `*.log` so any stray logs created here while
testing never get committed (they contain process names/paths incl. the
username). The script and plist are generic and safe to commit.
