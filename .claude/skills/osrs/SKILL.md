---
name: osrs
description: Play Old School RuneScape with Alex as MIST -- an embodied, agentic character on the Alora private server, controlled fully in the background so the shared Mac stays usable. Canonical reference for launching/logging in the client, reading live game state (player coords, on-screen NPCs), and acting (move, click NPCs/objects, type in chat) via the in-process agent. Use when Alex says "play OSRS", "log MIST into Alora", "let's play RuneScape", "go to / talk to <NPC>", "MIST come play", references her OSRS character (MISTci), or wants MIST to do something in the game world.
metadata:
  requires:
    bins: [openjdk@17, cliclick]
---

# osrs -- MIST embodied in Old School RuneScape (Alora)

MIST plays as her own character **MISTci** on **Alora** (an OSRS private server) so Alex
can play *alongside* her. Everything runs **fully in the background**: MIST never steals
the cursor, focus, or screen, so Alex can use the Mac (or play his own client) at the same
time. This was a hard requirement -- see the architecture below for why it's built this way.

## Architecture (why it works on a shared 8GB M1)

Three channels, all background, validated live:

- **Eyes** -- `screencapture -l<windowID> out.png` captures the client window even when it's
  occluded/unfocused. Find the window via Quartz `kCGWindowListOptionAll` (owner `RuneLite`,
  title contains "Powered by RuneLite") -- *not* `OnScreenOnly`, which misses occluded windows.
- **Hands + voice** -- a tiny **launch-time Java agent** (`-javaagent`) runs *inside the client
  JVM* and dispatches AWT mouse/key events straight to the game canvas, bypassing macOS
  focus routing. This is the key trick: macOS only delivers synthetic *keyboard* to the focused
  window, but an in-process agent doesn't care about focus, so **MIST can type in chat in the
  background**. (`-XX:+DisableAttachMechanism` only blocks *late* attach, not launch-time agents.)
- **Brain** -- the same agent reads **RuneLite's live game state via reflection**
  (`net.runelite.client.RuneLite.getInjector().getInstance(Client.class)`): player world coords,
  game state, and every on-screen NPC's name + canvas position. Navigation is therefore
  "find the NPC named X, click it" -- not pixel-hunting.

