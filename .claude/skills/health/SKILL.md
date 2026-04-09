---
name: health
description: Pull, persist, and analyze health data from Fitbit and Withings. Single source of truth for Health Log notes in Obsidian. Use when the user asks about health, steps, sleep, weight, heart rate, body composition, "how's my health", "health trends", "pull my health data", or when any skill needs health data (daily briefing, evening winddown, mood scoring, weekly/monthly review).
---

# Health

Single source of truth for all health data. Other skills reference this skill rather than implementing their own Fitbit/Withings logic.

## API Allocation

| API | Use for | Never use for |
|-----|---------|---------------|
| **Fitbit** | Steps, sleep, resting HR, AZM, calories, activity trends | **Weight** (that's Withings only) |
| **Withings** | Weight, body composition (fat %, muscle mass, bone mass, hydration %, visceral fat), blood pressure | Activity data |

Alex weighs in the morning before drinking water — hydration % reads low (~41%) by design. Not a concern.

## Health Log Notes

Path: `/Users/alexhedtke/Documents/Exobrain/Health Log/YYYY-MM-DD.md` (one per day).

### Format

```yaml
---
date: YYYY-MM-DD
steps: 14200
step_goal: 15000
resting_hr: 68
sleep_hours: 7.2
sleep_score: 82
azm: 45
calories_burned: 2450
weight_lbs: 137.1
body_fat_pct: 10.5
muscle_mass_lbs: 116.4
bone_mass_lbs: 6.2
hydration_pct: 41.5
visceral_fat: 1.3
bp_systolic:
bp_diastolic:
pulled_at: "YYYY-MM-DDTHH:MM:SS-05:00"
---
#### Notes
- [trend observations, flags, recommendations]
- [[Daily notes/day name|date]]
```

### Rules

- **Idempotent**: If a Health Log note already exists for a date, read it instead of re-querying APIs. Only update if new data is available (e.g., evening update adds final step count to a note the morning created with Withings data).
- **Omit empty fields**: No BP reading = omit `bp_systolic`/`bp_diastolic` entirely. Don't set to null.
- **Raw numbers only**: No units in frontmatter. Units go in display text.
- `Health Log.base` at the vault root renders all notes as filterable/sortable views.

## Morning Snapshot

Called by the daily briefing. Pulls **yesterday's** data and writes/updates the Health Log note.

### What to pull

**Fitbit** (yesterday's date):
- `get_daily_activity_summary` → steps, calories
- `get_heart_rate` → resting HR
- `get_azm_timeseries` (past 7 days) → AZM with trend
- `get_sleep_by_date_range` (last night) → sleep score, duration. Use today's date for the query — Fitbit records sleep under the wake-up date.
- `get_activity_timeseries` (past 7 days) → step trend for comparison

**Withings** (latest available):
- `withings_get_weight` (imperial) → weight
- `withings_get_body_composition` (imperial) → fat %, muscle mass, bone mass, hydration %, visceral fat
- Blood pressure if measured

### What to write

1. Write/update the Health Log note for yesterday's date
2. Return a formatted summary for the daily note (under `#### Health`):

```markdown
- Steps: 14,200 yesterday (✓ goal) | 7-day avg: 13,100
- [sample health data]
- Active Zone Minutes: 45 yesterday | 7-day total: 210
- Weight: 137.1 lbs | Fat: 10.5% | Muscle: 116.4 lbs (84.9%)
- Visceral fat: 1.3 | Bone: 6.2 lbs | Hydration: 41.5%
- *Recommendation: [specific, tied to today's calendar gaps]*
- Full data: [[Health Log/YYYY-MM-DD|Health Log]]
```

### Step goal tracking

Alex's goal: 15,000+ steps/day. Compare yesterday to 7-day average. If below goal, identify a free block in today's calendar and suggest a specific walk time. One recommendation per briefing — don't nag.

## Evening Update

Called by the evening winddown. Pulls **today's** final activity totals and updates the Health Log note.

- `get_daily_activity_summary` for today → final steps, calories, active minutes
- If the morning briefing already created the note (with Withings data), update only the activity fields
- If no Health Log note exists yet, create one with whatever data is available
- This is the "final tally" for the day — steps vs goal, but don't nag at bedtime

## Reading Historical Data

For downstream consumers (mood scoring, weekly review, monthly review, ad-hoc questions):

**Do not re-query APIs.** Read Health Log notes directly:
- Single day: `Health Log/YYYY-MM-DD.md`
- Date range: Glob `Health Log/*.md`, filter by frontmatter date
- 7-day trends: Read the 7 most recent Health Log notes

This ensures consistency across skills and saves API calls.

## Integration

| Skill | Uses | How |
|-------|------|-----|
| **daily-briefing** | Morning snapshot | Pulls APIs, writes Health Log, returns formatted summary |
| **evening-winddown** | Evening update | Pulls today's final Fitbit totals, updates Health Log |
| **mood** | Read historical | Reads Health Log for sleep/steps/HR as indirect mood signals |
| **weekly-review** | Read historical | 7-day trends from Health Log notes + fresh Withings pull |
| **monthly-review** | Read historical | Month-over-month from Health Log notes |
