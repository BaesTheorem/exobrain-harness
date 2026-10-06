# kc-civic

This tool syncs selected Kansas City, Missouri public meetings to Google Calendar. For each meeting in the next five days that has an agenda, it also writes a prep note: does the meeting take public comment, which agenda items are worth a remark, the research behind them, and a two-minute draft.

## Sources

| Source | Bodies | How it is read |
|---|---|---|
| [KCMO Legistar Web API](https://webapi.legistar.com/v1/kansascity/bodies) | City Council, Business Session, the three council committees, PIAC, City Plan Commission, Land Bank, Vision Zero Task Force, Board of Zoning Adjustment, Multi-Modal Transportation Commission | Plain HTTPS. No API key is necessary. The JSON contains raw control characters, so it is parsed with `strict=False`. |
| [EDC of Kansas City events](https://edckc.com/events/) | TIF Commission, PIEA, LCRA | The iCal feed, read through an off-screen Chrome because the site has a Cloudflare challenge |
| kcmo.gov body pages (`pages` in `config.json`) | City Plan Commission | The same browser lane. The page holds the docket link and the testimony rules. |

Change the body list in `config.json`. A Legistar `name` must match `EventBodyName`. Legistar posts a meeting only a small number of days before it occurs, so Thursday council sessions show up on the calendar during the week before.

## Expected-meeting holds

Bodies with a fixed cadence get a hold on the calendar before the city publishes the meeting. The `holds` block in `config.json` sets each cadence, which was measured from the 2026 Legistar history:

| Body | Hold | 2026 record |
|---|---|---|
| City Council | Thursday 2:00 PM | 29 of 29 at that time; it skips approximately one week in four |
| The three council committees | Tuesday 9:00, 10:30, 1:30 | 26 of 26, 26 of 33, 27 of 29 |
| City Plan Commission | 1st and 3rd Wednesday, 9:00 AM | 18 of 19 |
| Board of Zoning Adjustment | 2nd and 4th Wednesday, 9:00 AM | 17 of 17 |
| Land Bank Board | 3rd Wednesday, 11:00 AM | 7 of 11 |
| Multi-Modal Transportation Commission | 3rd Thursday, 10:00 AM | every month since June |

A hold has the title suffix `(expected)`. When the city publishes the meeting for that body and date, the sync patches the same calendar entry with the official details, so any RSVP or reminder on it stays. If the meeting is not published by 4 hours before the hold, the sync deletes the hold. `hold_skip_dates` removes holiday weeks. Business Session, PIAC and Vision Zero have no regular cadence, so they get no holds. The EDC boards publish months ahead and do not need holds.

## Commands

```
bin/kc-civic list [--force-edc] [--no-holds]   # what the next sync writes
bin/kc-civic sync [--dry-run] [--no-prep] [--no-edc] [--force-edc] [--no-holds]
bin/kc-civic prep KEY [--force]     # one meeting, for example legistar-19540
bin/kc-civic auth-calendar          # one-time consent; then --code '<redirected URL>'
bin/kc-civic status
```

## How a pass runs

1. Get the Legistar meetings for the next 60 days. The EDC feed is read at most one time in 20 hours. Between those reads, the tool uses a cached copy.
2. Make or update one calendar entry for each meeting. The dedup key is `extendedProperties.private.kccivicId`, so a meeting that moves is updated in place. If a meeting is removed from Legistar, its calendar title gets the `CANCELLED:` prefix.
3. Prep: when a meeting starts in the next `prep_lead_days` days and has an agenda, `prep.py` builds a packet in `data/packets/`. The packet holds the agenda text, every attachment as text, and snapshots of the walled pages. Then a headless Claude (Fable first, Opus fallback) reads the packet, does research on primary sources, and writes the note to `~/Exobrain/Areas/Contribution & Impact/KC Civic/Meeting Prep/`. When the city republishes an agenda, the tool preps the meeting again, but only if the meeting is more than 12 hours away.
4. The calendar entry gets the prep note link and the verdict (`speak`, `written-comment`, `watch`, or `skip`).
5. One digest notification for each pass (banner and Discord), and only when something new occurred.

launchd runs it at 06:30, 12:30 and 18:30 (`com.exobrain.kc-civic.plist`). The browser work occurs only on the first pass of the day, so the off-screen Chrome runs while nobody uses the Mac.

## Security

Agenda text, attachments and web pages are third-party data. The prep run has no shell and no MCP servers. It runs with `MIST_UNATTENDED=1`, so the guard hook applies, and its prompt starts with the harness UNTRUSTED preamble. The calendar token has the `calendar.events` scope only.

## Files

- `config.json`: the bodies, windows, and calendar color.
- `prep-prompt.md`: the instructions for the prep run.
- `data/` (gitignored): the state, the packets, and `lens.md`, which is the personal policy lens used to rank agenda items. See `data/README.md`.
- `secrets/` (gitignored): the calendar token. See `secrets/README.md`.

## Install

```
cp kc-civic/com.exobrain.kc-civic.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.kc-civic.plist
```
