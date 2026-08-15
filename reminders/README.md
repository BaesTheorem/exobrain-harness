# reminders/

Creates reminders in Apple Reminders, including **repeating** ones.

## Why this exists

The Reminders AppleScript dictionary has no recurrence properties:

```
$ sdef /System/Applications/Reminders.app | grep -iE 'recur|repeat|frequency'
$
```

So `osascript` can create a reminder, but only a one-shot one. Recurrence lives
in EventKit (`EKRecurrenceRule`), which needs a compiled binary. Hence the Swift.

## Usage

```bash
reminders/add-reminder "Title" [--list NAME] [--at HH:MM] \
    [--repeat daily|weekly|monthly|yearly|none] [--interval N] [--notes TEXT] [--force]
```

- `--list` defaults to `INBOX`; an unknown name prints the available lists.
- `--at` takes 24-hour `HH:MM`. If that time has already passed today, the first
  occurrence rolls to tomorrow.
- `--repeat` requires `--at`, otherwise the series would fire at midnight.
- `--interval` is the "every N" multiplier (`--repeat weekly --interval 2` is
  fortnightly).
- Without `--force`, an open reminder with the same title in the same list makes
  it a no-op that exits 0, so this is safe to re-run from a script.

Examples:

```bash
reminders/add-reminder "Check Luci's food bowl" --at 8:00 --repeat daily
reminders/add-reminder "Water the plants" --at 18:30 --repeat weekly --interval 2
reminders/add-reminder "Pick up prescription"          # no time, no repeat
```

`add-reminder` recompiles `mkreminder.swift` into `.build/` whenever the source
is newer, so just edit the Swift and re-run.

## Gotchas

- **An alarm is not implicit.** Setting `dueDateComponents` alone gives a
  reminder that shows a time but never notifies. The Reminders UI adds the alarm
  for you; EventKit does not, so the script attaches an `EKAlarm` explicitly.
- **TCC attaches to the calling process, not this binary.** Access is granted to
  whatever terminal or agent invoked it (Ghostty, the Console, launchd), so a
  fresh caller may prompt or silently fail the first time. `DENIED` on stderr
  with exit 2 means the caller needs Reminders in System Settings > Privacy &
  Security > Reminders.
- **Not the default task destination.** Alex's tasks live in Things 3 (see
  `/things3`). Reach for this only when he asks for Apple Reminders specifically,
  usually because he wants it on the watch or in a Siri flow.

## Things this created

- `Check Luci's food bowl` -- INBOX, daily at 8:00 AM, created 2026-08-14.
