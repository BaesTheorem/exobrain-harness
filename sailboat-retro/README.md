# Sailboat Retro

A visual sailboat retrospective tool for TTRPG campaign sessions. Uses the sailboat metaphor (wind = what went well, anchor = what held us back, rocks = risks, island = goals) to facilitate structured session debriefs.

## Gitignored Files

### `retro-data.json`
Campaign and session retro data including party names, session entries, and Obsidian vault paths. Gitignored to keep game state clean on clone.

**To initialize**: Nothing to do. `app.py` auto-creates the file on first run
with its `{"parties": ..., "settings": ...}` schema.

The web app (`app.py`) manages parties and session entries through the UI.

## Tracked Files

| File | Purpose |
|------|---------|
| `app.py` | Flask web app with drag-and-drop retro board |
| `README.md` | This file |
