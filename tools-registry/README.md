# tools-registry

Single source of truth for every tool on this machine — web apps, scheduled jobs/watchers,
and CLI tools — so the inventory never has to be remembered by hand.

`tools-registry-scan.py` auto-discovers tools from two authoritative on-disk sources:

- **App launchers** — `~/Desktop/Apps/*.app` (parses `Contents/MacOS/launch` for `DIR` + `PORT`)
- **Scheduled jobs** — `~/Library/LaunchAgents/{com.exobrain,com.mist,com.nightwatch,com.alexhedtke}*.plist`

For each tool it resolves repo dir, git remote, port, schedule, and live status, then writes
one note per tool into the Obsidian vault's `Tools/` folder. `Tools.base` (vault root) renders
them with views: Apps, Scheduled Jobs, Running Now, By Repo, All. The folder is wiped and
rewritten each run (notes are a disposable projection — never hand-edit them).

CLI-only tools with no launcher and no launchd job are added by hand via the `SUPPLEMENTAL`
list in the scanner.

## Usage

```
python3 tools-registry/tools-registry-scan.py
```

## Auto-refresh

A launchd job (`com.exobrain.tools-registry`, machine-local — not in this repo) runs the scan
daily at 07:15 so the registry stays current. To replicate, create a LaunchAgent that runs the
command above on a `StartCalendarInterval`.
