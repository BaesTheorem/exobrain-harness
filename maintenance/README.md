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
