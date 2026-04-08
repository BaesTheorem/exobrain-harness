# Sailboat Retro

A visual sailboat retrospective tool for TTRPG campaign sessions. Uses the sailboat metaphor (wind = what went well, anchor = what held us back, rocks = risks, island = goals) to facilitate structured session debriefs.

## Gitignored Files

### `retro-data.json`
Campaign and session retro data including party names, session entries, and Obsidian vault paths. Gitignored to keep game state clean on clone.

**To initialize**: Create an empty file:
```json
{"campaigns": {}}
```

The web app (`app.py`) manages campaigns and session entries through the UI.

## Tracked Files

| File | Purpose |
|------|---------|
| `app.py` | Flask web app with drag-and-drop retro board |
| `README.md` | This file |
