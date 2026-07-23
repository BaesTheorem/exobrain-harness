---
name: mood
description: Track and analyze Alex's mood, mental health, and wellbeing over time. Maintains a structured Mood Journal in Obsidian with day-by-day scores, weekly summaries, and a color-coded calendar heatmap. Use when the user asks about mood, mental health, "how am I doing", "how have I been feeling", "mood check", "update my mood journal", "how was my week emotionally", "any patterns in my mood", or as part of daily briefing and weekly review processing.
---

# Mood Tracking

Maintains `/Users/alexhedtke/Exobrain/Mood Journal.md` -- a longitudinal record of Alex's mental health and wellbeing.

## Scale

**Overall score (1-5):**

| Score | Label | Color | Emoji |
|-------|-------|-------|-------|
| 1 | Struggling | `#e74c3c` (red) | 🔴 |
| 2 | Low | `#e67e22` (orange) | 🟠 |
| 3 | Neutral | `#f1c40f` (yellow) | 🟡 |
| 4 | Good | `#2ecc71` (green) | 🟢 |
| 5 | Thriving | `#3498db` (blue) | 🔵 |

Half-points are valid (e.g., 2.5). Round to nearest 0.5 for display.

**Sub-categories (same 1-5 scale):**

| Category | What it measures | Key data sources |
|----------|-----------------|------------------|
| **Emotional State** | Direct mood reports, sentiment, affect | Transcripts (explicit statements), iMessage tone, Discord tone |
| **Energy** | Vitality, alertness, physical/mental stamina | Fitbit sleep quality/duration, resting HR, activity levels, caffeine timing |
| **Self-Care** | Exercise, nutrition, sleep hygiene, medication | Fitbit steps (15k goal), sleep timing, bedtime drift, alcohol mentions |
| **Social** | Connection quality, social battery, isolation | Transcript social content, Discord activity, iMessage responsiveness |
| **Purpose** | Motivation, progress on priorities, momentum | Things 3 completion, study sessions, procrastination flags, overdue tasks |

**Overall = weighted average leaning toward the lowest sub-score** -- a great social day doesn't cancel out struggling emotionally. Use judgment, not pure math.

## Data Sources & Signals

### Direct signals (high confidence)
- **Explicit mood statements** in transcripts ("feeling bleh", "great day", "anxious about X")
- **Alex's notes to Claude** at end of recordings (he often narrates his state)
- **iMessage tone** -- short/terse replies vs. engaged/warm
- **Discord engagement** -- active participation vs. lurking

### Indirect signals (medium confidence)
- **Fitbit sleep**: Duration, efficiency, bedtime (target: before 12:45 AM). Poor sleep = energy/mood drag
- **Fitbit steps**: <8k = sedentary day (flag), >15k = goal met (boost), >20k = exceptional
- **Fitbit resting HR**: Trending up = stress/poor recovery, trending down = improving fitness
- **Withings body composition**: Weight trend, fat % changes, muscle mass -- use for Self-Care scoring. Do NOT use Fitbit for weight.
- **Things 3 completion rate**: Tasks getting done vs. piling up
- **Pomodoro sessions** (`/Users/alexhedtke/Exobrain/Pomodoro Log.md`): daily session count and total minutes; focused-work momentum feeds the Purpose sub-score
- **Calendar density**: Overstuffed days = stress risk, empty days after heavy ones = recovery

### Inferred signals (use cautiously, mark as inferred)
- **Bedtime drift**: Consistently past 1 AM = self-care slip
- **Alcohol mentions**: Frequency/quantity in transcripts
- **Procrastination patterns**: Same tasks overdue for multiple days (e.g., a follow-up that keeps rolling over)
- **Social marathon detection**: 3+ consecutive high-social days without downtime
- **Deviation from routine**: Skipping exercise blocks, missing study sessions

## How to Score a Day

1. **Gather evidence** from all available sources for that day
2. **Score each sub-category** with a brief justification
3. **Calculate overall** -- weighted toward lowest scores, with judgment
4. **Note the primary driver** -- what most influenced the score ("depleted after 72hr social marathon", "productive study day + good sleep")
5. **Flag patterns** -- is this part of a trend? Deviation from baseline?

## Source of Truth -- Frontmatter

**Daily note YAML frontmatter is the canonical store** for every mood score.
Each daily note (e.g. `Daily notes/Monday, May 11th, 2026.md`) carries:

```yaml
mood_score: 3
mood_emotional: 3
mood_energy: 2.5
mood_self_care: 2
mood_social: 4.5
mood_purpose: 2.5
```

Everything else -- the `### Mood` body section, `mood-data.json`, and the
`Mood Journal.md` heatmap -- is **derived** from these fields. When you score
a day, write the frontmatter first, then render the body and run the sync.

Narrative fields that don't fit in frontmatter (`primary_driver`, `notes`,
`flags`) live in the body section and in `mood-data.json`. They are not
overwritten by the sync script.

## Obsidian Note Structure

The Mood Journal has three sections:

### 1. Calendar Heatmap (top)
An HTML calendar showing each day color-coded by overall score. One table per month. Update this whenever a new day is scored.

