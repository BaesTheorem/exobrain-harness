# solo-dm

Automated solo D&D 5e (2014 rules) Dungeon Master. Claude runs the game; Alex plays one PC. Designed against LLM-DM sycophancy via structural defenses, not vibes.

## What it does

- Runs a full turn loop: classify → commit DC → roll → adjudicate → narrate → NPC reaction → log.
- Keeps state in SQLite (one DB per campaign) so the main DM context stays at ~1–2k tokens regardless of campaign length.
- Spawns independent subagents for NPCs/monsters (Sonnet for named, Haiku for mooks) with firewalled context — they can't pull punches because they don't know the PC's HP.
- Promotes mooks to named NPCs on triggers (capture, last-of-group, leader succession, named by player).
- Writes a human-readable campaign notebook to Obsidian. Alex can edit; his edits and `> [!alex]` callouts are canon.
- Grounded dice via `secrets.SystemRandom` — real randomness, outside the LLM sampler.
- Cites the 5e SRD + vendored WotC 2014-era content before narrating spell/ability/monster behavior.

## Not in scope

- Human-table GMing — use `TTRPG-campaign-manager`.
- Playing in someone else's campaign — use `ttrpg-player`.
- Shared data with Calimport or any existing TTRPG campaign — this skill is isolated.
- 2024 rules — excluded by design.
- Tasha's-etc. copyrighted content ships gitignored; Alex populated `data/extensions/` with his own books.

## Entry points

- `SKILL.md` — orchestrator prompt. Six modes: setup, session start, play, scene close, session close, campaign status.
- `scripts/db.py` — canonical state (SQLite). Append-only events, sealed turns after a roll lands, retcon discipline.
- `scripts/roll.py` — `secrets.SystemRandom` dice. Writes `rolls` row + JSONL mirror.
- `scripts/srd.py` — rules lookup, SRD + extensions.
- `scripts/context.py` — per-turn context slice (~1k tokens).
- `scripts/sheet.py` — PC mutations (damage/heal/slots/conditions/xp/inventory) + markdown export.
- `prompts/` — templates for named NPC, mook, scene summarizer subagents.

## Self-tests

```
python3 scripts/roll.py --selftest      # chi-squared + adv/dis distribution
python3 scripts/db.py selftest          # sealing + append-only triggers
python3 scripts/context.py selftest     # context size budget
```

## Data layout

- `data/srd/` — vendored MIT-licensed 2014 SRD from 5e-bits/5e-database. In the repo.
- `data/extensions/` — Alex's book content (Xanathar's, Tasha's, etc.). Gitignored.
- `~/Documents/Exobrain harness/data/solo-dm/<slug>/state.sqlite` — per-campaign state. Outside repo, outside vault.
- `~/Documents/Exobrain/Areas/Adventure & Creativity/Solo DnD/<Campaign>/` — shared human-readable notebook. Inside vault, gitignored.

## Anti-sycophancy guarantees

The DB is the audit trail. Session recaps are generated from events, not model memory. If a success appears in the recap without a logged roll, that's a bug — the self-check at session close verifies this.
