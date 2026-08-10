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

Alex weighs in the morning before drinking water -- hydration % reads low by design. Not a concern.

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

### Band not worn vs. band not synced

Absent Fitbit data has two very different causes and they look identical on the day. Getting this wrong writes false history: on 2026-08-10 a reconnect flushed nine days of buffered data and revealed that 8/4--8/9 had all been logged as "band off" when the band was on the whole time. 8/7 was recorded as **115 steps**; it was actually **9,297 steps and 6.45 miles**, the best day of the month.

**The discriminators, in order of reliability:**

1. **`distances[activity=tracker]` in `get_daily_activity_summary`.** Non-zero means the wrist recorded it. Zero with a non-zero `total` means the phone recorded it and the band did not.
2. **Presence of the `restingHeartRate` field.** A worn band always produces one. Its absence is strong evidence of non-wear; its presence is proof of wear.
3. Heart-rate zone minutes are **not** a discriminator. Both cases return 1,440 minutes "Out of Range" with zero elevated-zone minutes, because that is also what a genuinely unexerted worn day returns.

**Trap: `get_activity_timeseries` with `resourcePath: "tracker/distance"` returns TOTAL distance, not tracker distance.** It will not discriminate. You must read `distances[activity=tracker]` out of the per-day `get_daily_activity_summary`.

**The honest position when data is absent.** You cannot distinguish non-wear from non-sync from absence alone -- only the *arrival* of data settles it. So:
- Record what the API returned, flag it as provisional, and say which explanation the tracker-distance and RHR checks favor.
- Never write "band off, day N" as settled fact across a multi-day gap. Write "no data, N days" and name the leading hypothesis.
- **When a gap ends, re-pull the whole gap and correct the notes.** Set `backfilled: true` and put a correction block at the top of each amended note rather than silently overwriting -- the original reasoning is worth keeping next to the correction.

Fitbit's daily rollup is also **not stable before roughly noon**. A same-morning "the value did not revise" reading is not evidence of anything.

## Morning Snapshot

Called by the daily briefing. Pulls **yesterday's** data and writes/updates the Health Log note.

### What to pull

