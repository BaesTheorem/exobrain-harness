# Pomodoro Timer

A Things 3-styled pomodoro timer that logs sessions to Obsidian daily notes. Runs as a native macOS app via pywebview.

## Setup

```bash
pip install pywebview pillow
bash setup.sh
```

`setup.sh` creates a macOS .app bundle at `~/Desktop/PomodoroTimer.app`.

## Files

| File | Purpose |
|------|---------|
| `main.py` | App entry point — timer logic, Things 3 task picker, Obsidian logging |
| `setup.sh` | Builds the macOS .app bundle |
| `create_icon.py` | Generates the app icon from `AppIcon.icns` |
| `web/index.html` | Timer UI (loaded by pywebview) |

## Dependencies

- `pywebview` — native window wrapper
- `pillow` — icon generation
- Things 3 (reads task list from its SQLite database)
