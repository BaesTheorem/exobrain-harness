---
name: cycle-tracker
description: Track and manage partner's menstrual cycle — log periods, symptoms, view predictions, and check phase status
user_invocable: true
triggers:
  - period
  - cycle
  - menstrual
  - PMS
  - partner's cycle
  - cycle tracker
---

# Cycle Tracker Skill

Track partner's menstrual cycle phases, symptoms, and predictions.

## Data Location

- **Cycle data**: `/Users/alexhedtke/Documents/Exobrain harness/cycle-tracker/cycle-data.json`
- **Web UI**: `python3 "/Users/alexhedtke/Documents/Exobrain harness/cycle-tracker/app.py"` (opens at http://localhost:5173)
- **People note**: Partner's People/ note in the Obsidian vault (cycle section)

## What This Skill Does

### 1. Log Period Start
When Alex reports that partner's period has started (from transcript, note, or direct input):
- Read `cycle-data.json`
- Add a new cycle entry with `start_date`
- Recalculate averages if there are 2+ cycles
- Update partner's People note with the latest cycle info
- Confirm to Alex what was logged

### 2. Log Period End
When told the period has ended:
- Update the most recent cycle's `end_date`
- Recalculate average period length

### 3. Log Symptoms
When symptoms are mentioned (cramps, headache, mood, irritability, fatigue, etc.):
- Add to `symptoms_log` with today's date
- Valid symptoms: cramps, headache, bloating, breast_tenderness, fatigue, acne, backache, nausea, insomnia, cravings, irritability, anxiety, mood_swings, brain_fog, hot_flashes, dizziness
- Mood and energy are 1-5 scales

### 4. Check Current Phase
Calculate which phase partner is currently in based on her last period start and averages:
- **Menstrual** (Days 1-5): Active bleeding
- **Follicular** (Days 6 to ovulation-2): Estrogen rises, energy increases
- **Ovulation** (Day ~14, ±1): Peak fertility window
- **Luteal** (Post-ovulation to cycle end): Progesterone dominant
- **PMS** (Last 5 days of luteal): Common symptom window

### 5. Predict Next Period
Based on rolling average of logged cycles (default 28 days if <2 cycles logged).

### 6. Launch Web UI
Offer to launch the visual calendar: `python3 "/Users/alexhedtke/Documents/Exobrain harness/cycle-tracker/app.py"`

## Cycle Phase Best Practices

- **Cycle length**: Normal range is 21-35 days. Flag if outside this range.
- **Luteal phase**: Relatively fixed at ~14 days. Variation usually comes from follicular phase.
- **Irregular cycles**: If cycle-to-cycle variation exceeds 7 days, note this as irregular.
- **PMS window**: Symptoms typically appear 5-7 days before period starts. Note any specific PMS symptoms partner has mentioned for personalized tracking.
- **Medical context**: Check partner's People note for any upcoming medical appointments where cycle data may be relevant.

## When Processing Transcripts/Notes

If any transcript or note mentions:
- "period started", "got her period", "that time of the month", "she's on her period"
- Symptoms like cramps, PMS, mood swings, irritability (in context of partner)
- "period ended", "done with her period"

→ Automatically extract and log to cycle-data.json using this skill.

## Updating partner's People Note

Update the `## Cycle Tracking` section in partner's People note **daily** (via the evening winddown) and after any cycle data change. This section should always reflect current status:
- Current phase and day of cycle (e.g., "Follicular — Day 10")
- Average cycle length
- Next predicted period date
- Recent symptoms if any
- Last updated date

The People note path is defined in `PEOPLE_NOTE` in `cycle-tracker/app.py` (gitignored). If the path is unknown, search the People/ folder for partner's note.

## Integration with Daily Briefing

When generating daily briefings, check the cycle tracker:
- If period is predicted within 2 days: flag in briefing
- If currently in PMS window: note it for Alex's awareness
- If currently menstrual: note it
