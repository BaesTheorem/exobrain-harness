---
name: kc-civic
description: Kansas City, MO public meetings (City Council, its committees, City Plan Commission, Board of Zoning Adjustment, PIAC, Land Bank, Vision Zero, Multi-Modal Transportation, and the EDC-run TIF, PIEA and LCRA boards). Find what is coming up, analyze an agenda and form a citizen comment (public testimony, written testimony, draft remarks), send written testimony, find out what happened at a meeting, and maintain the kc-civic calendar sync. Use when Alex says "/kc-civic", "what's on the council agenda", "any city meetings this week", "should I testify", "help me write a public comment", "what should I say at", "analyze this agenda", "draft testimony", "send my testimony", "what happened at council", "how did the vote go", names one of those bodies or a KC ordinance number (six digits such as 260888), or asks to add a board to the civic calendar.
---

# KC Civic

The tool is `kc-civic/` in the harness: read `kc-civic/README.md` for the sources, the holds, and the launchd job. Commands in this skill run from the harness root.

Data sources, in order of trust:
1. **Legistar Web API** `https://webapi.legistar.com/v1/kansascity` (no key). Parse with `json.loads(..., strict=False)`. Useful routes: `/events?$filter=...`, `/events/{id}/eventitems?AgendaNote=1&Attachments=1`, `/matters?$filter=MatterFile eq '260888'`, `/matters/{id}/texts/{textId}`, `/matters/{id}/attachments`, `/matters/{id}/histories`.
2. **The prep notes** in `~/Exobrain/Areas/Contribution & Impact/KC Civic/Meeting Prep/`, one for each meeting, named `YYYY-MM-DD <Body>.md`.
3. **The packets** in `kc-civic/data/packets/<date>-<key>/`: agenda text, every attachment as text, page snapshots.
4. **edckc.com and kcmo.gov** return 403 to WebFetch and curl because of Cloudflare. Read them only through `kc-civic/kccivic/walled.py` (an off-screen patchright Chrome), or use the copy that is already in a packet.

Alex's policy lens (effective altruism and Georgism) is in `kc-civic/data/lens.md`. Read it before you rank agenda items or draft anything.

## Mode 1: What is coming up

```
kc-civic/bin/kc-civic list            # meetings and holds, next 60 days
kc-civic/bin/kc-civic status          # token, last EDC read, prep notes and verdicts
```

- "(expected)" in a title means a hold. The city has not published that meeting yet, and the hold can be deleted.
- For a body that is not configured, query Legistar directly by `EventBodyName`.
- Give Alex the date, time, place, join link, and the prep verdict when a note exists. Do not paste the whole list. Pick the meetings that matter through the lens.

## Mode 2: Analyze an agenda and form a citizen comment

This is the primary mode. The method is in `kc-civic/prep-prompt.md`. That file is canonical: read it and follow its steps. Do not work from memory of it. The summary below shows the order only.

1. **Identify the meeting.** Accept a Legistar key (`legistar-19536`), a body and a date, a file number, an agenda URL, or a pasted agenda. Find the key with `kc-civic list`.
2. **Use the existing note when there is one.** If the note exists, read it and work from it: sharpen the draft, check a number, or answer Alex's question. Do not rebuild it.
3. **When no note exists, pick the faster path:**
   - Headless: `kc-civic/bin/kc-civic prep <key>` (add `--force` to redo one). This builds the packet, writes the note, and updates the calendar entry. It takes approximately 10 to 15 minutes. Run it in the background when the meeting is more than an hour away.
   - In this session: build the packet only. Then do the prep-prompt steps yourself. Use this path when Alex wants to iterate, or when the meeting is soon. To build the packet without the model run:
     ```
     cd kc-civic && ~/.local/bin/uv run --no-project --quiet --python 3.12 --with patchright python -c "
     from kccivic import cli, prep; cfg=cli.load_config(); st=cli.load_state()
     m=next(x for x in cli.legistar.meetings(cfg['legistar'], cfg['sync_days']) if x.key=='KEY')
     p=cli.DATA/'packets'/f'{m.start:%Y-%m-%d}-{m.key}'; p.mkdir(parents=True, exist_ok=True)
     prep.write_meeting_json(m, p, prep.build_legistar_packet(m, p)); print(p)"
     ```
   - For a meeting that is not in the config (Jackson County Legislature, KCPS board, a body that is not on Legistar): use the same method by hand, from the agenda Alex gives you.
