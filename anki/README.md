# Anki Sync

Polls Anki's SQLite database every 10 minutes and writes session data into the Obsidian vault. Mirrors the pomodoro module's pattern.

## What it writes

**`~/Exobrain/Anki Log.md`** — one H3 date header per day with one bullet per session:
```
### [[Monday, May 11th, 2026]]
- **11:49 AM** -- Security+ (21 cards, 8 min)
- **12:17 PM** -- Security+ (17 cards, 7 min)
```

**Today's daily-note frontmatter:**
- `anki_cards` — total cards reviewed today
- `anki_sessions` — count of distinct study sessions today (each session = a burst of reviews with no 5+ min idle gap)
- `worked_on:` — auto-appends the Project wikilink that matches the decks studied (e.g. Sec+ Certification)

## How sessions are defined

A new session starts when there's a 30+ minute idle gap between consecutive reviews. This means a 25-min lunch break still counts as the same study block. Configurable via `SESSION_GAP_MIN` in `anki-sync.py`.

## Project mapping

`PROJECT_MAPPINGS` at the top of `anki-sync.py` maps deck-name regex → Project wikilink. Current entries:

| Pattern | Display label | Project |
|---------|---------------|---------|
| `security\+|messer` | Security+ | Get new job/Security+ Certification |
| `az-?900` | AZ-900 | Get new job/MS learnings |

Decks that don't match any pattern get the display label "Other" in the log bullet and don't appear in `worked_on:`.

## Files

| File | Purpose |
|------|---------|
| `anki-sync.py` | Main script. Reads Anki SQLite read-only, writes Obsidian. Stdlib only. |
| `run-anki-sync.sh` | Bash wrapper used by launchd (bash typically has Full Disk Access; Python directly often doesn't). |
| `com.exobrain.anki-sync.plist` | launchd LaunchAgent — polls every 10 min, runs at load. |

## Install

```bash
cp anki/com.exobrain.anki-sync.plist ~/Library/LaunchAgents/
chmod +x anki/run-anki-sync.sh
launchctl load ~/Library/LaunchAgents/com.exobrain.anki-sync.plist
```

Use a real file copy, not a symlink — TCC blocks login-time load of plists symlinked into `~/Documents/`.

Verify:
```bash
launchctl list | grep anki-sync
tail -f /tmp/exobrain-anki-sync.log
```

## Behavior notes

- **Idempotent**: every run rewrites today's section of `Anki Log.md` and refreshes today's daily-note frontmatter. Safe to invoke as often as you like.
- **Past days** are never modified — the script only looks at reviews from today's 00:00 onward.
- **Anki must be installed** at the standard profile path (`~/Library/Application Support/Anki2/User 1/collection.anki2`). If the DB is missing or locked, the script no-ops silently.
- **Daily note must exist** for frontmatter to update. The script doesn't create daily notes itself — that's left to the pomodoro app, skills, or Obsidian's Daily Notes plugin.
