# maintenance/

Background housekeeping jobs that keep the machine tidy. Driven by launchd.

## rotate-logs.sh

Caps the size of the scheduled-job logs in `~/Library/Logs/exobrain/`.

Those logs used to live in `/tmp`, where macOS reaped them unprompted. That
reaping is exactly what destroyed the evidence of a run that died with exit -9
before anyone read it (2026-07-28), so the logs moved somewhere durable. The
tradeoff: nothing prunes them now, because launchd appends to
`StandardOutPath` forever. This puts the ceiling back without losing the
history that matters.

- Logs over **512KB** rotate to `.1` (one generation kept). Rotation is a
  **copy-then-truncate, never a move** -- launchd holds an open file descriptor
  on `StandardOutPath`, so renaming the file would leave the job writing into an
  unlinked inode nobody can read again.
- Timestamped per-run artifacts (`job-scan-*.out/.err`,
  `bodyguard-weekly-*.json`) are deleted after **30 days**.

Locks and scratch files stay in `/tmp` on purpose -- clearing those on reboot is
the correct behavior.

### Run by

`~/Library/LaunchAgents/com.exobrain.rotate-logs.plist` (Sundays 04:00).

```bash
bash maintenance/rotate-logs.sh   # run once now
```

## headless-chrome-reaper.sh

Kills orphaned headless Chrome render processes (and their hung shell wrappers)
older than 10 minutes (`THRESHOLD_SECS=600` default). These accumulate when a `Google Chrome --headless`
screenshot / `--dump-dom` / `--print-to-pdf` invocation hangs and never exits, a
known macOS failure mode (see the `browser-render` skill, which is the preferred,
timeout-guarded path that avoids spawning these in the first place).

**Targeting is narrow and safe.** It only kills processes whose command line
contains both `--user-data-dir=/tmp/` (the render profile marker) and a Chrome
headless marker. It will **not** touch:

- LinkedIn MCP's `chrome-headless-shell` (uses `~/.linkedin-mcp/profile`, not /tmp)
- Plaud / other Electron apps (different binary, no /tmp profile)
- Fresh in-flight renders younger than 10 minutes

### Run by

`~/Library/LaunchAgents/com.exobrain.headless-chrome-reaper.plist` (every 120s,
also at load). Logs to `~/.claude/channels/maintenance/`.

### Manage

```bash
launchctl unload ~/Library/LaunchAgents/com.exobrain.headless-chrome-reaper.plist   # stop
launchctl load   ~/Library/LaunchAgents/com.exobrain.headless-chrome-reaper.plist   # start
bash maintenance/headless-chrome-reaper.sh                                          # run once now
```

When it reaps something it appends a one-line timestamped count to the stdout log;
otherwise it's silent.

## tcc_carry_forward.py

Stops the endless `"2.1.235" would like to access files in your Documents
folder` popups from the Claude Code CLI.

**Root cause.** The CLI is a bare Mach-O with no bundle, so TCC identifies it by
**path** (`identifier_type=Path` in tccd's log), and the native installer gives
every release its own path:

```
~/.local/share/claude/versions/2.1.233
~/.local/share/claude/versions/2.1.234   <- new path = brand-new TCC identity
~/.local/share/claude/versions/2.1.235
```

The CLI auto-updates roughly daily. Each bump mints an identity with zero
grants, so Documents, Desktop, Google Drive, app-data, and Things 3 / System
Events automation all get re-approved from scratch. This is the same mechanism
the `session-start` Full Disk Access check already warns about; this script is
the half that can actually be fixed without root.

**Why re-pointing the grant is legitimate, not a bypass.** Every grant stores a
code requirement, and macOS writes a version-independent one here:

```
identifier "com.anthropic.claude-code" and anchor apple generic
  and certificate leaf[subject.OU] = Q6L2SF6YDW
```

Any Anthropic-signed `claude` satisfies it. The consent was never withdrawn or
scoped to a version, macOS just lost track of which binary it was talking to.
The script copies the existing row to the new path **and refuses to write a
grant onto any binary that fails that stored requirement** (`verify_binary`).
Verified with a negative control: Apple's own `/bin/ls` is rejected, so the gate
tests identity, not merely "is it signed".

It never invents a grant. Newest donor row wins, so a permission revoked two
versions ago stays revoked instead of being resurrected. TCC.db is backed up to
`~/Library/Logs/exobrain/tcc-backups/` (7 kept) before any write.

```bash
maintenance/bin/mist-tcc-carry           # carry grants forward
maintenance/bin/mist-tcc-carry --check   # report only; exit 1 = grants pending
maintenance/bin/mist-tcc-carry --prune   # also drop rows for uninstalled versions
```

**Two triggers, because neither covers everything.** The `session-start` hook
runs it on every interactive session (silent when there's nothing to do). The
`com.exobrain.tcc-carry-forward` agent watches the versions **directory** and
fires the instant the updater drops a new binary, which is what covers launchd
routines firing overnight before Alex ever opens a session. WatchPaths targets
the directory, not a file: the changing filename *is* the problem, so there is
no stable file to watch.

Full Disk Access itself (`kTCCServiceSystemPolicyAllFiles`) lives in the
**system** database and needs root, so it cannot be carried. It still has to be
re-added by hand after an upgrade, which is what the hook's separate FDA check
is for.

### One-time setup (Full Disk Access), in this order

Reading TCC.db requires FDA, and TCC keys that grant to the **interpreter's**
path, so the script runs under a dedicated copy we own rather than the shared
Homebrew python (which would hand FDA to every script on the machine).

1. Build the interpreter (gitignored):
   ```bash
   cd maintenance
   python3.12 -m venv --copies venv
   cp venv/bin/python3.12 venv/bin/mist-tcc-python3
   ```
   `venv/`, not the usual `.venv/`: Finder hides dot-directories, so the Full
   Disk Access file picker in step 2 cannot browse to a binary inside one.
2. **System Settings → Privacy & Security → Full Disk Access** → **+** →
   **⌘⇧G** → `maintenance/venv/bin/mist-tcc-python3` → toggle ON.
3. Only then load the agent:
   ```bash
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.tcc-carry-forward.plist
   ```

**Do not reverse steps 2 and 3.** The script lives under `~/Documents`, so
without FDA the launchd job blocks on a Documents prompt just to read its own
source, and hangs there holding a dialog open. Observed on 2026-08-19: the fix
triggering the exact popup it exists to remove. The plist invokes the
interpreter directly rather than the `bin/` wrapper for the same reason -- for a
launchd job TCC judges the executable launchd started, and going through the
`#!/bin/sh` wrapper would demand FDA on `/bin/sh`.
