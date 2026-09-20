---
name: jackbox
description: Play Jackbox games autonomously by driving jackbox.tv in a headless Chrome over the DevTools protocol. Canonical reference for joining a room, reading the controller screen, and the one-loop autopilot that recognizes the game (Quiplash 2, Tee K.O., with a generic fallback for any text-prompt or vote-among-choices game), writes LLM-generated jokes, draws human-like doodles, and votes. Use when the user says "join this jackbox", "play jackbox", "join room <CODE>", gives a 4-letter Jackbox room code, or asks the bot to play Quiplash / Tee K.O. / Drawful / a party game.
---

# Jackbox autopilot

Plays Jackbox party games as a player by driving **jackbox.tv** (the phone-controller site) in a throwaway **headless** Chrome over CDP. One background loop watches the controller DOM, picks the game module that recognizes the screen, and acts in-process, so it keeps up with fast voting windows and never touches the user's focus. Claude does the creative and judgment work.

Plays as **AlexsClaude** by default (<=12 chars; signals to friends it's Alex's bot).

## Quickstart (the whole night is four commands)

```bash
bin/jackbox launch            # headless Chrome, CDP on :9222, jackbox.tv open. No window, no focus change.
bin/jackbox join GBVN         # exit 0 = in the room; exit 2 = room rejected the code (message says why)
bin/jackbox play              # autopilot in the background; auto-detects the game and switches between games
bin/jackbox status            # running? what phase does it see? Chrome up?
bin/jackbox log               # live play-by-play
bin/jackbox stop --chrome     # end of night
```

Optional: `bin/jackbox shot` (PNG for vision), `bin/jackbox peek` (DOM probe), `bin/jackbox dump <label>` (save the phase for a fixture), `bin/jackbox report` (summarize the game log), `bin/jackbox test` (offline suite), `bin/jackbox launch --headed` (visible window; focus is handed back).

The wrapper sources `scripts/env.sh` (installs node deps on first run, loads a key if one exists). Nothing needs `NODE_PATH`.

## Architecture (why it's built this way)

- **One persistent Chrome, many short node calls.** `launch.sh` starts Chrome with remote debugging on a throwaway profile (`/tmp/jackbox-chrome-profile`). Scripts `connectOverCDP`, act, and disconnect; `browser.close()` on a CDP connection detaches without killing Chrome, so the game session survives across tool calls.
- **Headless by default.** jackbox.tv, its room-lookup API, canvas mouse input, and CDP screenshots all work under `--headless=old` (verified 2026-09-20 on Chrome 153). Headed Chrome activates its own window even via `open -g`, so `--headed` restores focus to the previous app afterwards. `--headless=new` also works but flashes the screen once at launch (see the browser-render skill).
- **One loop, pluggable games.** `autopilot.js` probes the DOM every 500ms (`lib/probe.js`: text, inputs, buttons, vote elements, canvas + blank check in a single `evaluate`), then dispatches to the first module whose `match(state)` fires. The match is sticky through a game's waiting screens, and anything a specific module declines falls through to `games/generic.js`. A Party Pack night that rotates games needs no restart.
- **Trusted input by coordinates.** Votes click at element centers via `Input.dispatchMouseEvent`, never by text selector, so answers containing quotes or emoji can't break a click. Drawing pipelines every mouse event of a stroke over the CDP socket without awaiting each (order is preserved), which is roughly 100x faster than per-point `page.mouse`.
- **Claude through whichever credential exists** (`lib/claude.js`): the Anthropic SDK when `ANTHROPIC_API_KEY` is set, otherwise `claude -p` on Alex's Claude Code login. This machine currently has no API key, so the CLI path is the live one.

## Models and measured latency (CLI provider, 2026-09-20)

| Role | Model | Effort | Wall time |
|---|---|---|---|
| answers, slogans, drawings | `claude-opus-5` | `medium` (`JACKBOX_EFFORT`) | answer 2.6s, 4 slogans 3.2s, 16-stroke design 10s |
| text votes (pairwise + ranking) | `claude-opus-5` | `low` | 2.6s |
| vision votes | `claude-sonnet-5` | `low` | unmeasured live |

Haiku 4.5 through the CLI always thinks and took 5-8s per vote, so it lost to Opus at low effort on both speed and quality. Override any model with `JACKBOX_ANSWER_MODEL` / `JACKBOX_JUDGE_MODEL` / `JACKBOX_VISION_MODEL`. Drawing itself is milliseconds; the design call is the cost.

## Tools

