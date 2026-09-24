---
name: exercise
description: "Read Alex's resistance-training log from the Exercise Log iPhone app: sets, reps, weekly targets, progressions, and rest per exercise. Use when Alex mentions the exercise log, workouts, lifting, the gym, sets or reps, 'did I train this week', 'how many sets', a progression or weight for an exercise, or when a briefing, winddown, or weekly review wants training data."
metadata:
  repo: "/Users/alexhedtke/Documents/exercise-log (public: BaesTheorem/exercise-log)"
  app: "Exercise Log on Alex's iPhone (bundle com.alexhedtke.exerciselog)"
---

# /exercise

The iPhone app is the only writer. It mirrors one file, `exercise-log.json`,
into a folder Alex picked in Files (iCloud Drive or Google Drive), and that
folder syncs to this Mac. Read it through the CLI, never by hand:

```
~/Documents/exercise-log/bin/exercise-log status          # this week, file age
~/Documents/exercise-log/bin/exercise-log weeks -n 8      # sets done vs target per week
~/Documents/exercise-log/bin/exercise-log week YYYY-MM-DD # one page
~/Documents/exercise-log/bin/exercise-log markdown        # paste-ready table
~/Documents/exercise-log/bin/exercise-log vault           # project weeks into the vault
```

The README in the repo documents the JSON schema. Ids join `exercises` to
`days[].entries`; `weeklySets` is a per-week target, not per day; a `done`
flag is the paper strikethrough.

## Where the file is

Resolution order: `--file`, `$EXERCISE_LOG_JSON`, then
`~/Library/Mobile Documents/com~apple~CloudDocs/Exercise Log/`, then
`~/My Drive/Exercise Log/`. "No exercise-log.json found" means Alex has not
picked a sync folder in the app yet (Settings > Choose sync folder), or picked
one outside those two paths: ask which folder, then point `EXERCISE_LOG_JSON`
at it. An `.exercise-log.json.icloud` placeholder means iCloud has not
hydrated it on this Mac; opening the folder in Finder pulls it.

## Freshness

`status` prints the file's `updatedAt` age. Treat a stale file as "not synced
yet", not as "did not train": the app pushes a couple of seconds after each
edit, but only while it has been opened since. See
[[feedback_launchd_ok_is_not_data_freshness]] for the general rule.

## Vault projection

`vault` writes `Areas/Health & Fitness/Exercise Log/Week of YYYY-MM-DD.md`
with frontmatter (`week_of`, `days_trained`, `sets_done`, `sets_target`,
`dates`) and the week as a markdown table. It is idempotent. The older
`Areas/Health & Fitness/Exercise Log.md` note is the Supernote archive
(May 2023 to March 2026) and stays as history.

## Briefings

For the morning briefing or winddown, one line is enough: sets done vs target
this week and days trained, from `weeks -n 1`. Flag a week with 0 days
trained by Thursday.
