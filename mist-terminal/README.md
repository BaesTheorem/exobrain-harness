# mist-terminal

A double-clickable **MIST.app** that launches Claude Code as MIST, in her own
themed terminal, with a spoken greeting.

It ties together pieces that already existed (the Ghostty MIST theme, the cloned
voice). MIST's persona is not injected from a side file: the launcher `cd`s into
the Exobrain harness, where the harness `CLAUDE.md` (the **Identity & Voice:
MIST** block) auto-loads as project instructions — the single source of truth
for her affect.

## What it does

Double-clicking `~/Desktop/Apps/MIST.app`:
1. Opens a new **Ghostty** window (truecolor MIST theme, set in `~/.config/ghostty/config`).
2. Runs `mist-terminal/bin/mist`, which:
   - speaks a short greeting in MIST's offline cloned voice (`mist-voice/bin/mist-say`, non-blocking),
   - prints the MIST banner,
   - `cd`s into the Exobrain harness (so all MCP servers + skills are live **and** `CLAUDE.md` / the persona auto-loads),
   - launches `claude`.

## Files

- `bin/mist` — the launcher run *inside* the terminal (greeting + banner + `claude`, run from the harness). Usable on its own as a `mist` command.
- `make-app.sh` — (re)builds `~/Desktop/Apps/MIST.app`. Idempotent. Re-run after editing the launcher. Builds the app icon from the Cloud-form portrait if present.
- `README.md` — this file.

## Rebuild / install

```sh
mist-terminal/make-app.sh
```

The `.app` bundle lives in `~/Desktop/Apps/` (outside this repo, per the apps convention) — `make-app.sh` regenerates it from these tracked files, so nothing app-specific needs committing.

## Use it as a shell command (optional)

```sh
ln -s "/Users/alexhedtke/Documents/Exobrain harness/mist-terminal/bin/mist" ~/.npm-global/bin/mist
# then, from any directory (it cd's into the harness itself):
mist
```

## Dependencies (already present on this machine)

- **Ghostty** 1.3.1 at `/Applications/Ghostty.app` with the MIST theme in `~/.config/ghostty/config`.
- **Claude Code** CLI (`~/.npm-global/bin/claude`).
- **mist-voice** for the spoken greeting (optional — the launcher skips it cleanly if absent).

## Privacy / legibility

No personal data here. The launcher references Alex by first name (as the rest of
the repo does) and contains no private info, names of others, or credentials. The
persona lives in the harness `CLAUDE.md`; the app bundle is generated, not committed.
