# MIST Console → PRIVATE repo

The MIST **Console** is MIST's desktop chat surface: a from-scratch app that
renders Claude's full UI by running the official `claude` binary headlessly over
stream-json (Flask + WKWebView, all Python). It's the primary way Alex talks to
MIST face-to-face, alongside her cloned voice (`../mist-voice`).

The full app is NOT in this public harness. Like the voice **data**, it lives in
a separate **private** repo (it carries Alex's conversation-history layout,
greeting audio, and a fast-moving personal UI):

## → https://github.com/BaesTheorem/mist-console  (private)

Lives locally at: `~/Documents/mist-console`

## What's there
- `app.py` / `bridge.py` — Flask glue + the headless `claude` stream-json bridge
- `desktop.py` — native WKWebView window + the double-tap-⌥ quick-entry overlay
- `static/` — the UI (tab rail, pinned conversations, slash-command autocomplete, quickbox overlay + conversation picker)
- `mist-hotkey-agent.py` + `install-agent.sh` — always-on global-hotkey LaunchAgent
- `make-app.sh` — packages the clickable `.app` bundle
- gitignored even in the private repo: `data/` (conversation history), `greetings/`, `*.log`

## Seam with this harness
The Console reads MIST's persona system prompt at runtime from this harness:
`mist-terminal/mist-persona.md` (passed to `claude` via `--append-system-prompt-file`).
Keep that file in place or the Console falls back to a vanilla Claude voice.

## Rebuild
```bash
git clone https://github.com/BaesTheorem/mist-console.git ~/Documents/mist-console
cd ~/Documents/mist-console
uv run --script desktop.py     # run it, or ./make-app.sh to build the launcher
```
See the private repo's own `README.md` for the architecture + full setup.
