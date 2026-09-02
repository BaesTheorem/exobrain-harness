---
name: duel
description: "Play Yu-Gi-Oh! against Alex in EDOPro, live, with MIST picking a deck from her roster and making every decision from this session. Use when Alex says 'duel me', 'let's duel', 'play yugioh', 'play against you', 'sit down at EDOPro', 'rematch', 'new duel', 'reconnect the bot', names a deck or format he wants to face, or asks why the bot played something."
metadata:
  repo: "/Users/alexhedtke/Documents/mist-windbot (local-only, no remote; read its README first)"
  client: "/Applications/ProjectIgnis (EDOPro)"
  brain: "launchd com.exobrain.mist-duel-brain, http://127.0.0.1:8777, backend=live"
---

# /duel

MIST is the opponent. Not a script that plays like her: **her**, reading the
whole board each decision and answering from this conversation. A C# WindBot
executor routes every game decision to a local brain server; the brain queues
them; `mist-duel-cli` shows them to you and sends your answer back. Nothing
decides on its own. The only automatic behaviour is a heuristic fallback if a
decision sits unanswered for 240 s, and the log says so when it happens.

All commands below are in `~/Documents/mist-windbot/bin/`. Use `B=~/Documents/mist-windbot/bin`.

## 0. Pick a deck

```
$B/mist-duel-roster pick                 # a deck from the default format, not the last one played
$B/mist-duel-roster pick --format "2005.4 GOAT"
$B/mist-duel-roster pick --style aggro
$B/mist-duel-roster list                 # everything on the roster
```

The first output line is the deck code (`MISTTENGU`, `MISTGB`, ...); the second
says which Forbidden list Alex must host with. **You choose.** Honor a request
if Alex names a deck or a style ("play something aggressive", "Zombies again"),
otherwise let `pick` vary it; the point of a roster is that he doesn't know
what's coming. Then read the plan before sitting down:

```
$B/mist-duel-roster notes <CODE>
```

That prints the deck's engine, its key lines, and its watch-outs. Play the
plan, not just the card text. If he asks what you're playing, tell him; if he
doesn't, it's fine to let the first turn answer.

Adding a deck is a decklist in `decks/<CODE>.txt`, an entry in
`decks/roster.json`, a five-line `[Deck]` subclass in `src/`, then the `mcs`
line in the README and `mist-install`. `build_decks.py` refuses anything off
the named list or over its limit, by card name.

## 1. Preflight (every time, first thing)

```
$B/mist-duel-preflight
```

Every line must be `OK` except the last three (`EDOPro running`, `room hosted`,
`bot connected` may be `WARN` before Alex has hosted). A `FAIL` means **fix
before playing**, because every executor hook is fail-open: a dead brain or a
stale DLL does not error, it hands the duel to stock WindBot and nothing in the
client tells you. The fixes:

- brain unreachable or `backend` not `live`: `launchctl kickstart -k gui/$(id -u)/com.exobrain.mist-duel-brain`, re-run preflight.
- executor size mismatch, bots missing, decks missing: `$B/mist-install` (idempotent; an EDOPro update wipes `bots.json` and the dialogs).
- EDOPro not running: `open -a /Applications/ProjectIgnis/EDOPro.app`. **Never** run `EDOPro-bin --help`; it ignores flags and just boots the GUI.

## 2. Tell Alex how to host (he does this, not you)

Give him exactly this, every time; the time limit is the one people forget:

1. Load his deck in the deck editor. His two for the pre-Xyz format are
   `Zombie World (2011.03 Pre-Xyz)` and `Gravekeepers (2011.03 Pre-Xyz)`. There
   are similarly named older decks; the parenthetical matters.
2. Multiplayer, Host. **Forbidden list: the one `pick` printed** (for the
   default roster that is `2011.03 TCG Pre-Xyz`). **Time limit: 0.** A
   considered answer from you takes 10-30 s and a whole turn a minute or two; a
   3-minute clock will time you out mid-turn, and it timed *him* out once while
   he stepped away.
3. Port 7911, no password. Master Rule doesn't affect legality, but on the old
   shared-field-zone rule **activating a Field Spell destroys the opponent's**.
   Say so if either deck runs one.

He should **not** pick MIST from the WindBot Ignite dropdown for this. That path
has EDOPro spawn the bot itself; you're joining as a network client instead.

## 3. Join, and arm it before he's done clicking

```
$B/mist-duel --wait --deck <CODE>        # run_in_background: true
```

`--wait` polls port 7911 for up to 30 minutes and joins the moment the room
exists, so you don't have to coordinate timing. Run it in the background; it
stays attached for the whole duel.

