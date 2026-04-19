# Extensions

Rules content beyond the 2014 D&D 5e SRD. Loaded by `scripts/srd.py` in addition to `data/srd/`.

## What's vendored here

Content filtered from the [dnd-data](https://github.com/meta-llama/dnd-data) npm package (MIT), restricted to:
- **Publisher**: Wizards of the Coast only.
- **Era**: 2014-rules-era books (anything tagged `(2024)` is excluded).

That gives Alex access to the books he owns:

- Player's Handbook (2014)
- Dungeon Master's Guide (2014)
- Monster Manual (2014)
- Xanathar's Guide to Everything
- Tasha's Cauldron of Everything
- Mordenkainen Presents: Monsters of the Multiverse
- Mordenkainen's Tome of Foes
- Volo's Guide to Monsters
- Fizban's Treasury of Dragons
- Bigby Presents: Glory of the Giants
- Eberron, Wildemount, Ravnica, Strixhaven, Theros campaign books
- Various adventure modules (Curse of Strahd, Descent into Avernus, Icewind Dale, etc.)

Files: `monsters.json`, `spells.json`, `classes.json`, `species.json`, `backgrounds.json`, `items.json`. Each is a flat JSON array with `name`, `kind`, `source`, `description`, `properties`.

**Gitignored.** The harness repo stays free of copyrighted material.

## Lookup

`srd.py lookup <kind> "<name>"` searches `data/srd/` first (canonical SRD shape), then falls back to `data/extensions/`. Extension hits are tagged with their `source` book so the DM can cite it — e.g. "Healing Spirit (Tasha's Cauldron of Everything)".

Results found in extensions are not `house_rule` — they're real 5e content from Alex's books, just not SRD-OGL.

## Adding more

Drop additional JSON files here (flat arrays with `kind` tagging). Homebrew, third-party content, typed-up notes from your own books. See the `dnd-data` format above for the shape `srd.py` expects.
