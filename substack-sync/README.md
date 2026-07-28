# substack-sync

Mirrors posts from the Substack into `posts.json` in the
[becomingstronger.github.io](https://github.com/BecomingStronger/becomingstronger.github.io)
repo, which is what the site's Blog tab renders.

## Why this runs locally

This used to be a GitHub Actions workflow (`.github/workflows/substack-sync.yml`).
It never succeeded once. Every scheduled run died on:

```
urllib.error.HTTPError: HTTP Error 403: Forbidden
```

Substack's edge blocks GitHub's datacenter IPs. It is not a User-Agent problem:
the same request with the same custom UA returns 200 from a residential
connection, and so do a browser UA and no UA at all. Since the fetch only works
from a home IP, the job moved here and the workflow was deleted. Four failure
emails a day stopped with it.

## What it does

1. Fetches the RSS feed and takes the newest 12 items.
2. Parses each into `{title, link, date, excerpt, image}`. The parsing is kept
   byte-identical to the retired workflow so the runner swap produced no diff.
3. Writes `posts.json`, then commits and pushes **only if the content changed**.
4. Notifies via `mist-notify` when a genuinely new post lands. Silent otherwise.

## Schedule

Daily at 07:23 via launchd (`com.exobrain.substack-sync`). The Substack
publishes every few months, so the old every-6-hours cadence was overkill.

## Guards

It refuses to overwrite `posts.json` when the feed 403s, errors, or parses to
zero posts. A stale local clone is handled by rebasing onto `origin/main` and
retrying the push once.

## Manage

```bash
# run now
launchctl kickstart -k gui/$(id -u)/com.exobrain.substack-sync

# stop / start
launchctl bootout   gui/$(id -u)/com.exobrain.substack-sync
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.substack-sync.plist

# logs
tail -20 substack-sync/sync.log

# run against a scratch clone instead of the real repo
BECOMINGSTRONGER_REPO=/tmp/whatever ./run.sh
```

Notes:

- The plist uses `/opt/homebrew/bin/python3`, not `/usr/bin/python3`. The
  CommandLineTools binary lacks TCC Full Disk Access for `~/Documents` under
  launchd, and the site repo lives there.
- Install the plist into `~/Library/LaunchAgents/` as a real copy, not a symlink.
- Pushes authenticate through the osxkeychain credential helper.
