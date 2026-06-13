---
name: jackbox
description: Play Jackbox games autonomously by driving jackbox.tv in a headed Chrome over the DevTools protocol. Canonical reference for joining a room, reading the screen with vision, and running per-game autopilots (Quiplash 2, Tee K.O.) that write LLM-generated jokes, draw human-like doodles, and vote. Use when the user says "join this jackbox", "play jackbox", "join room <CODE>", gives a 4-letter Jackbox room code, or asks the bot to play Quiplash / Tee K.O. / Drawful / a party game.
---

# Jackbox autopilot

Plays Jackbox party games as a player by driving **jackbox.tv** (the phone-controller site) in a real Chrome window over CDP (Chrome DevTools Protocol). The autopilots run locally in tight loops and use the Claude API for humor/judgment, so they keep up with fast game timers and never steal the user's screen focus.

Plays as **AlexsClaude** by default (<=12 chars; signals to friends it's Alex's bot).

## Architecture (why it's built this way)

- **One persistent Chrome, many short node calls.** `launch.sh` starts Chrome with `--remote-debugging-port=9222` on a **throwaway profile** (`/tmp/jackbox-chrome-profile`) so the user's real Chrome is never touched. Every script then `connectOverCDP('http://localhost:9222')`, acts, and disconnects with `browser.close()` — which **detaches CDP but leaves Chrome running**. This keeps the game session alive across separate tool calls.
- **Autopilots are local loops, not turn-by-turn.** A turn-based agent (screenshot → think → click) is too slow for Quiplash voting windows and Tee K.O. phases. The autopilots (`quiplash.js`, `teeko.js`) poll the DOM every 0.6–1s, detect the phase, and act in-process. Launch them with `nohup … & disown` so they survive.
- **The Claude API does the creative/judgment work**, not the loop. Opus 4.8 writes answers/slogans/draws; Haiku judges text votes fast; Sonnet does vision votes.

## Setup / prerequisites

- Google Chrome installed at `/Applications/Google Chrome.app`.
- Playwright available to node. `env.sh` resolves it into `NODE_PATH`; if missing: `npm i -g playwright && npx -y playwright@1.60 install chromium`.
- `ANTHROPIC_API_KEY` — loaded by `env.sh` from the gitignored `phone/.env` (never inlined). Only the autopilots need it; `control.js`/`shot.js`/`join.js` don't.

All node scripts read `NODE_PATH` + `ANTHROPIC_API_KEY` from the environment, so **always `source scripts/env.sh` first**.

## Quickstart

```bash
cd .claude/skills/jackbox
source scripts/env.sh

# 1. Launch the throwaway Chrome (once per session)
bash scripts/launch.sh                 # CDP on :9222, opens jackbox.tv

# 2. Join the room (name as "AlexsClaude")
node scripts/join.js GBVN

# 3. See what's on screen (vision)
node scripts/shot.js /tmp/jb.png       # then Read /tmp/jb.png
node scripts/control.js peek           # DOM text + interactive elements

# 4. Start the right autopilot for the game in the background
nohup node scripts/quiplash.js >> /tmp/jb-quiplash.log 2>&1 & disown   # Quiplash 2
nohup node scripts/teeko.js    >> /tmp/jb-teeko.log    2>&1 & disown   # Tee K.O.
tail -f /tmp/jb-teeko.log              # live play-by-play
```

Identify the game from the loading flavor text or `control.js peek`: Quiplash 2 shows `#quiplash-answer-input`; Tee K.O. shows a `<canvas>` + `#awshirt-submitdrawing` (internal name "awshirt"/"Awesome Shirt").

## Tools

| Script | Purpose |
|---|---|
| `scripts/env.sh` | **Source first.** Resolves Playwright into `NODE_PATH`, loads `ANTHROPIC_API_KEY` from `phone/.env`. |
| `scripts/launch.sh` | Launch throwaway Chrome w/ remote debugging, open jackbox.tv. |
| `scripts/join.js <CODE> [name]` | Navigate to jackbox.tv, dismiss cookie banner, enter code + name, click PLAY. |
| `scripts/shot.js [out]` | **Reliable** screenshot via raw CDP. Use this for vision. |
| `scripts/control.js <cmd>` | Generic driver: `peek` / `click` / `fill` / `type` / `press`. For manual play and discovering a new game's DOM. |
| `scripts/quiplash.js` | Quiplash 2 autopilot (writing + voting). |
| `scripts/teeko.js` | Tee K.O. autopilot (draw + slogans + voting). |

