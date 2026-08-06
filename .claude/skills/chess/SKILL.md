---
name: chess
description: Play annotated chess against Maia (human-like engine at rating levels 1100-1900) directly in chat, with Stockfish move annotations and a board image per move. Use when the user says "let's play chess", "chess game", "play chess", gives a chess move in a running game (e4, Nf3, O-O), asks for analysis of a position, a hint, the PGN, or wants to change difficulty. Also covers the MIST Chess stack (the MIST Chess app, En Croissant, engine roster).
---

# Chess (annotated play mode)

Everything lives in `~/Documents/mist-chess` (repo: MIST Chess). The play
harness is `scripts/chess_play.py`, run with the repo venv:

```bash
CHESS="$HOME/Documents/mist-chess"
PY="$CHESS/.venv/bin/python"
RENDER='/Users/alexhedtke/Documents/Exobrain harness/tmp/images/chess'
"$PY" "$CHESS/scripts/chess_play.py" --render-dir "$RENDER" <command>
```

Always pass `--render-dir` to the harness `tmp/images/chess` path: the
Console only serves images from harness `tmp/`, not from `~/Documents`
or `/tmp`.

## Commands

| Command | What it does |
|---|---|
| `new --level 1500 --color white --id <name>` | start a game (levels 1100-1900 in steps of 100) |
| `move <san> --id <name>` | play a move; validates, annotates, engine replies |
| `board --id <name>` | re-render current position |
| `analyze --id <name>` | Stockfish top-3 lines |
| `hint --id <name>` | best move for the side to move |
| `pgn --id <name>` | full PGN so far |
| `resign --id <name>` | end game |
| `list` | all saved games |

Game state persists in `mist-chess/games/<id>.json`, so a game survives
across sessions. Default `--id` is `game`; use a fresh id per new game
("morning", "lunch") so history is kept. **The MIST Chess app (below)
uses the same files**: a game started in the app can be continued in
chat and vice versa. If the app is open while chat plays the same game,
its view is stale until the game is reopened there.

## Play flow in chat

1. On "let's play": ask level only if unknown; otherwise default to the
   last level played (check `list`). Run `new`, embed the board.
2. Each user message containing a move: run `move <san>`. The script
   prints the annotation for their move, Maia's reply, and the board path.
3. Relay in MIST voice, short: their move + glyph + what it cost (only if
   flagged), engine's reply, then the board image. Do not paste the raw
   script output.
4. Embed the PNG with a RAW path (literal spaces, never percent-encoded):
   `![board](/Users/alexhedtke/Documents/Exobrain harness/tmp/images/chess/<file>.png)`
5. Illegal move: exit code 2, script lists legal moves. Tell them plainly.
6. Game over: script prints final PGN. Offer a quick post-mortem
   (`analyze` at key moments, worst 3 moves from the annotations in the
   game JSON).

## Annotation legend

Stockfish (depth 12) evaluates before/after each human move; the swing
is the mover's centipawn loss: `??` blunder (>=200cp), `?` mistake
(>=100cp), `?!` inaccuracy (>=50cp), nothing if fine. Evals are always
from White's point of view. The engine reply is Maia at 1 node, which is
the setting Maia was trained for: it plays like a human at that rating,
including human mistakes. Do not "fix" it with more nodes.

## Coaching stance

MIST is the accountability partner here too: point out the pattern, not
just the move ("that's the third hanging knight this week"). After a
blunder, one short line on why the better move works. Never dump full
engine lines unprompted; `analyze` is for when Alex asks.

## The rest of the stack

- **MIST Chess.app** (`/Applications`, port 5024): native board UI over
  the same harness (click-to-move, live grading, post-mortem, hint,
  analysis, PGN). Server: `app/server.py`; rebuild the bundle with
  `app/make-app.sh`. Registered in the vault Tools registry.
- **En Croissant** (`/Applications/en-croissant.app`): GUI for deep
  analysis and database work. Engine roster pre-registered: "Stockfish
  18" (full strength) and "Maia 1100-1900". Re-register any time with
  `python3 ~/Documents/mist-chess/encroissant/install-config.py`.
- Engines: `/opt/homebrew/bin/stockfish` (18), `/opt/homebrew/bin/lc0`
  (0.32.1, Metal backend), Maia nets in `mist-chess/engines/maia/`.
- Stockfish runs are capped small (Threads 2, Hash 128) on purpose: 8GB
  machine. Keep analyze depth <= 18 in chat.