| Path | Purpose |
|---|---|
| `bin/jackbox` (repo root) | The CLI above. Self-registers in the tools registry. |
| `scripts/autopilot.js` | The loop. `--game quiplash|teeko|generic` forces a module, `--name`, `--interval`. |
| `scripts/games/quiplash.js` | Quiplash 2: answer via `#quiplash-answer-input` + `#quiplash-submit-answer`; 2-way votes; **Last Lash** ranks all N answers and keeps clicking next-best (up to 3) while the choices stay on screen, so it fits both single-vote and ranked rounds. |
| `scripts/games/teeko.js` | Tee K.O. ("awshirt"): design -> pipelined strokes -> submit; pre-generated slogan queue; text-first votes with a vision fallback for image-only shirts. |
| `scripts/games/generic.js` | Fallback: answers a lone text prompt, votes among a group of same-styled choice buttons. Never clicks lobby controls (Everyone's in, Skip, Continue, Ready...). |
| `scripts/lib/` | `browser` (connect, CDP screenshot, clickAt), `probe`, `claude` (dual provider), `humor` (prompts + parsers), `draw`, `actions` (fill/submit/vote), `results` (JSONL log). |
| `scripts/join.js`, `shot.js`, `control.js`, `report.js` | Join with real waits; raw-CDP screenshot; peek/click/fill/type/press/dump; log summary. |
| `tests/run.js` + `tests/fixtures/` | Offline suite on the Playwright headless shell: probes, module detection, Last Lash multi-pick, lobby guard, trusted drawing events, and a drawing benchmark. |

## Conventions & hard rules

- **Name:** `AlexsClaude`.
- **Quiplash: NEVER use the Safety Quip** (`#quiplash-submit-safetyquip`), it's half points. On API failure submit a real fallback line from `humor.fallbackAnswer()`.
- **Never bring the window to front.** Headless makes this moot; in headed mode nothing calls `bringToFront()`.
- **Autopilot runs in the background** via the wrapper (`nohup … & disown`), one instance at a time.
- **Generic module stays conservative.** It may only fill a prompt or vote; adding any click on a control button is a bug.

## Humor (this is the point, keep it good)

The prompts in `lib/humor.js` encode what wins these games (researched + user-validated): specificity over generic, commit to the absurd, smart-stupid juxtaposition, misdirection (skip the first obvious joke), relatable darkness, funniest word last. **THE BAR** (aim, don't copy): *"A cupholder shaped like the middle class."* With Opus 5 the five-candidate brainstorm happens in thinking and the reply is the single answer line; the prompt also enforces format constraints (Acro-Lash acronyms, Word-Lash required words, Comic-Lash captions).

**Tuning loop.** Every run writes `tmp/jackbox/games/<stamp>-<game>.jsonl`: each answer with its prompt and latency, each vote with the options and the ranking, each drawing, and every distinct controller screen. `bin/jackbox report` summarizes it. Outcomes are the missing column: the phone controller does not show who won a matchup, so after a game ask Alex which answers landed and annotate the log, then use `/claude-api build-eval` and `hillclimb` on `ANSWER_SYS`. Do not tune the prompt on vibes.

## Drawing (Tee K.O.)

Opus designs a bold single-subject graphic as normalized stroke paths (0..1, inside 0.12-0.88); `lib/draw.js` interpolates each segment into ~8px steps with per-point jitter and replays them as trusted mouse events. Chrome coalesces rapid `mousemove`s to about one per frame regardless of batching (measured: 42 of 66 points survive fully pipelined, 47 with chunks of 4, at 25ms vs 186ms), which still leaves a point every ~12px, finer than a finger. Colors come from sampling palette swatch backgrounds. A fresh blank canvas (pixel sample) re-arms drawing for Tee K.O.'s two-drawings-per-round flow.

## Gotchas (learned the hard way)

- **`page.screenshot()` hangs on jackbox.tv** ("waiting for fonts"). Use `shot.js` / `lib/browser.screenshot` (raw `Page.captureScreenshot`).
- **PLAY stays disabled until jackbox.tv validates the code** with its API; a bad code shows "Room not found". `join.js` waits for either, so its exit code is trustworthy.
- **Cookie banner** appears a beat after load on a fresh profile and covers PLAY. `join.js` polls the body text and clicks Reject/Accept All until it's gone.
- **`claude -p --bare` cannot log in** (it reads only `ANTHROPIC_API_KEY`), and an isolated `CLAUDE_CONFIG_DIR` loses the keychain login too. So the CLI provider runs with the global CLAUDE.md attached (~9k cached input tokens) and strips the kaomoji line MIST's instructions add to every reply.
- **`claude -p` waits 3s for stdin** unless stdin is closed; the provider spawns with `stdio: ['ignore', ...]`.
- **Vote element text is the truth for text games.** Tee K.O. vote buttons are `awshirt-vote-button` and usually carry the slogan; only image-only shirts need the screenshot path.
- **Verify detection against the live DOM** with `bin/jackbox peek` before assuming a phase will be caught; ids are game-specific and Jackbox ships new packs.
- Background `node … &` inside a backgrounded shell can die when the wrapper exits; the wrapper uses `nohup … & disown`.

## Adding a new game

1. During each phase run `bin/jackbox peek` (and `bin/jackbox dump <phase>` to save HTML+PNG under `tmp/jackbox/dumps/`).
2. Write `scripts/games/<game>.js` exporting `{ name, match(state), tick(ctx, state) -> handled }`, modeled on `quiplash.js` (text) or `teeko.js` (canvas + vision). `ctx` gives `page`, `cdp`, `ai`, `probe()`, `record()`, `log()`, `playerName`. Register it in the `MODULES` list in `autopilot.js`.
3. Scrub player names from the dump, trim it to the elements that matter, drop it in `tests/fixtures/`, and add a case to `tests/run.js` (the stub `ai` returns fixed picks). Run `bin/jackbox test`.
4. Keep the loop fast, text-first, and focus-free.

## Teardown

```bash
bin/jackbox stop --chrome     # kills the autopilot and the throwaway Chrome, removes the profile
rm -f /tmp/jb*.png /tmp/jb-autopilot.log
```

## Privacy

Scripts contain no personal data. Game logs and DOM dumps live under the gitignored `tmp/`; dumps of a lobby contain friends' player names, so scrub before promoting one to `tests/fixtures/`. The only outward-facing identity is the player name `AlexsClaude`.
