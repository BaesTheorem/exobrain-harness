---
name: game-dev
description: Game design and development partner -- auto-starts the Godot and Blender MCP tool hosts, then helps with mechanics, level design, balance, playtesting, and asset generation. Use when Alex mentions game design, game dev, a Godot project, Blender, Pocket Dungeon, level design, game balance, game feel, playtesting, a game mechanic, sprites/tilesets/3D assets for a game, or says "work on the game", "the game project", "let's build a game", "start the game tools".
---

# Game Dev

Design and build games with direct control of the running engine, instead of writing code blind and hoping.

## Start here, always

**Run the bootstrap before anything else.** Both MCP servers are hosted *by* their app: no app open, no tools. The script is idempotent, so running it when things are already up is free.

```bash
bash .claude/skills/game-dev/scripts/gamedev.sh start all      # godot + blender
bash .claude/skills/game-dev/scripts/gamedev.sh start godot    # just the engine
bash .claude/skills/game-dev/scripts/gamedev.sh status         # what's up right now
bash .claude/skills/game-dev/scripts/gamedev.sh stop all
```

`start` auto-detects the Godot project by walking up from the cwd, then checking one level down (repos often keep the project in a `game/` subdir). Pass a path as the third argument to override.

**The MCP tools only appear after a Claude Code restart** following install. If `status` says UP but no `mcp__godot-ai__*` tools exist in this session, that is the cause. You can still verify a server by speaking JSON-RPC to it directly (HTTP POST to `127.0.0.1:8000/mcp`, or a stdio subprocess for blender), which is how to test without burning a restart.

## The toolchain

| Tool | Where | Port | What it gives you |
|---|---|---|---|
| godot-ai | Godot editor plugin | 8000 (MCP), 9500 (ws) | 43 tools: scene tree, nodes, scripts, signals, materials, animations, editor screenshots, in-editor test suites |
| blender-mcp | Blender addon | 9876 | 22 tools: scene/object info, viewport screenshot, `execute_blender_code`, Poly Haven, Sketchfab, Hyper3D Rodin, Hunyuan3D |
| mist-image | `mist-image/bin/mist-image` | none | Concept art, textures, UI mockups. Cloud GPU, never touches local RAM |
| mist-music | `mist-music/bin/mist-music` | none | Full songs, plus text-to-SFX for creature and foley sounds |

See [[project_gamedev_mcp_tooling]] for install details, ports, and the active project pointers.

## Working in Godot

The reason this setup exists: **textured GLBs segfault `godot --headless`**, so visual verification had no path. Driving the live editor sidesteps the dummy renderer entirely.

- Prefer `editor_screenshot` over reasoning about what the scene probably looks like. Look at it.
- The plugin ships an in-editor GDScript test framework (`McpTestSuite` under `res://tests/`, run via `test_run`). Prefer real suites over one-off `--test-*` CLI flags for anything you will run more than twice.
- `class_name` only registers after an editor scan, which a bare `godot --path` run never does. Use explicit `const X := preload(...)` instead.
- Grep test output for `SCRIPT ERROR` before diagnosing a hang: a GDScript parse error boots a silent empty scene that looks identical to a freeze.
- Mute every test run (`--audio-driver Dummy`) unless audio is the thing under test.

## Working in Blender

- Blender's socket does not open on launch. The bootstrap starts it via a deferred timer; if you opened Blender by hand, click **N sidebar > BlenderMCP > Connect to Claude**.
- Scene-reading tools require a `user_prompt` argument. Omitting it is a pydantic validation error, not a connection failure.
- Telemetry is opt-in and off. Leave it: enabled, it uploads prompts, code snippets, and screenshots.
- For game-ready output, check scale and origin before export. Read the target project's own scale constant rather than assuming Blender units map 1:1.

## Design practice

Engine control is the mature part of this ecosystem. The *design* layer is mostly research papers, not shipping tools, so this is where judgment carries the weight rather than tooling.

- **Playtest before balancing.** A balance change justified by a spreadsheet and not by play is a guess. Run the thing, then change one number.
- **Make the discriminating test.** "Does this feel bad because the hitbox is wrong, or because the animation lies about the timing?" Those predict different observations. Find the one where the two disagree and check that, instead of tweaking both.
- **Feel is measurable in frames.** Input latency, animation start, hitstop, recovery. When something feels off, count frames before theorizing.
- **Keep a difficulty intuition separate from a difficulty measurement.** The designer has played it hundreds of times and is the worst available judge of first-run difficulty.
- **Scope honestly.** A vertical slice that is fully finished teaches more than three half-built systems. Pick the first complete loop and cut everything past it.

## Gotchas that cost real time

- The Godot process registers as **`godot`** (lowercase) from the homebrew binary, but **`Godot`** from `/Applications/Godot.app`. `pgrep -x Godot` silently matches neither on a homebrew launch and reports a live editor as "not running". Always match case-insensitively (`pgrep -ix godot`). This one falsely reported success for several kills in a row while editors quietly stacked up.
- The godot-ai Python server **outlives a force-quit editor** and keeps holding 8000/9500. An open port therefore does NOT mean an editor is attached. Readiness requires port AND process. `status` reports this third state as STALE, and `start godot` re-attaches to it.
- Never launch an app in the background and return immediately: the script exiting can take the still-initializing editor down with it. Wait for the process, not the port.
- macOS App Nap parks occluded Godot windows in the AppKit event loop (a 2% CPU zombie that looks like a hang). The bootstrap sets `NSAppSleepDisabled`; diagnose suspected stalls with `sample <pid>`.

## Not installed, deliberately

**Unreal.** The MCP tooling is the best of the three engines ([remiphilippe/mcp-unreal](https://github.com/remiphilippe/mcp-unreal), 49 tools with headless builds and tests), but UE5 is not viable on an 8GB Air with [[project_mem_watchdog]] killing anything over 12GB. Candidate for the Mac Mini split, not this machine. Do not re-pitch it for the Air.
