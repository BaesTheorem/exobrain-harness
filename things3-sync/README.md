# Things 3 → Obsidian Sync

One-way sync from Things 3 to the Obsidian vault. Reads the local Things 3 SQLite database and mirrors project + area structure into `Projects/` notes so the vault has a navigable graph of what's active, deferred, and archived.

This runs in addition to the deep-link convention (every Things project's notes field contains an `obsidian://open?...` link back to its Project note). The sync handles the other direction: making sure those Project notes exist and reflect Things' current status.

## Files

| File | Purpose |
|------|---------|
| `things3-obsidian-sync.py` | The sync script. Queries Things 3's SQLite database read-only, classifies each project as active / someday / archive, and creates or relocates the matching Obsidian note. |
| `run-things3-sync.sh` | launchd wrapper that runs the Python script with the right working directory. |
| `com.exobrain.things3-sync.plist` | launchd plist. `StartInterval: 900` (every 15 min). `RunAtLoad: true`. |

## Sync rules

The script categorizes each Things 3 project (`type=1` rows in `TMTask`) by status, then writes/moves the corresponding Obsidian note under `Projects/`:

| Things 3 state | Obsidian destination | `status:` frontmatter |
|----------------|---------------------|------------------------|
| Active (start ≠ 2, status = 0, not trashed) | `Projects/<Name>/` | `active` |
| Someday (start = 2) | `Projects/Someday/<Name>/` | `someday` |
| Completed / cancelled (status 2 or 3) or trashed | `Projects/Archive/<Name>/` | `archive` |

New projects auto-create their Obsidian note. Area assignments from Things 3 sync into the note's frontmatter `area:` field.

## Install

Copy the plist (real file, NOT a symlink — TCC blocks login-time loading of symlinks into `~/Documents/`):

```bash
cp com.exobrain.things3-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.exobrain.things3-sync.plist
launchctl list | grep com.exobrain.things3-sync
```

Logs:
- `/tmp/exobrain-things3-sync.log` (script output via `logging`)
- `/tmp/exobrain-things3-sync.err` (launchd stderr)

## Configuration constants

Edit these at the top of `things3-obsidian-sync.py` to tune behavior:

| Constant | Default | Purpose |
|----------|---------|---------|
| `THINGS_DB` | `~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/ThingsData-VE3Z1/Things Database.thingsdatabase/main.sqlite` | Read-only path to Things 3's SQLite DB. The `VE3Z1` suffix may differ on a fresh install. |
| `VAULT` | `~/Documents/Exobrain` | Obsidian vault root. |
| `EXCLUDED_AREA_TITLES` | `{"Morning", "Evening"}` | Areas treated as ritual containers, not project areas — projects in these areas are NOT required to have a parent area. |
| `AREA_EXEMPT_PROJECTS` | `{"Shopping list"}` | Project names allowed to live without an area assignment (otherwise the script warns). |

## Read-only safety

The script opens the Things 3 database with `mode=ro` and never writes to it — Things 3 itself is the source of truth for task state. Edits flow Things 3 → Obsidian, never back.