## Conventions & hard rules

- **Name:** `AlexsClaude` (so the friend group knows it's the bot).
- **Quiplash: NEVER use the Safety Quip** (`#quiplash-submit-safetyquip`) — it's half points. Always submit a real full-points answer via `#quiplash-submit-answer`. On API failure, fall back to a real generic answer, never the safety quip.
- **Don't steal focus.** Never call `page.bringToFront()` — it yanks the Chrome window in front of the user (this was an explicit complaint). The bot plays in its own background window.
- **Run autopilots in the background**, never foreground — and `disown` so they survive the launching shell exiting.

## Humor (this is the point — keep it good)

The answer/slogan prompts encode what actually wins these games (researched + user-validated):
- **Specificity > generic** ("Pulling a Beyoncé" > "dancing"); real brands, oddly specific numbers.
- **Commit to the absurd**; **smart-stupid juxtaposition** (highbrow + idiotic).
- **Misdirection** — skip the first obvious joke; the 3rd/4th idea wins.
- **Relatable darkness** — debt, your ex, the DMV, burnout, existential dread, HR.
- **Punchy, funniest word last** so it lands when read aloud.
- **THE BAR** (aim here, don't copy): *"A cupholder shaped like the middle class"* — a mundane object weaponized into a socioeconomic gut-punch. User flagged this as elite; the prompts target that register, not mere quirk.
- Answers use **best-of-N**: Opus brainstorms 5 candidates across techniques and ships only the funniest. Models: answers/draws/slogans = `claude-opus-4-8`; text votes = `claude-haiku-4-5-20251001`; vision votes = `claude-sonnet-4-6`.

## Drawing (Tee K.O.)

`teeko.js` asks Opus to design a bold, single-subject t-shirt graphic as **normalized stroke paths** (0..1, kept inside 0.12–0.88), then replays them as **real mouse strokes with per-point jitter + segment interpolation** so the lines wobble like a hand drew them (not vector-perfect). It picks the nearest color swatch by sampling palette background colors. Detects a fresh blank canvas (samples the canvas pixels) to handle Tee K.O.'s two-drawings-per-round flow.

## Gotchas (learned the hard way)

- **`page.screenshot()` HANGS on jackbox.tv** ("waiting for fonts to load"). Use `shot.js` (raw CDP `Page.captureScreenshot`) for vision instead. `control.js` only does a best-effort screenshot with a short timeout.
- **Fast windows beat slow paths.** Quiplash voting and Tee K.O. phases close in seconds. Keep per-action latency low: text votes use Haiku (~1s), not vision (~3–5s). If votes are missed, the path is too slow, not the detection.
- **Tee K.O. vote buttons are `awshirt-vote-button`** and are often **text** (the slogan), not images — judge by text. Use the vision fallback only when buttons carry no text.
- **Verify detection against the live DOM** with `control.js peek` before assuming an autopilot will catch a phase — element ids/classes are game-specific.
- Background `node … &` inside a backgrounded shell can die when the wrapper exits; use `nohup … & disown` and confirm with `pgrep -fl`.

## Adding a new game

1. `node scripts/control.js peek` during each phase to learn the element ids/classes (and `shot.js` to see it).
2. Add a phase branch to a new `<game>.js` modeled on `quiplash.js` (text in/out) or `teeko.js` (canvas + vision). Reuse the `claude()` helper and the humor system prompts.
3. Keep the loop fast, text-first, and focus-free.

## Teardown

```bash
pkill -f 'quiplash.js|teeko.js'                       # stop autopilots
pkill -f jackbox-chrome-profile                       # close the throwaway Chrome
rm -rf /tmp/jackbox-chrome-profile /tmp/jb*.log /tmp/jb.png
```

## Privacy

Scripts contain no personal data; the API key is loaded from a gitignored file at runtime, never inlined. Safe to commit. The only outward-facing identity is the player name `AlexsClaude`.
