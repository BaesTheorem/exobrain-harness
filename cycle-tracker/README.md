# Cycle Tracker

A self-contained period tracking web app with calendar view and prediction engine. Built as an Exobrain module to help track a partner's menstrual cycle phases, symptoms, and predictions.

## Why `app.py` is missing

`app.py` is gitignored because it contains a hardcoded path to a People note in the Obsidian vault, which includes the partner's real name. The data file (`cycle-data.json`) is also gitignored since it contains personal health data.

## Building `app.py`

Ask Claude Code to generate `app.py` based on the skill definition at `.claude/skills/cycle-tracker/SKILL.md`. It should be a single-file Python web app (stdlib only, no dependencies) that:

1. **Serves a web UI** on `http://localhost:5173` with a calendar view showing cycle phases
2. **Stores data** in `cycle-data.json` (same directory) with this structure:
   ```json
   {
     "cycles": [
       {
         "start_date": "YYYY-MM-DD",
         "end_date": "YYYY-MM-DD",
         "symptoms_log": [
           {"date": "YYYY-MM-DD", "symptoms": ["cramps", "fatigue"], "mood": 3, "energy": 2}
         ]
       }
     ],
     "averages": {
       "cycle_length": 28,
       "period_length": 5
     }
   }
   ```
3. **Calculates cycle phases**: Menstrual (days 1-5), Follicular (days 6 to ovulation-2), Ovulation (~day 14), Luteal (post-ovulation to end), PMS (last 5 days of luteal)
4. **Predicts next period** based on rolling average of logged cycles
5. **Updates a People note** in the Obsidian vault with current phase, averages, and predictions. Set the `PEOPLE_NOTE` constant to the partner's People note path.
6. **Supports CLI flags**: `--check-notify` returns `NOTIFY:YYYY-MM-DD` if the next period is predicted for tomorrow (used by `notify-check.sh`)

## Files

| File | Tracked | Purpose |
|------|---------|---------|
| `README.md` | Yes | This file |
| `notify-check.sh` | Yes | Daily notification script (launchd/cron) |
| `app.py` | No (gitignored) | Web app — contains partner's People note path |
| `cycle-data.json` | No (gitignored) | Personal health data |