### 2. Weekly Summaries
One entry per week (Monday-Sunday), including:
- Overall week score (average of daily scores)
- Sub-category averages for the week
- Weekly narrative (2-3 sentences)
- Trend vs. previous week (arrow up/down/flat)

### 3. Daily Log
Individual day entries with sub-scores, evidence, and primary driver. Most recent at the top within each week.

## Files

- **Source of truth**: daily-note YAML frontmatter (`mood_score` + 5 facets) for each note in `~/Exobrain/Daily notes/`. Edit via Obsidian Properties UI or by skills.
- **Body narrative**: `### Mood` section in the daily note body (primary driver, notes, flags). Free-form prose.
- **Renderer**: `python3 "/Users/alexhedtke/Documents/Exobrain harness/mood-tracker/render-mood-journal.py"` regenerates `~/Exobrain/Mood Journal.md` (calendar heatmaps + weekly summaries + daily log) from frontmatter.
- **No JSON store, no web UI, no REST API.** The vault is the database.

## Updating the Journal

### When to update
- **Daily briefing**: Score the previous day (all data is in by morning)
- **Weekly review**: Add the weekly summary narrative
- **Standalone `/mood`**: Score today so far, or review trends
- **Transcript processing**: If a transcript contains strong mood signals, flag for journal update
- **Obsidian Properties UI**: Alex can edit `mood_score` and the facets directly in any daily note. The renderer picks up manual edits.

### How to update

1. Write the score + 5 facets to the daily note's YAML frontmatter
   (`mood_score`, `mood_emotional`, `mood_energy`, `mood_self_care`,
   `mood_social`, `mood_purpose`).
2. Append a `### Mood` body section to the daily note with the narrative
   (`primary_driver`, notes, flags) -- prose belongs in the body, not in YAML.
3. Run the renderer to regenerate the Mood Journal heatmap:
   ```bash
   python3 "/Users/alexhedtke/Documents/Exobrain harness/mood-tracker/render-mood-journal.py"
   ```
   It walks every daily note, reads frontmatter, and rewrites
   `~/Exobrain/Mood Journal.md` (calendar heatmaps + weekly summaries + daily log).

Manual frontmatter edits (via Obsidian Properties UI) are picked up the next
time the renderer runs -- at evening wind-down, or on demand.

## Integration with Other Skills

- **`/daily-briefing`**: After building the briefing, score yesterday and update the journal. Include a 1-line mood summary in the briefing: "Mood yesterday: 2.5/5 🟠 (depleted after social marathon)"
- **`/weekly-review`**: Generate the weekly summary entry. Compare to prior weeks. Flag multi-week trends.
- **`/process-transcript`**: If the transcript contains direct mood statements, note them for the next journal update. Don't score mid-day -- wait for full-day data.


## Daily Briefing

When called as part of the daily briefing:

1. **Score yesterday**: Gather evidence from all sources already pulled during the briefing (Fitbit via Health Log, calendar, email, tasks). Score each sub-category with brief justification. Calculate weighted overall.
2. **Write yesterday's daily note frontmatter** (source of truth):
   ```yaml
   mood_score: 3
   mood_emotional: 3
   mood_energy: 2.5
   mood_self_care: 2
   mood_social: 3.5
   mood_purpose: 3
   ```
   If yesterday's daily note doesn't exist, create it with frontmatter + nav header first.
3. **Render the `### Mood` body section** in the same note from those values:
   ```markdown
   ### Mood
   **Overall**: 3/5 🟡 -- steady day, self-care dipped
   - Emotional: 3 | Energy: 2.5 | Self-Care: 2 | Social: 3.5 | Purpose: 3
   - *Primary driver: late bedtime + low steps dragged energy/self-care down*
   ```
4. **Render Mood Journal**: Run
   `python3 "/Users/alexhedtke/Documents/Exobrain harness/mood-tracker/render-mood-journal.py"`.
   It reads frontmatter from every daily note and regenerates `Mood Journal.md`.
5. **Mood boost recommendation**: Read the week's daily log entries so far. Identify the lowest or most consistently weak sub-category, then generate ONE concrete, actionable recommendation tied to today's schedule. Examples:
   - Self-Care lowest → "Calendar clear 12-1 PM. A 30-min walk would break the 3-day low-step streak."
   - Energy lowest → "Past 1 AM every night this week. Set a 12:30 AM wind-down alarm."
   - Purpose lowest → "No cert progress in 4 days. Block 45 min before your 2 PM meeting."
6. **Return for today's briefing**:
   - 1-line summary: `**Mood yesterday**: 3/5 🟡 -- steady day, self-care dipped`
   - Boost: `**🎯 Mood boost**: [recommendation]`
   - If multi-day declining trend, flag prominently.

## Proactive Flags

Surface these in daily briefings and ad-hoc responses:
- **3+ days at 2 or below**: "You've been in a rough stretch -- what would help?"
- **Dropping trend**: 3+ consecutive days of declining scores
- **Self-care slip**: Sleep/exercise sub-scores at 1-2 for 3+ days
- **Social overload**: Social score high but Energy/Emotional dropping -- marathon pattern
- **Recovery needed**: Flag empty calendar slots as recovery opportunities after low-score days