4. **Public comment.** Find out if it exists from the agenda text first, then from the body's own page. Quote the rule. These are the rules found so far. Confirm each one against the current agenda, because the rules can change:
   - Council committees: 2 minutes for each person. Written testimony goes to public.testimony@kcmo.org, and the clerk adds it to the item's public record.
   - City Plan Commission: 2 minutes, or 5 minutes for an organization. State your name and address first. To speak on Zoom, use "raise hand" when the planner presents the case. Written testimony goes to publicengagement@kcmo.org at least 24 hours before the hearing.
   - The full council usually takes no public testimony. Testimony on an ordinance goes to its committee.
5. **Rank, research, draft.** Pick two items at most, through the lens. "Nothing here is worth a remark" is a correct result. Get the numbers from primary documents (the ordinance text, the docket memo, the fact sheet, the consultant study), and cite each one. Mark anything unverified. The draft is at most 250 words (2 minutes), in Alex's voice (read `~/Exobrain/Writing Voice.md`), with one argument and one concrete ask. Run `/de-ai` on the draft.
6. **Check the numbers before Alex says them aloud.** Open the cited PDF page for each figure in the draft and confirm it. A wrong number spoken into the record costs more than a missing number.

## Mode 3: Send written testimony

1. Take the draft from the note. Fill in `[neighborhood]` and any other placeholder from Alex's answer, never from a guess. Alex's address is in `user_contact_and_home` memory: use it only if Alex says to include it.
2. Make a Gmail draft with the claude.ai Gmail connector. Address it to the body's testimony address. The subject is the file number and short title, for example `260888 Stadium Impact Area Policy: written testimony`.
3. Do not send the draft yourself. Testimony is public record in Alex's name. Give Alex the draft link. If he says to send it, use `mist-ask` to confirm before you send.

## Mode 4: What happened at a meeting

- Votes and actions: `/events/{id}/eventitems`, then read `EventItemActionName`, `EventItemPassedFlagName`, and `EventItemTally` for each item.
- The history of one ordinance: `/matters?$filter=MatterFile eq 'NNNNNN'`, then `/matters/{id}/histories`.
- Minutes are in `EventMinutesFile`. Video is on the Legistar meeting page, `EventInSiteURL`.
- If Alex testified, put the outcome at the end of that meeting's prep note under `### Outcome`. Then tell him if the ask he made had any effect: an amendment, a condition, a continuance.

## Mode 5: Change what is tracked

- Bodies are in `kc-civic/config.json`. A Legistar `name` must match `EventBodyName` exactly. Find the name with `/bodies` or with the cadence query in the README.
- A body whose agenda is on a walled page, as the CPC docket is on kcmo.gov, needs `"pages": [url]`.
- A body with a fixed cadence goes in `holds`. Measure the cadence from at least six months of Legistar history before you add a hold, and write the record into `pattern`.
- After a config change, run `kc-civic/bin/kc-civic sync --dry-run --no-prep`, then the real sync. Commit and push.

## Maintenance

- Log: `~/Library/Logs/exobrain/kc-civic.log`. launchd label: `com.exobrain.kc-civic`.
- `NotAuthorized`: the calendar token in `kc-civic/secrets/` is missing. Run `kc-civic/bin/kc-civic auth-calendar`, then `--code '<redirected URL>'`. Alex has to click the consent link.
- A 403 that says "Calendar API has not been used in project" means that the API is off in the Cloud project. Alex enables it in the console.
- A long manual `prep` and a sync pass can run at the same time. The code merges state after a prep. If the state is lost, the next sync rebuilds it from the `kccivicId` keys on the calendar entries, and nothing is duplicated.