**A session restart kills the background join and the bot with it.** If the
harness resumes mid-duel, run `$B/mist-duel --rejoin --deck <CODE>` (drops any
orphaned connection first) and go straight back to step 4. Same command when
the bot is stuck in the lobby after a surrender and doesn't re-ready; but
confirm with Alex the duel isn't actually running first, since dropping a
connected bot mid-duel forfeits.

## 4. The play loop (this is the skill)

```
$B/mist-duel-cli next --wait 110        # Bash timeout 130000
```

blocks until a decision arrives and renders the whole board: both fields and
graveyards, banished piles, hand, LP, phase, whose turn, the chain so far, and
every option with its card text. Then:

```
$B/mist-duel-cli answer <id> <index>    # or several indices for multi-select
```

Chain the two in one call so each step costs one tool use:
`$B/mist-duel-cli answer <id> <i> && $B/mist-duel-cli next --wait 110`.

Cadence rules, learned the hard way:

- **On your own turn use `--wait 110`** (Bash timeout `130000`). Each action
  produces the next prompt within a second.
- **When you end your turn use `--wait 580`** (Bash timeout `600000`). Alex's
  turn can take minutes and you only get prompts at chain windows.
- `next` exits 3 with "no decision pending" when the wait expires. That's not
  an error. On his turn it just means he's still thinking; poll again. On *your*
  turn it's suspicious: run `mist-duel-cli log 5` and check `by=` on the last
  lines. `fallback-timeout` means you were too slow and the heuristic answered.
- **The 240 s clock only runs while a decision is pending for you.** Nothing
  pending, no clock. So there's no cost to a long poll on his turn.
- A single decision's reasoning belongs in your head, not in a paragraph to
  Alex. Say one line about the play if it's interesting, then send. He's
  waiting.

What the prompt kinds mean:

| kind | what it is | answer |
|---|---|---|
| `menu` (Main 1/2) | the **entire** menu: every activate / summon / set / reposition, plus Battle Phase / End turn | one index |
| `menu` (Battle) | activations available in battle, `Proceed to attack declarations`, Main 2, End | one index |
| `battle` | every attacker x target pair, direct attacks, Main 2, End | one index |
| `menu` on **opponent's** turn | a chain window: your triggerable traps plus `Do not respond` | one index |
| `select_card` | targets, tributes, discards, searches; the `prompt:` line says which | `min`..`max` indices |
| `effect_yn` / `yes_no` | an optional effect, shown with the card text | `1` yes, `0` no |
| `select_position` / `select_option` | position on summon; multi-effect choice | one index |
| `go_first` | coin toss won | `1` first, `0` second |

Things the board render makes easy to get wrong anyway:

- **Check `MY s/t` for `{FIELD}` before activating a Field Spell.** A second copy
  destroys your own. This was MIST's first-ever misplay and the reason the
  executor now shows the whole menu instead of one card at a time.
- **Don't Warning your own summon.** The game offers you your own set traps in
  your own chain windows. `Do not respond`.
- **Trap thresholds are literal.** Bottomless needs 1500+ ATK *as summoned*,
  boosts included.
- **Gorz is off while the opponent controls any card**, including his own
  field spell. Lethal math ignores it then.
- **Attack order matters when a Mirror Force might be set:** lead with the
  monster whose death pays you.
- Under the shared-field-zone rule, your field spell dying to his drops every
  boost on your board at once. Recheck ATK before attacking.

## 5. After the duel

- `$B/mist-duel-cli log 40` shows the decisions with who made them. Any
  `fallback-timeout` or `heuristic` line is a decision that wasn't you; say so.
- `$B/mist-coach` reviews the full duel log (`~/Documents/mist-windbot/logs/duel-*.jsonl`) for misplays. Offer it, don't force it.
- If Alex asks why you played something, the log has the exact board you saw.
  Answer from it, not from memory.
- A misplay that came from *missing information* is an executor bug (add the
  field to `Snapshot()` in `src/MistExecutor.cs`, recompile with the `mcs` line in
  the README, `mist-install`). A misplay with the information on screen is
  yours. Say which.
- If the deck itself felt wrong, the fix is its `decks/<CODE>.txt` and its
  roster entry, not the skill.

## Formats

`2011.03 TCG Pre-Xyz` (the roster default) is generated by
`~/Documents/mist-windbot/build_prexyz_lflist.py`: the March 2011 TCG list over
every card printed before Generation Force, so Synchro is the newest mechanic.
Trishula is unlimited on it. Heavy Storm is Forbidden, which is why a resolved
field spell tends to stay resolved. `2005.4 GOAT` ships with EDOPro and has one
roster deck; the current TCG list has one modern deck. Both need a matching
host list and Alex's own deck for that format.
