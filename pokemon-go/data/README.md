# pokemon-go/data (gitignored)

Personal Pokémon GO data lives here and never enters the repo. `pogo` rebuilds it
from the two exports:

| Path | What | Rebuilt by |
|---|---|---|
| `box/<stamp>.json`, `box/latest.json` | Your Pokémon storage parsed from a Poke Genie or Calcy IV CSV export (species, form, CP, HP, IVs, level, moves, shadow/lucky flags, league ranks) | `pogo box import <file.csv>` or the inbox watcher |
| `account/<stamp>/` | The official data-request export, unzipped (Gameplay.txt, InAppPurchases.tsv, FriendList.tsv, GameplayLocationHistory.tsv, Player Journey CSVs) | `pogo account import <export.zip>` or the inbox watcher |
| `account/summary.json` | Counts, totals and date ranges derived from the export. Location coordinates are never copied out of the export folder | same |
| `imports.json` | sha256 of every file already imported, so the watcher never double-imports | any import |
| `state.json` | Watcher bookkeeping (last stale-box nudge) | `pogo inbox --notify` |

Set `POGO_DATA_DIR` to put all of this somewhere else (tests do). The nightly backup
covers gitignored data in sibling repos, so this folder is backed up with the rest.
