# Mood Tracker

A web-based mood journal that tracks daily mood scores with 5 sub-categories (Emotional, Energy, Self-Care, Social, Purpose), weekly summaries, and trend detection.

## Gitignored Files

### `mood-data.json`
Contains daily mood entries with scores, personal notes, sleep timing, social context, and mental health flags. Gitignored because it includes sensitive personal health and wellbeing data.

**To initialize**: Create an empty file:
```json
{
  "entries": [],
  "weekly_summaries": []
}
```

The `/mood` skill and `/evening-winddown` populate entries automatically. Each entry includes:
- `date`, `overall_score` (1-5), sub-scores (emotional, energy, self_care, social, purpose)
- `notes` (free-text), `primary_driver`, `flags` (e.g., bedtime_drift, social_marathon)
- `data_sources` (what signals informed the score)

## Tracked Files

| File | Purpose |
|------|---------|
| `app.py` | Flask web app with calendar heatmap and trend charts |
| `README.md` | This file |
