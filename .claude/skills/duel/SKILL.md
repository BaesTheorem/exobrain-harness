---
name: duel
description: "Play Yu-Gi-Oh! against Alex in EDOPro, live, with MIST picking a deck from her roster and making every decision from this session; afterwards, review the game log to tune her decks and coach Alex. Use when Alex says 'duel me', 'let's duel', 'play yugioh', 'play against you', 'sit down at EDOPro', 'rematch', 'new duel', 'reconnect the bot', names a deck or format he wants to face, asks why the bot played something, or says 'review the game', 'coach me', 'how did I play', 'what should I have done', 'tune your deck', 'how's your record'."
metadata:
  repo: "/Users/alexhedtke/Documents/mist-windbot (local-only, no remote; read its README first)"
  client: "/Applications/ProjectIgnis (EDOPro)"
  brain: "launchd com.exobrain.mist-duel-brain, http://127.0.0.1:8777, backend=live"
  coaching_note: "/Users/alexhedtke/Exobrain/Areas/Adventure & Creativity/Yu-Gi-Oh/Coaching.md"
---

# /duel

MIST is the opponent. Not a script that plays like her: **her**, reading the
whole board each decision and answering from this conversation. A C# WindBot
executor routes every game decision to a local brain server; the brain queues
them; `mist-duel-cli` shows them to you and sends your answer back. Nothing
decides on its own. The only automatic behaviour is a heuristic fallback if a
decision sits unanswered for 240 s, and the log says so when it happens.

Two modes. **Play** (steps 0-5) when Alex wants a game. **Review** (the last
section) when he wants to go over one, or you want to tune a deck.

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

## 5. When the game ends

Surrenders, disconnects and timeouts never reach the log, so **record the
result before anything else**, from your point of view:

```
$B/mist-duel-cli result win|loss|draw --note "surrendered at 2800 facing lethal"
```

Then offer a review. Don't force it; he may just want another game. If he does
want one, or you noticed something in your own play, that's the next section.

## Review mode

Trigger: "review the game", "coach me", "how did I play", "what should I have
done", "tune your deck", "how's your record", or your own itch after a game.

```
$B/mist-duel-review digest            # the last duel, turn by turn (or a log name)
$B/mist-duel-review list              # every logged duel: deck, turns, result
$B/mist-duel-review stats             # per-deck record, fallback rate
$B/mist-coach                         # archives the client replay, then the digest
```

The digest is deterministic and it is honest about what it is: **your seat,
not a referee's.** Alex's hand is only a count. Anything he did between two of
your decisions shows up as a diff ("his Zombie Master appeared", "Mirror Force
went to his grave") attributed to the moment you next looked, not to when it
happened. Reason from those observations. Say "looks like" for inferences. Do
not invent a narrative for the parts you couldn't see. Read the whole digest
before writing a word; the review is a judgment call, so it happens here, in
this session, not in a side call.

**Reviewing your own deck** (the part that makes the roster get better):

1. Separate the three failure kinds, because they have different fixes.
   *Information gap* (something you needed wasn't in the prompt): fix
   `Snapshot()` in `src/MistExecutor.cs`, recompile, `mist-install`.
   *Judgment* (it was on screen and you misread it): that's yours; note it in
   the roster's `watch` if it will recur. *Deck* (the right play didn't exist
   in the list): that's the decklist.
2. Ask the deck questions the game actually posed. Which cards were dead in
   hand and why. Which out you needed and didn't have, and how many copies
   would have found it (the hypergeometric numbers are cheap; run them). Which
   trap you set and never wanted to fire. Whether the plan in `notes` matched
   how the game went.
3. Change one thing at a time and write down why: edit `decks/<CODE>.txt`, then
   `build_decks.py <CODE>` (it will refuse an illegal list), then
   `mist-install`, then a dated entry at the top of `decks/JOURNAL.md` with the
   deck, the game, the change, and the reason. Update the roster `plan` or
   `watch` if the *approach* changed, not just the list. `stats` is the
   scoreboard for whether the change held up.
4. Never rewrite a deck off one game. One game is one hand. Three games with
   the same problem is a deck problem.

**Coaching Alex** (the part he asked for):

Write to him the way a good practice partner talks, and put it in
`Areas/Adventure & Creativity/Yu-Gi-Oh/Coaching.md` in the vault (create it if
missing; dated entries, newest first) so it accumulates. The shape:

1. How the game went in three or four sentences, tracking the life totals.
2. The two or three moments where his play cost the most: the turn, what the
   board looked like, what he did, what you'd have done, and *why in terms of
   this game*. Concrete beats general. "Zombie Master into two set cards after
   my MST had already shown I was holding removal" beats "play around traps".
3. Before judging a key turn, **ask what he was holding.** You couldn't see his
   hand, and the play that looks wrong from your seat is sometimes forced. His
   answer changes the coaching; don't skip it.
4. One thing he did well, only if it's real.
5. The single habit for next game. One. He'll remember one.

Things to look for in his side of the digest: turns he passed with cards in
hand; summons into a backrow you'd already shown; resource spends that put him
in lethal range (the Solemn Warning at 4800 that left him at 2800 into a board
that swung for 3100); field spell timing on the shared-zone rule; attacking or
not attacking into face-downs; what he searched and whether the search made
sense under the lock you had up. And the things he did right that he might
not know were right.

No em dashes. No flattery. He wants to get better.
