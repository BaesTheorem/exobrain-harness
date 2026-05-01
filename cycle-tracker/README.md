# Cycle Tracker

A self-contained period tracking web app with calendar view and prediction engine. Built as an Exobrain module to help track a partner's menstrual cycle phases, symptoms, and predictions. Notifies the day before a predicted period via macOS notification (8:00 AM via launchd or scheduled task).

## Why `app.py` is missing

`app.py` and `cycle-data.json` are gitignored. `app.py` contains a hardcoded path to a People note in the Obsidian vault, which includes the partner's real name. `cycle-data.json` holds personal health data.

The repo keeps only the public glue: this README, the notification wrapper script, and the skill definition at `.claude/skills/cycle-tracker/SKILL.md`.

## Files

| File | Tracked | Purpose |
|------|---------|---------|
| `README.md` | Yes | This file |
| `notify-check.sh` | Yes | Daily notification wrapper. Calls `python3 app.py --check-notify`; if the result is `NOTIFY:YYYY-MM-DD`, fires a macOS notification telling Alex tomorrow is the predicted period day. Run via launchd or a scheduled task daily at 8:00 AM. |
| `app.py` | No (gitignored) | Single-file Python web app — see "Building app.py" below. |
| `cycle-data.json` | No (gitignored) | Personal health data |

## Building `app.py`

Ask Claude Code to generate `app.py` based on `.claude/skills/cycle-tracker/SKILL.md`. It should be a single-file Python web app (stdlib only, no dependencies) that:

1. **Serves a web UI** on `http://localhost:5173` with a calendar view showing cycle phases
2. **Stores data** in `cycle-data.json` (same directory) with this shape:
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
3. **Calculates cycle phases**: Menstrual (days 1-5), Follicular (day 6 to ovulation-2), Ovulation (~day 14), Luteal (post-ovulation to end), PMS (last 5 days of luteal)
4. **Predicts the next period** using a rolling average of logged cycles
5. **Updates a People note** in the Obsidian vault with current phase, averages, and predictions. Set the `PEOPLE_NOTE` constant to the partner's People note path.
6. **Supports CLI flags**:
   - `--check-notify` → prints `NOTIFY:YYYY-MM-DD` to stdout if the next period is predicted for tomorrow, else nothing. Used by `notify-check.sh`.

## Notification flow

`notify-check.sh` runs `app.py --check-notify`. If `app.py` prints a `NOTIFY:` line, the script fires:

```bash
osascript -e "display notification \"Partner's period is expected tomorrow ($FORMATTED). Be extra thoughtful today.\" with title \"Exobrain — Cycle Tracker\" sound name \"Purr\""
```

Schedule it daily via launchd or the `scheduled-tasks` MCP at ~8:00 AM. There is no plist tracked here yet — install it as a personal scheduled task or one-off plist outside this repo.