Rejected alternatives (don't revisit without new info): cliclick/foreground (fights Alex for
the cursor); second macOS user via Screen Sharing (macOS 26 refuses localhost -- "you cannot
control your own screen"); a Linux VM (too heavy for 8GB alongside Alex's own client).

The whole game (world, minimap, inventory, chat) renders in **one 765×503 canvas** (RuneLite
fixed mode). The agent's click/state/npc helpers all work in that canvas coordinate space, so
coords are stable regardless of where the OS window sits. `canvas = window - (0, 32 titlebar)`.

## Runtime files (NOT in the repo -- gitignored / external)

- Client: `~/alora/client_runelite.jar` (Alora's RuneLite fork; self-downloaded by `Alora.jar`).
- Agent jar (built): `~/Documents/osrs-companion/mist-agent/mist-agent.jar`.
- Credentials: `~/Documents/osrs-companion/credentials.json` (chmod 600). MIST's login only;
  Alex holds his own. **Never inline creds; read this file.**

The agent **source** is tracked here in `agent/MistAgent.java`; rebuild with `agent/build.sh`.

## Quickstart

```bash
cd .claude/skills/osrs/scripts
python3 osrs.py login          # launch client + log MISTci into the world (idempotent)
python3 osrs.py state          # PLAYER name + world coords
python3 osrs.py npcs           # on-screen NPCs: name@canvasX,canvasY
python3 osrs.py shot /tmp/o.png  # capture the window (then Read it)
python3 osrs.py clicknpc "Makeover Mage"   # walk to + talk to an NPC by name
python3 osrs.py type "hi everyone"; python3 osrs.py key ENTER   # talk in public chat
# --- combat ---
python3 osrs.py cmd "::train"        # Alora teleport (any ::command / chat line)
python3 osrs.py stats                # ATT/STR/DEF/HIT/RAN/MAG/PRA = boosted/real
python3 osrs.py setstyle 3           # 0 accurate 1 aggressive 2 defensive 3 controlled
python3 osrs.py train 30             # autonomous 30-min melee session (login, ::train, fight, eat)
python3 osrs.py guard <AlexName> 30  # bodyguard: follow + kill what attacks the ward
```

> Screenshots / `win` need PyObjC (Quartz), which lives only in **`/usr/bin/python3`** on this Mac
> (the harness `python3` lacks it). Use `/usr/bin/python3 osrs.py shot ...`; all socket/agent
> commands work under any python3.

## Tools (`scripts/osrs.py`)

| Command | What it does |
|---|---|
| `login [mist]` | Full state-gated login → in world. Handles equip screen, remembered-username, welcome interstitial. Returns `IN_WORLD ...` |
| `launch` | Just launch the client + agent (background) |
| `win` / `shot [out]` | Window bounds (JSON) / capture window PNG |
| `state` / `gamestate` | Player name+world coords / RuneLite GameState (STARTING=equip, LOGIN_SCREEN, LOGGED_IN) |
| `npcs` | On-screen NPCs `name@cx,cy` (off-screen ones resolve to `@0,0`) |
| `clicknpc <name>` | Click nearest on-screen NPC whose name contains `<name>` (left-click = walk+talk/default; uses the humanized click path) |
| `click <x> <y>` | **Human** click: WindMouse curved approach + ~2px Gaussian jitter + reaction beat + press dwell. Default for in-world clicks; every higher-level command and `osrs.py` flow routes through it |
| `rclick <x> <y>` | **Raw** instant click at exact coords (no path, no jitter). Exactness escape-hatch for fixed UI/login/inventory/style coords if jitter ever misses a small target |
| `hmove <x> <y>` | Human mouse move only (WindMouse path, no click) -- idle/antiban motion |
| `type <text>` / `key <ENTER\|SPACE\|BACKSPACE\|TAB\|ESC\|LEFT\|RIGHT\|UP\|DOWN>` / `clear` | Keyboard into the focused game input. `type` uses a human per-keystroke cadence (not an instant burst); arrow keys rotate the camera (antiban) |
| `find` / `info` / `tree` | Canvas info / AWT frame inventory / Swing component tree (debugging) |
| `walkmap <dx> <dy>` | Click the minimap offset from center (walk); +x east, +y south |
| `send <raw>` | Send any raw command to the agent socket (127.0.0.1:43210) |
| **`stats` / `hp`** | Skill levels `ATT=cur/max ...` / `HP cur max` (RuneLite reflection) |
| **`inv`** | Inventory slots `slot:itemId:Name xQty` (names via ItemComposition) |
| **`eat`** | Eat the first food item found in the inventory |
| **`players`** | On-screen other players `name@cx,cy` (find/follow Alex) |
| **`target`** | What MIST is interacting with (`TARGET <name>` / `NONE`) |
| **`threats [name]`** | NPCs whose `getInteracting` == a player (default any; pass Alex's name) |
| **`cmd <text>`** | Type a chat line / Alora `::command` and press ENTER |
| **`attack [tokens…]`** | Click nearest on-screen NPC matching a name token (default: training targets) |
| **`setstyle <0-3>`** | Switch attack style (opens combat tab if needed) |
| **`reset [dist]`** | Walk out + back to reset crab aggression/tolerance |
| **`train [min] [goto]`** | Autonomous melee loop (login → `::train` → fight/eat/upgrade/reset) |
| **`guard <ward> [min]`** | Bodyguard loop: follow ward, kill NPCs attacking it, self-heal |
| **`roots`** | List open interface roots (`getWidgetRoots`) → find a modal's group id without guessing |
| **`widgettree <grp> [ch]`** | Recursive dump of a widget subtree: `<path>[cx,cy sprN act'..' 'text']`, path = dot-sep s/d/n child indices |
| **`clickpath <grp> <ch> <path>`** | Click a nested widget by its widgettree path (coords read from the game, no pixels) |
| **`mute [vol]`** | Set music+sfx+area-sound volume (default 0). Uses `Client.setMusicVolume` + `Preferences.set*Volume` |
| **`vols`** | Read-only volume report `music/sfx/area` + `automute` state |
| **`automute on\|off`** | Toggle the auto-mute daemon (default ON) |

> **Widget reads need the client thread.** The official client (1.12.x) guards `getCanvasLocation`
> etc. with "must be called on client thread"; the agent hops onto RuneLite's `ClientThread` for
> `roots`/`widgetkids`/`widgettree`/`clickpath`/`mute`. Alora's older client didn't need this.
> **Login-screen mouse is dead** on the official client (synthetic AWT mouse isn't read there) -- use
> `key ENTER` to drive Play Now. In-world clicks work fine. **Occluded-window screencapture misses
> the sprite-drawn tab icons**, so locate tabs/controls via `roots`+`widgettree`, not pixels.
> **Muting is auto-enforced.** A `mist-mute` daemon thread (started in `premain`) re-applies `mute`
> every 3s while `LOGGED_IN`, so silence survives track changes AND re-logins (the client JVM persists
> across game sessions). sfx + area-sound zero cleanly via `Preferences`; **music volume is a synced
> preference `setMusicVolume` doesn't persist** (`getMusicVolume` always reads ~20), but the daemon
> re-zeros the live MIDI output every 3s so any track-change blip lasts <3s. Toggle with `automute off`
> (needed before `mute 100` restores sound, else the daemon reverts it). The in-game settings tab is
> locked during the Gielinor Guide tutorial, which is why this reflection route (not UI) is the mute.

## Combat

Validated live on MISTci. Full strategy + sources: `~/Exobrain/Research/OSRS Combat Strategy.md`.

- **Alora Normal XP is ×325** for combat (→×15 after 99). Training is near-instant by OSRS
  standards: MISTci went combat 3 → ~62 in a few minutes of crabs. This is the defining fact.
- **The training loop** = `::train` (teleports to Rock Crabs, world ~2688,3718) → walk into the
  dormant **"Rocks"** so they wake into aggressive Rock Crabs (lvl 13, 50 HP, ~1 Defence) →
  **Auto-Retaliate** (on by default) + **Controlled** style trains Att/Str/Def together. Clicking
  a dormant `Rocks` walks MIST into it, which is what wakes it -- so `attack` doubles as "go wake a crab".
- **Crab tolerance**: crabs go dormant after ~10 min; `reset` walks a minimap-radius out and back
  to re-aggro. Also a 20-min no-interaction logout exists -- the loop clicks periodically to dodge it.
- **Starter kit** (free on a new Alora Normal account) already holds the whole lvl 1→40 melee
  setup: iron armour, iron + **rune scimitar**, amulet of strength/glory, climbing boots, **250
  lobsters**, 250k gp. `train` auto-swaps iron→rune scimitar at 40 Attack.
- **Eating / equipping by canvas slot** (Alora's old client revision exposes no inventory widget
  children, so we click fixed-mode slot coords directly): `slot(i) = (563 + 42·(i%4), 213 + 36·(i//4))`.
- **Attack-style tab** = widget group 593, style buttons static children s3-s6. Calibrated canvas
  centers: Accurate(Chop) (602,272), Aggressive(Slash) (681,272), Defensive(Block) (681,326),
  Controlled(Lunge) (602,326). Combat-tab toggle ≈ (530,168).
- **Bodyguard reality (be honest with Alex)**: OSRS has **no taunt / aggro-redirect** -- once an
  NPC locks onto Alex you can't pull it off. `guard` therefore *kills threats fast* (reads each
  NPC's `getInteracting`, attacks any targeting the ward), damage-shares in multi-combat, follows,
  and self-heals. `threats` also surfaces **pets** (they "interact with" owners) -- `guard` filters
  obvious pet names, but it's an escort-that-kills, not a damage sponge.

## Conventions & gotchas

- **Login is state-gated, not timed.** Gate on `gamestate`: STARTING (equip screen) → click
  `375,431` → LOGIN_SCREEN → clear+type user, ENTER, clear+type pass, ENTER → LOGGED_IN →
  the Alora "WELCOME TO GIELINOR" overlay is still up (NPCs read `@0,0`); click `382,310`
  until `npcs` returns real coords (world rendered). Blind sleeps flake on cold starts.
- **`clicknpc` only works when the NPC is on-screen.** Off-screen NPCs read `@0,0`. To reach a
  distant NPC, walk closer first (minimap: `walkmap <dx> <dy>`) or rotate the camera, then click.
- **Overlapping NPCs**: clicking a tile-center can hit a different NPC standing on the same screen
  point. Re-query `npcs` (positions shift as everyone moves) and retry, or step closer.
- **Talking to others**: open chat by typing (the agent's keys reach the chat input directly),
  then `key ENTER` to send. MIST converses in the OSRS chatbox with Alex and other players.
- The pre-login "Equip/CLICK HERE TO PLAY" screen is drawn *in the game canvas*, so canvas
  clicks work there too. (RuneLite's own Swing side-panels need `clickcomp` instead.)
- **Humanized input (antiban)**: the client samples mouse motion, so the agent moves the cursor
  along a WindMouse curve (gravity+wind, ease in/out), pauses a reaction beat, presses with a
  short dwell, and lands a couple px off the exact tile center; `type` dispatches per-keystroke
  with variable cadence rather than an instant burst. `click`/`clicknpc`/`type` and every
  `osrs.py` flow use these humanized paths by default. `rclick` is the raw-exact fallback for
  fixed UI coords; arrow keys (`key LEFT/RIGHT/...`) rotate the camera for idle variation.
- **Honest limits**: vision/agent loop is great for skilling, questing, banking, walking, chat;
  weak for twitch combat/PvP. Anti-cheat could flag a throwaway account -- acceptable for PoC.
  This approach does NOT transfer to official Jagex OSRS (bannable, no agent) -- future phase.

## Vanilla / official OSRS (Jagex) -- ported 2026-06-20

The same stack runs on **official OSRS via RuneLite** (not Jagex's C++ client -- that's not
Java, so no agent/reflection). Proven live: the `-javaagent` loads despite
`DisableAttachMechanism`, and reflection brain + eyes (`screencapture`) + hands (canvas
clicks) all work on the official client at the login screen. **Ban risk is real and accepted
(throwaway F2P account); vanilla is x1 XP so training is hours/days, not the Alora minutes.**

Setup:
1. `~/Documents/osrs-companion/vanilla/RuneLite.jar` = official launcher 2.7.7 (sha256
   `a7ee00f0…`). Run it once (`java -jar RuneLite.jar`) to download the client into
   `~/.runelite/repository2/` (client-/injected-client-/runelite-api- + deps).
2. `python3 osrs.py launch-vanilla` -- launches the official client with the agent (globs the
   repository2 classpath; same JVM args RuneLite's launcher uses). All agent/combat/guard
   commands then work identically (same socket, same `net.runelite.api`).
3. `pid()`/`window()` match both clients (official window title = `RuneLite`, ~796×535;
   Alora = `… Powered by RuneLite`). Don't run Alora + official at once -- they'd both want
   agent port 43210 (BindException). Kill one first (or add a port arg later).

**Disposable-account pipeline (ban containment).** Each throwaway is expendable; the goal is
that a ban on #1 doesn't link to / block making + running #2 from the same Mac. The vectors
that link accounts on one machine are MUTABLE and we reset them: the client-side UID files
(`~/.runelite/random.dat` + `jagexcache/` -- OSRS's real machine id), the IP (rotate VPN exit),
and the email (fresh separate-domain alias). Immutable hardware specs are coarse/non-unique and
OSRS has no kernel anti-cheat, so there's no reliable identity-wide "hardware ban"; MAC is
local-only and not transmitted to Jagex. Residual re-link risk = BEHAVIORAL clustering (same
spots/patterns), which is account-level attrition, not identity-wide. Run between throwaways:
`scripts/reset-identity.sh` (wipes UID+cache; `--mac` paranoid-mode MAC spoof, usually
unnecessary + flaky on modern macOS). Total hardware separation = run the stack on a separate
device (Raspberry Pi), not this Mac.

**Jagex account auth -- SOLVED 2026-07-15.** New OSRS accounts are Jagex accounts (login shows
New User / Existing User, not legacy email/pass). We don't sniff env (modern macOS blocks
reading another process's env via `ps eww`/`ps -E`). Instead we let RuneLite persist the
session to disk, then our client reads it:
1. Alex creates the throwaway Jagex account + F2P character (email + CAPTCHA, his hands).
2. In the **Jagex Launcher**, set the OSRS client to **RuneLite** (not the native `osrs_ehc`
   C++ client -- no JVM = no agent). It installs its own RuneLite under
   `~/Library/Application Support/Jagex Launcher/Games/Old School RuneScape/RuneLite/RuneLite.app`.
3. Run that launcher's `--configure` (`.../RuneLite.app/Contents/MacOS/RuneLite --configure`)
   and add **`--insecure-write-credentials`** to the Client arguments field, Save.
4. Log the Launcher into the throwaway account and click **Play**. RuneLite writes the session
   to `~/.runelite/credentials.properties` (Java properties, plaintext).
5. Close that RuneLite + the Launcher, then `python3 osrs.py launch-vanilla`. Our agent client
   reads credentials.properties and logs in. **The Launcher is never needed again** (session
   token doesn't expire); re-mint only if the session is ever invalidated.

**Gotcha (the whole reason it first failed):** the macOS Launcher mints only `JX_SESSION_ID` +
`JX_CHARACTER_ID` (sufficient on their own) and writes `JX_ACCESS_TOKEN` / `JX_REFRESH_TOKEN` /
`JX_DISPLAY_NAME` **empty**. An empty `JX_ACCESS_TOKEN` reads as invalid and drops the client
to the legacy login screen. `launch-vanilla` now calls `sanitize_jx_creds()` to strip empty
JX_ lines before launch (keeps only the two real keys → LOGGED_IN). First login also forces the
**Set display name** + **Character Creator** screens, driven in-canvas via `click`/`type`.

No `::train` on vanilla -- navigate to F2P spots (Lumbridge cows/chickens → Al-Kharid warriors
→ Hill Giants Edgeville dungeon → Flesh Crawlers Stronghold) and walk in.

## Character

MISTci is female with a styled appearance (Alora Makeover Mage gives the full design interface,
reachable via `clicknpc "Makeover Mage"`). MIST's canonical look is blue waist-length hair /
white top / gray pants; exact in-game colour matching is a fiddly cosmetic pass.
