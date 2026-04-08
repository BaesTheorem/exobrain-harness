---
name: mood
description: Track and analyze Alex's mood, mental health, and wellbeing over time. Maintains a structured Mood Journal in Obsidian with day-by-day scores, weekly summaries, and a color-coded calendar heatmap. Use when the user asks about mood, mental health, "how am I doing", "how have I been feeling", "mood check", "update my mood journal", "how was my week emotionally", "any patterns in my mood", or as part of daily briefing and weekly review processing.
---

# Mood Tracking

Maintains `/Users/alexhedtke/Documents/Exobrain/Mood Journal.md` — a longitudinal record of Alex's mental health and wellbeing.

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

**Overall = weighted average leaning toward the lowest sub-score** — a great social day doesn't cancel out struggling emotionally. Use judgment, not pure math.

## Data Sources & Signals

### Direct signals (high confidence)
- **Explicit mood statements** in transcripts ("feeling bleh", "great day", "anxious about X")
- **Alex's notes to Claude** at end of recordings (he often narrates his state)
- **iMessage tone** — short/terse replies vs. engaged/warm
- **Discord engagement** — active participation vs. lurking

### Indirect signals (medium confidence)
- **Fitbit sleep**: Duration, efficiency, bedtime (target: before 12:45 AM). Poor sleep = energy/mood drag
- **Fitbit steps**: <8k = sedentary day (flag), >15k = goal met (boost), >20k = exceptional
- **Fitbit resting HR**: Trending up = stress/poor recovery, trending down = improving fitness
- **Withings body composition**: Weight trend, fat % changes, muscle mass — use for Self-Care scoring. Do NOT use Fitbit for weight.
- **Things 3 completion rate**: Tasks getting done vs. piling up
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
3. **Calculate overall** — weighted toward lowest scores, with judgment
4. **Note the primary driver** — what most influenced the score ("depleted after 72hr social marathon", "productive study day + good sleep")
5. **Flag patterns** — is this part of a trend? Deviation from baseline?

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

## Data & Web UI

- **Data file**: `/Users/alexhedtke/Documents/Exobrain harness/mood-tracker/mood-data.json`
- **Web UI**: `python3 "/Users/alexhedtke/Documents/Exobrain harness/mood-tracker/app.py"` → http://localhost:5174
- **Obsidian note**: `/Users/alexhedtke/Documents/Exobrain/Mood Journal.md` (auto-synced on every change)
- **CLI sync**: `python3 "/Users/alexhedtke/Documents/Exobrain harness/mood-tracker/app.py" --sync` (regenerate Obsidian note from data)

The web app provides a full calendar heatmap, trend chart, sub-category sliders, flag chips, edit/delete on all entries, and editable weekly narrative summaries. All changes sync automatically to the Obsidian Mood Journal note.

## Updating the Journal

### When to update
- **Daily briefing**: Score the previous day (all data is in by morning)
- **Weekly review**: Add the weekly summary narrative
- **Standalone `/mood`**: Score today so far, or review trends
- **Transcript processing**: If a transcript contains strong mood signals, flag for journal update
- **Web UI**: Alex can log directly at http://localhost:5174

### How to update (programmatic)
1. Read `mood-data.json`
2. Add/update the entry in the `entries` array
3. Save the file
4. Run `python3 app.py --sync` to regenerate the Obsidian note
   — OR use the REST API: `POST /api/entries` (auto-syncs)

### REST API
- `GET /api/data` — full data
- `GET /api/trends?days=14` — recent entries
- `GET /api/streak` — current scoring streak
- `POST /api/entries` — create/update entry (auto-syncs Obsidian)
- `DELETE /api/entries?date=YYYY-MM-DD` — delete entry (auto-syncs)
- `POST /api/weekly-narrative` — update week narrative (auto-syncs)

## Integration with Other Skills

- **`/daily-briefing`**: After building the briefing, score yesterday and update the journal. Include a 1-line mood summary in the briefing: "Mood yesterday: 2.5/5 🟠 (depleted after social marathon)"
- **`/weekly-review`**: Generate the weekly summary entry. Compare to prior weeks. Flag multi-week trends.
- **`/process-transcript`**: If the transcript contains direct mood statements, note them for the next journal update. Don't score mid-day — wait for full-day data.
- **`/hey-claude`**: Can answer "how have I been feeling?" or "show my mood trends" by reading the journal.

## Proactive Flags

Surface these in daily briefings and hey-claude responses:
- **3+ days at 2 or below**: "You've been in a rough stretch — what would help?"
- **Dropping trend**: 3+ consecutive days of declining scores
- **Self-care slip**: Sleep/exercise sub-scores at 1-2 for 3+ days
- **Social overload**: Social score high but Energy/Emotional dropping — marathon pattern
- **Recovery needed**: Flag empty calendar slots as recovery opportunities after low-score days
