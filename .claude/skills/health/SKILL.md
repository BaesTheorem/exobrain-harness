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

## MyChart (Epic patient portal)

Available via [OpenRecord](https://github.com/Fan-Pier-Labs/openrecord), hosted at `openrecord.fanpierlabs.com`. Full Epic patient portal access; sessions auto-renew. MCP tools are namespaced `mcp__claude_ai_MyChart__*` (lab results, medications, messages, appointments, etc.).

## Health Log Notes

Path: `/Users/alexhedtke/Exobrain/Areas/Health & Fitness/Health Log/YYYY-MM-DD.md` (one per day).

### Format

```yaml
---
date: YYYY-MM-DD
steps: 0
step_goal: 15000
resting_hr: 0
sleep_hours: 0.0
sleep_score: 0
azm: 0
calories_burned: 0
weight_lbs: 0.0
body_fat_pct: 0.0
muscle_mass_lbs: 0.0
bone_mass_lbs: 0.0
hydration_pct: 0.0
visceral_fat: 0.0
bp_systolic:
bp_diastolic:
pulled_at: "YYYY-MM-DDTHH:MM:SS-05:00"
---
#### Notes
- [trend observations, flags, recommendations]
- [[Daily notes/day name|date]]
```

### Concern Tracking

Health Log notes may include additional frontmatter properties for tracking specific health concerns. These properties and their definitions are kept in a gitignored file (`health-concerns-config.md`) since they contain private health information. The evening winddown skill references that config at runtime.

### Rules

- **Idempotent**: If a Health Log note already exists for a date, read it instead of re-querying APIs. Only update if new data is available (e.g., evening update adds final step count to a note the morning created with Withings data).
- **Morning cross-check** (exception to idempotent rule): When the morning briefing runs and yesterday's Health Log note already exists (created by the evening winddown), always pull fresh Fitbit data for yesterday and compare against the stored values. The evening winddown often runs before all data has synced (late-night steps, sleep data finalized after wake). If any field differs, update the note with the fresh value and note the correction in the `#### Notes` section (e.g., "Morning cross-check: steps updated 3,832 → 4,105").
- **Omit empty fields**: No BP reading = omit `bp_systolic`/`bp_diastolic` entirely. Don't set to null.
- **Raw numbers only**: No units in frontmatter. Units go in display text.
- `Health Log.base` at the vault root renders all notes as filterable/sortable views.

## Morning Snapshot

Called by the daily briefing. Pulls **yesterday's** data and writes/updates the Health Log note.

### What to pull

**Fitbit** (yesterday's date):
- `get_daily_activity_summary` → steps, calories
- `get_heart_rate` → resting HR
- `get_heart_rate_by_date_range` (today minus 15 to today) → RHR baseline for canary check
- `get_temp_skin_by_date_range` (today minus 15 to today) → skin temp baseline for canary confirmer (see **RHR Illness Canary** below)
- `get_azm_timeseries` (past 7 days) → AZM with trend
- `get_sleep_by_date_range` (last night) → sleep score, duration. Use today's date for the query — Fitbit records sleep under the wake-up date.
- `get_activity_timeseries` (past 7 days) → step trend for comparison

**Withings** (only if a weigh-in occurred yesterday):
- `withings_get_measurements` with yesterday's date as both startDate and endDate → check which measurement types were actually recorded
- **Only include fields that were actually measured on that date.** The `withings_get_body_composition` tool silently combines the latest weight with the latest body comp even if they're from different dates — do NOT trust its output blindly. Use `withings_get_measurements` with date filtering to verify which types were recorded.
- Common pattern: a quick weigh-in records only weight (type 1), while a full body scan records weight + fat mass (5) + muscle (76) + bone (88) + hydration (77) + visceral fat (170). Only include fields that have a measurement on that specific date.
- If no weigh-in yesterday: **omit all Withings fields** from the Health Log note. Never carry forward stale Withings data from a prior date.
- Blood pressure: include only if measured that day.

### What to write

1. If yesterday's Health Log note already exists, cross-check all Fitbit fields against the fresh API pull. Update any stale values and log corrections. Then write/update the Health Log note for yesterday's date
2. Return a formatted summary for the daily note (under `#### Health`):

```markdown
- Steps: [value] yesterday (✓ goal) | 7-day avg: [value]
- [sample health data]
- Active Zone Minutes: [value] yesterday | 7-day total: [value]
- Weight: [value] lbs | Fat: [value]% | Muscle: [value] lbs ([value]%)
- Visceral fat: [value] | Bone: [value] lbs | Hydration: [value]%
- *Recommendation: [specific, tied to today's calendar gaps]*
- Full data: [[Areas/Health & Fitness/Health Log/YYYY-MM-DD|Health Log]]
```

### Step goal tracking

Alex's goal: 15,000+ steps/day. Compare yesterday to 7-day average. If below goal, identify a free block in today's calendar and suggest a specific walk time. One recommendation per briefing — don't nag.

### RHR Illness Canary

Resting heart rate typically rises 1-2 days before symptoms appear, but stress and anxiety also elevate RHR. **Skin temperature is the discriminator**: illness pushes nightly skin temp variation +0.2°C (+0.4°F) above baseline; stress does not. The canary fires only when both signals agree.

**Inputs**:
- 15 days of RHR via `get_heart_rate_by_date_range` (today minus 15 to today)
- 15 days of nightly skin temp via `get_temp_skin_by_date_range` (same range)

Drop days with missing readings.

**Baselines** (each computed independently, excluding today's value):
- RHR baseline: median of prior 14 days
- Skin temp baseline: median of prior 14 nights' `nightlyRelative` value (Fitbit already reports this relative to a longer-term personal baseline, so the 14-night median is your near-term normal)

**RHR-elevated condition** (either of):
- Today's RHR ≥3 bpm above RHR baseline AND yesterday's RHR also ≥3 bpm above its baseline
- Today's RHR ≥5 bpm above RHR baseline (single-day spike)

**Skin temp confirmer**: last night's skin temp variation ≥+0.2°C above the 14-night skin-temp median. (Fitbit reports in °C; +0.2°C ≈ +0.36°F.)

**Fire alert only when both the RHR-elevated condition AND the skin temp confirmer are true.**

If RHR is elevated but skin temp is normal, **do not fire** — this is the stress/anxiety pattern, not illness. Do not surface it in the briefing at all.

**Severity** (only applies when alert fires):
- `moderate`: 2-day RHR streak ≥3 bpm + skin temp confirmed, or single-day +5–6 bpm + skin temp confirmed
- `high`: single-day RHR spike ≥7 bpm, OR 3+ day RHR streak ≥3 bpm, in both cases with skin temp confirmed

**Output** (returned to the daily briefing alongside the `#### Health` summary):
```
{
  "fired": true,
  "severity": "moderate" | "high",
  "today_rhr": 82,
  "rhr_baseline": 75,
  "rhr_delta": 7,
  "skin_temp_delta_c": 0.34,
  "streak_days": 3,
  "message": "RHR elevated 7 bpm AND skin temp +0.34°C above baseline (3-day streak). Likely illness onset — consider lightening tomorrow's schedule, hydrating, and protecting sleep."
}
```

If `fired` is false, the briefing omits the alert. **Do not nag**: when the streak ends (RHR returns within 2 bpm of baseline OR skin temp returns to baseline), suppress further alerts until a fresh trigger.

**Skin temp data unavailability**: if the Fitbit API returns no skin temp data for last night (device wasn't worn, or device doesn't support it), do not fire — never fall back to RHR-only, since RHR alone has too many false positives from stress.

**Confounders** to mention in the message when relevant:
- Hard workout in the past 24h (check `get_exercises`) — exercise can elevate next-day RHR
- Heavy alcohol the prior evening — note from the daily note if mentioned
- Travel/altitude change

These don't suppress the alert (skin temp already filters most stress-only events), but the message should acknowledge them so Alex can interpret the signal.

## Evening Update

Called by the evening winddown. Pulls **today's** final activity totals and updates the Health Log note.

- `get_daily_activity_summary` for today → final steps, calories, active minutes
- If the morning briefing already created the note (with Withings data), update only the activity fields
- If no Health Log note exists yet, create one with whatever data is available
- This is the "final tally" for the day — steps vs goal, but don't nag at bedtime

## Reading Historical Data

For downstream consumers (mood scoring, weekly review, monthly review, ad-hoc questions):

**Do not re-query APIs.** Read Health Log notes directly:
- Single day: `Areas/Health & Fitness/Health Log/YYYY-MM-DD.md`
- Date range: Glob `Areas/Health & Fitness/Health Log/*.md`, filter by frontmatter date
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
