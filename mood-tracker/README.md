# Mood Tracker

Renders `~/Exobrain/Mood Journal.md` from daily-note YAML frontmatter.

## Source of truth

Each daily note's frontmatter stores the mood data:

```yaml
mood_score: 3
mood_emotional: 3
mood_energy: 2.5
mood_self_care: 2
mood_social: 4.5
mood_purpose: 2.5
```

Narrative (primary driver, notes, flags) lives in the daily note's body as a `### Mood` section.

## Files

| File | Purpose |
|------|---------|
| `render-mood-journal.py` | Walks `Daily notes/*.md`, reads frontmatter, regenerates `Mood Journal.md` (calendar heatmaps + weekly summaries + daily log). Stdlib only. |
| `README.md` | This file |

## Run

```bash
python3 render-mood-journal.py
```

The `/mood` and `/evening-winddown` skills run this automatically after they write to frontmatter.