**Fitbit** (yesterday's date):
- `get_daily_activity_summary` → steps, calories
- `get_heart_rate` → resting HR
- `get_heart_rate_by_date_range` (today minus 15 to today) → RHR baseline for canary check
- `get_temp_skin_by_date_range` (today minus 15 to today) → skin temp baseline for canary confirmer (see **RHR Illness Canary** below)
- `get_azm_timeseries` (past 7 days) → AZM with trend
- `get_sleep_by_date_range` (last night) → sleep score, duration. Use today's date for the query -- Fitbit records sleep under the wake-up date.
- `get_activity_timeseries` (past 7 days) → step trend for comparison

**Withings** — always call `withings_get_measurements`, never `withings_get_weight` alone:
- `withings_get_measurements` with yesterday's date as both startDate and endDate → check which measurement types were actually recorded
- **Do not gate this call on "did a weigh-in happen."** Alex owns a BPM Connect as well as the scale, and blood-pressure readings arrive independently of weigh-ins. Querying weight only will silently miss them. On 2026-08-07 he took the BP baseline Talkiatry had asked for; because the routine only checked weight, every log from 8/2 to 8/9 kept reporting it as overdue, escalating to "23 days overdue," while the reading sat in the account. Found on 2026-08-10.
- BP measure types: **9 = diastolic, 10 = systolic, 11 = heart pulse**. Weight is 1.
- **Only include fields that were actually measured on that date.** The `withings_get_body_composition` tool silently combines the latest weight with the latest body comp even if they're from different dates -- do NOT trust its output blindly. Use `withings_get_measurements` with date filtering to verify which types were recorded.
- Common pattern: a quick weigh-in records only weight (type 1), while a full body scan records weight + fat mass (5) + muscle (76) + bone (88) + hydration (77) + visceral fat (170). Only include fields that have a measurement on that specific date.
- If no weigh-in yesterday: **omit all Withings fields** from the Health Log note. Never carry forward stale Withings data from a prior date.
- Blood pressure: include only if measured that day.

**Awair (air quality)**: read the latest entry in `/Users/alexhedtke/Exobrain/Areas/Health & Fitness/Air Quality Log.md` (written by the awair-rollup watcher; read the note, don't query the device) and include a one-line CO2/air-quality summary in the daily note's health section.

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

Alex's goal: 15,000+ steps/day. Compare yesterday to 7-day average. If below goal, identify a free block in today's calendar and suggest a specific walk time. One recommendation per briefing -- don't nag.

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

If RHR is elevated but skin temp is normal, **do not fire** -- this is the stress/anxiety pattern, not illness. Do not surface it in the briefing at all.

**Severity** (only applies when alert fires):
- `moderate`: 2-day RHR streak ≥3 bpm + skin temp confirmed, or single-day +5-6 bpm + skin temp confirmed
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
  "message": "RHR elevated 7 bpm AND skin temp +0.34°C above baseline (3-day streak). Likely illness onset -- consider lightening tomorrow's schedule, hydrating, and protecting sleep."
}
```

If `fired` is false, the briefing omits the alert. **Do not nag**: when the streak ends (RHR returns within 2 bpm of baseline OR skin temp returns to baseline), suppress further alerts until a fresh trigger.

**Skin temp data unavailability**: if the Fitbit API returns no skin temp data for last night (device wasn't worn, or device doesn't support it), do not fire -- never fall back to RHR-only, since RHR alone has too many false positives from stress.

**Confounders** to mention in the message when relevant:
- Hard workout in the past 24h (check `get_exercises`) -- exercise can elevate next-day RHR
- Heavy alcohol the prior evening -- note from the daily note if mentioned
- Travel/altitude change

These don't suppress the alert (skin temp already filters most stress-only events), but the message should acknowledge them so Alex can interpret the signal.

## Evening Update

Called by the evening winddown. Pulls **today's** final activity totals and updates the Health Log note.

- `get_daily_activity_summary` for today → final steps, calories, active minutes
- If the morning briefing already created the note (with Withings data), update only the activity fields
- If no Health Log note exists yet, create one with whatever data is available
- This is the "final tally" for the day -- steps vs goal, but don't nag at bedtime

## Reading Historical Data

For downstream consumers (mood scoring, weekly review, monthly review, ad-hoc questions):

**Do not re-query APIs.** Read Health Log notes directly:
- Single day: `Areas/Health & Fitness/Health Log/YYYY-MM-DD.md`
- Date range: Glob `Areas/Health & Fitness/Health Log/*.md`, filter by frontmatter date
- 7-day trends: Read the 7 most recent Health Log notes

This ensures consistency across skills and saves API calls.

## Loki (pet health)

Alex's cat **Loki** is tracked as a first-class health subject, same as Alex.
Her **PetKit PuraMax 2** litterbox has a built-in scale, so a standalone puller
logs every visit's body weight, time, and duration. The litterbox is a cat's
best early-warning sensor -- weight drift and frequency changes show up weeks
before behavior does, and cats hide illness.

- **Puller**: `~/Documents/petkit-loki` (standalone repo, NOT in the harness;
  same pattern as `nest-hvac`/`evergy-energy`). Hourly launchd poll via
  `pypetkitapi`. Raw per-visit data in a gitignored `loki-litter-log.csv`.
- **Daily notes**: `Areas/Health & Fitness/Loki Health Log/YYYY-MM-DD.md`, one
  per day, frontmatter `visits`, `weight_lbs`, `total_minutes`, `avg_visit_min`,
  `poops`. `Loki Health Log.base` renders the filterable views.
- **Profile**: `Areas/Health & Fitness/Loki.md` (baseline, vet notes, watch-items).

**Reading Loki's data** (same rule as Alex's): **don't re-query the API.** Read
the Loki Health Log notes directly. The puller owns the API; skills read the
notes. To force a fresh pull or rebuild a day, see the petkit-loki README.

### Loki anomaly watch (the actual payoff)

When surfacing Loki, compare recent data to her baseline (median weight + typical
daily visit count from the trailing ~14 days of Loki Health Log notes). Flag, as
**watch-items not diagnoses**, and only when the signal is real:

- **Weight slide** -- a sustained drop (≥~5% off baseline median over a week+) is
  the earliest signal for kidney disease, the most common serious problem at her
  age. This is the highest-value flag. Surface it and suggest a vet weigh-in.
- **Frequency spike / straining** -- visits well above baseline, or many short
  trips, can mean a UTI or (emergency) a urinary blockage.
- **Frequency drop** -- well below baseline can mean constipation or reduced
  eating/drinking.

Don't nag: flag a sustained change, not single-day noise. One litterbox weighing
is jittery (she moves); trust the multi-day trend, not one reading.

**Acute no-visit canary** (autonomous, not a briefing job): the puller itself
checks the gap since Loki's last box visit on every hourly poll and fires a
spoken `mist-notify` if she hasn't gone in **12h** (escalates at 18h) -- her
observed max in a month is 10.2h. A cat that stops using the box may be blocked
(a urinary emergency). This fires in near-real-time on its own; the briefing
doesn't need to replicate it. If a gap alert recently fired, mention it in the
next briefing for continuity.

## Integration

| Skill | Uses | How |
|-------|------|-----|
| **daily-briefing** | Morning snapshot | Pulls APIs, writes Health Log, returns formatted summary; reads latest Loki Health Log for the pet line |
| **evening-winddown** | Evening update | Pulls today's final Fitbit totals, updates Health Log; reads today's Loki Health Log |
| **mood** | Read historical | Reads Health Log for sleep/steps/HR as indirect mood signals |
| **weekly-review** | Read historical | 7-day trends from Health Log notes + fresh Withings pull; 7-day Loki weight/visit trend |
| **monthly-review** | Read historical | Month-over-month from Health Log notes, incl. Loki weight trend |
