# maintenance/

Background housekeeping jobs that keep the machine tidy. Driven by launchd.

## headless-chrome-reaper.sh

Kills orphaned headless Chrome render processes (and their hung shell wrappers)
older than 5 minutes. These accumulate when a `Google Chrome --headless`
screenshot / `--dump-dom` / `--print-to-pdf` invocation hangs and never exits, a
known macOS failure mode (see the `browser-render` skill, which is the preferred,
timeout-guarded path that avoids spawning these in the first place).

**Targeting is narrow and safe.** It only kills processes whose command line
contains both `--user-data-dir=/tmp/` (the render profile marker) and a Chrome
headless marker. It will **not** touch:

- LinkedIn MCP's `chrome-headless-shell` (uses `~/.linkedin-mcp/profile`, not /tmp)
- Plaud / other Electron apps (different binary, no /tmp profile)
- Fresh in-flight renders younger than 5 minutes

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
