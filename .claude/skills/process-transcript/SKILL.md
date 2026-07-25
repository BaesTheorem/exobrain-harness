---
name: process-transcript
description: Process Plaud Note transcripts and work with the Plaud cloud library. Part A is the vault pipeline -- extracts tasks, events, notes, and insights from transcript files, routing them to Things 3, Google Calendar, and the daily note. Part B is the Plaud MCP server -- browse, find, read, digest, draft follow-ups from, and export recordings. Use when the user mentions transcripts, recordings, Plaud, conversations to process, "I just recorded something", "any new recordings", "process my notes", "what did I talk about", "list my recordings", "find the meeting about X", "the call from Monday", "show the transcript", "summarize this recording", "what were the action items", "weekly digest of my meetings", "draft a follow-up from that call", or when triggered by a scheduled task.
---

# Process Transcript

Two halves. **Part A** is the file-based vault pipeline that runs on `.txt` files synced into `/Users/alexhedtke/My Drive/Plaud/` -- this is what the scheduled watcher triggers. **Part B** is the Plaud cloud API over MCP, for reaching recordings that have not landed as files or that Alex wants to query directly.

# Part A: Vault pipeline

## Steps

### 0. Canonical name mapping
Plaud transcripts frequently mis-transcribe names. Before processing any transcript, apply these corrections throughout the text:

Before processing any transcript, check the People/ folder in the Obsidian vault for canonical spellings. Common Plaud mis-transcriptions include phonetically similar substitutions (e.g., "Linda" for a name ending in "-inda", "Bryce" for "[Friend]").

To build the correction table:
1. Glob `/Users/alexhedtke/Exobrain/Areas/Relationships & Community/People/*.md`
2. Use those filenames as the canonical names
3. Apply phonetic matching when Plaud produces a name that's close but not exact

Also normalize variations of the same person to one canonical name for People/ notes (e.g., don't create both a nickname file and a full name file). When in doubt, use the fullest version of the name that exists in the People/ folder. Always check for existing People/ notes with similar names before creating a new one.

### 1. Find unprocessed transcripts
- List all `.txt` files in `/Users/alexhedtke/My Drive/Plaud/`
- Read `/Users/alexhedtke/Documents/Exobrain harness/processing-log.json`
- Identify files not yet in the log. **Dedup by content, not just filename.** Two failure modes to guard against:
  1. **Filename collision** -- Plaud reuses the placeholder name `create_tim ... .txt` (and `... (N).txt` variants) for every unrenamed recording, so a new recording can have the same filename as a previously-processed file. **Treat any filename starting with `create_tim` as unprocessed by filename alone -- always open the JSON and dedup by `create_time`.**
  2. **Filename rename** -- the same recording can appear under different filenames (e.g., `create_tim ... .txt` renamed to `2026-04-08_0955_...txt`).
- A file is considered already processed if ANY of the following match an existing log entry:
  1. The filename matches an `id` or `filename` field in the log **AND** the filename does not start with `create_tim`
  2. The `create_time` in the file's JSON matches (within a few minutes) the `create_time` recorded in a log entry, or the date+time encoded in a log entry's `id` (e.g., `2026-04-08_0955_...`)
  3. The `title` in the file's JSON closely matches an existing log entry's `title` field on the same date
- If no unprocessed files, stop silently (no notification)

### 2. For each unprocessed transcript, read and analyze

Each transcript file is **JSON** with this structure:
```json
{
  "create_time": "2026-03-25T12:19:59Z",
  "summary": "# Transcript\n**Speaker:** ...",
  "title": "03-25 Voice Memo: Topic Description",
  "transcript": "00:00:01\nFirst line of speech..."
}
```

Use `create_time` for the recording date and time. **Critical timezone gotcha**: Plaud writes the recording's *local* wall-clock time into `create_time` but appends a `Z` (UTC) suffix anyway. Do **not** apply a UTC→local conversion -- strip the `Z` and treat the timestamp as naive local time in the **current system timezone** (read it from `date +%Z` or Python's `datetime.now().astimezone().tzinfo`; for Alex's normal location this is `America/Chicago`). Applying a UTC offset incorrectly shifts the displayed time by 5 hours and flips the date for any recording made between midnight and 5 AM local. Use `title` for the transcript heading. Use `summary` (speaker-labeled) as the primary content to analyze; fall back to `transcript` (raw timestamped) for additional detail.

Extract these categories from the transcript content:

**Tasks**: Action items, to-dos, commitments, follow-ups, things to buy/research/contact
**Events**: Meetings, appointments, deadlines with dates/times
**Notes**: Ideas, reflections, information worth remembering, key decisions
**Insights**: Connections to existing knowledge, patterns, recommendations

### 2b. TTRPG session handoff (check before routing)
Before routing anything, decide whether this transcript is a **tabletop RPG session recording** (a D&D/TTRPG game at the table, not just a conversation that mentions D&D). Signals: in-character dialogue, dice rolls, initiative/combat, a DM narrating scenes, known player/character names in a play context, references to "the party", "the session", spells/abilities being used.

If it is a session recording, **stop the normal pipeline here and hand off to the `TTRPG-campaign-manager` skill (Mode 2: Session Recap)**. Do not run steps 3-8 on session content:
- The recap belongs in the campaign folder as `Session [N] recap.md`, not the daily note.
- Do NOT route session beats to Things 3 or Google Calendar, and do NOT enrich People/ notes from in-character material.
- The **only** exception is real-life action items Alex says out loud during the session (e.g., "remind me to text [player] about next week", "I need to buy more dice") -- capture those as tasks/events per steps 3-4, but leave everything else to the recap.
- The campaign-manager skill owns the processing-log entry for the session (source `"plaud"`, flagged as a TTRPG session), so skip step 10 here for it.

If it's merely a conversation that *references* a TTRPG (e.g., planning a session, chatting about the campaign), keep processing normally -- the Media-extraction rule in step 7b still applies.

### 3. Route tasks to Things 3
For each task:
1. **Sanitize text**: Ensure task titles and notes are clean plaintext -- no URL encoding (`+` for spaces, `%20`, etc.). If the transcript JSON contains URL-encoded strings, decode them first.
2. Use `search_todos` to check if a similar task already exists
3. If exists → `update_todo` to append new context as a note
4. If new → `add_todo` to Inbox (or to a specific project if clearly matching)
5. After creating each task, note its UUID so you can include a `things:///show?id=UUID` deep link in the daily note

### 4. Route events
- **Clear date/time** → `gcal_create_event` directly
- **Ambiguous** → `add_todo` to Things 3 Inbox as "Review: [event description]" with details in notes

### 5. Write to daily note
Determine the **transcript's recording date** from the `create_time` field in the JSON. Each transcript file is JSON with a structure like `{"create_time": "2026-03-25T12:19:59Z", "summary": "...", "title": "...", "transcript": "..."}`. Parse `create_time` as **naive local time in the current system timezone** (see the timezone gotcha in step 2) -- strip the `Z`, do not apply any UTC offset -- then format to the daily note filename style (e.g., `Wednesday, March 25th, 2026`).

**Always write to the recording date's daily note, NOT today's daily note.** A transcript from March 25th processed on March 27th goes in the March 25th note.

Read the existing daily note for that date. If it doesn't exist, create it with:
```
<< [[Yesterday Name|Yesterday]] | [[Tomorrow Name|Tomorrow]] >>
```

Append a section for the transcript using this compact format. **Each transcript is a standalone H3 -- never nest transcripts under a parent heading, never use H2 for transcript entries, and never create a "### Transcripts" or "### Transcript Processing" group heading.** Use bold text for sub-sections, no markdown headings below the H3:
```markdown
### 📼 Transcript: [filename or topic]
**Source**: [file info and timestamp]
**Speaker(s)**: [who was involved]

**Summary** -- [2-3 sentence overview of the conversation/recording]

**Key points**
- [main subjects, decisions, notable details as bullets]

**Open questions**
- [unresolved items that came up]

**Tasks created**
- [ ] [Task name](things:///show?id=UUID) -- [brief context]

**Recommendations** -- [your suggestions for follow-ups, efficiency, connections to [[existing notes]]]
```

Keep it tight -- aim for one screen of content per transcript. Merge key topics, people, and connections inline rather than giving each its own section.

Before adding wikilinks, check that the target note exists by listing files in the vault.

### 6. Update People/ notes
For every person mentioned in the transcript:
1. Check if `/Users/alexhedtke/Exobrain/Areas/Relationships & Community/People/[Name].md` exists
2. If it doesn't exist, create it:
   ```markdown
   ## Context
   - **First mentioned**: [today's date] -- [brief context from transcript]
   ## Mentions
   - [[Daily note link]] -- [1-line context of interaction]
   ## Follow-ups
   - [any pending follow-ups from the transcript]
   ```
3. If it already exists, append to the `## Mentions` section:
   ```
   - [[Daily note link]] -- [1-line context of interaction]
   ```
   And update `## Follow-ups` if new follow-ups were identified.
4. Also add any new factual information about the person (role, company, interests, relationships, contact info, opinions, life events) to their `## Context` section. The People note should accumulate knowledge over time -- every transcript is a chance to enrich it.
5. **Personality & social dynamics**: Follow the `/crm` skill's mode 9 (Continuous Integration) protocol -- enrich `## Context`, `## Connections`, and `## Personality & Dynamics` sections with observations from the transcript. Use specific examples, not vague labels.
5. Use `[[wikilinks]]` to link People notes from the daily note Network table.
6. Skip generic/unknown speakers (e.g., "Speaker 1", "unknown") -- only create notes for identifiable people.

### 7. Log job-related content to job hub
If the transcript contains any job search-related content -- job leads, companies mentioned, networking contacts for job hunting, interview prep, upskilling discussion, application strategy -- append a dated log entry to `/Users/alexhedtke/Exobrain/Projects/Get new job.md` under `## Job Search Log`. Use the appropriate type (Networking, Research, Upskilling, Interview, etc.) and include the key details.

### 7b. Media extraction

Whenever the transcript mentions a movie, show, anime, book, podcast, article, game, TTRPG, or other media, create or update `/Users/alexhedtke/Exobrain/Media/[Title].md`. Always Glob for an existing note first; if found, append to its body -- don't duplicate.

Frontmatter:
```yaml
---
media_type: movie | tv | anime | book | music | game | article
recommended_by: "Name"
status: false              # true = consumed
group_watch: true | false
date_added: YYYY-MM-DD
author: "Author Name"      # books only
word_count: 80000          # books only, approximate
---
**Context**: [how it came up]
```

Mention in the daily note entry: "Added X media items to [[Media.base|Media]]". The `Media.base` view auto-renders all Media/ notes. This same schema applies to media discovered via Supernote, iMessage, Discord, or any other input pipeline.

### 8. Flag proactive observations
- If anything sounds like procrastination on a priority item, note it
- If something could be done more efficiently, suggest it
- If a task relates to current priorities (from Dashboard.md), highlight the connection

### 9. Rename transcript file
After processing, rename the transcript file to include the recording date/time for easy searching. Parse `create_time` from the JSON as **naive local time in the current system timezone** (see step 2 -- strip the `Z`, do not apply a UTC offset) and the `title` field, then rename:

```
create_tim ...  (N).txt  →  2026-03-25_1219_Voice-Memo-Topic-Description.txt
```

Format: `YYYY-MM-DD_HHmm_[sanitized-title].txt` where:
- Date and time come from `create_time` (read as naive local time -- see step 2)
- Title comes from the `title` field with the date prefix stripped (e.g., `03-25 Voice Memo: Topic Description` → `Voice-Memo-Topic-Description`)
- Replace spaces and special characters with hyphens, collapse multiple hyphens

Use `mv` to rename in place within `/Users/alexhedtke/My Drive/Plaud/` (files stay in Google Drive). Update the processing log entry (step 10) to use the **new** filename as the `id`.

### 10. Update processing log
Append to `processing-log.json`. Always include `create_time` so future dedup is content-based, not filename-based:
```json
{
  "id": "filename.md",
  "processedAt": "ISO-8601 timestamp",
  "source": "plaud",
  "create_time": "2026-04-27T13:07:28Z",
  "title": "transcript title from JSON",
  "itemsCreated": { "tasks": N, "notes": N, "events": N }
}
```

---

# Part B: Plaud cloud API (MCP)

For reaching the Plaud library directly instead of the synced files. If the user's goal is "process my new recordings into the vault", that is Part A. If it is "find/read/summarize a recording" or "roll up my meetings", it is Part B.

## Core (read before any tool call)

### Authentication

- Plaud MCP uses OAuth. MCP tokens live in `~/.plaud/tokens-mcp.json` and refresh automatically. The terminal CLI uses `~/.plaud/tokens.json` separately.
- On an auth error (message contains `Not authenticated` or `401`), call `login` and wait for the browser callback. Do **not** retry the original call until login returns success.
- Never ask the user to paste tokens. The `login` tool handles the whole flow.

### Tool inventory

| Tool | Purpose |
|---|---|
| `login` | Open browser for OAuth; blocks until callback or 2-min timeout |
| `logout` | Revoke and clear tokens |
| `get_current_user` | Verify who is signed in |
| `list_files` | Browse, paginate, filter recordings (`query`, `date_from`, `date_to`) |
| `get_file` | Full record incl. `presigned_url`, `source_list`, `note_list` |
| `get_note` | AI-generated summary and action items |
| `get_transcript` | Timestamped transcript with speaker labels |

### Error semantics

| Pattern in error | Meaning | Action |
|---|---|---|
| `401` / `Not authenticated` | Token missing or expired | Call `login`, then retry |
| `404` | File ID does not exist | Tell the user the ID is wrong; do not retry |
| `500` | Backend error (often an invalid ID too) | Retry once; if still 500, treat as NOT_FOUND |
| `fetch failed` / `ECONNREFUSED` | Network problem | Abort; tell user to check connection |

### Data model

- `duration` is **milliseconds**.
- `source_list`: items with `data_type === "transaction"` hold transcript segments (JSON-encoded string in `data_content`).
- `note_list`: items with `data_type === "auto_sum_note"` hold the AI summary (Markdown in `data_content`).
- `presigned_url` expires in 24 hours; re-fetch with `get_file` if stale.
- **`create_time` is local wall-clock time despite its `Z` suffix.** Same gotcha as Part A step 2. Never apply a UTC offset.

### Output conventions

- Always show name, date, duration, and file ID. Users need the ID for follow-ups.
- Durations human-readable: `23s`, `5m23s`, `1h05m`. Raw milliseconds are for logs only.
- Dates as `YYYY-MM-DD` in local time.
- Transcripts: preserve `[MM:SS - MM:SS] Speaker: content` exactly. Do not reformat timestamps.
- Summaries: render the Markdown directly; quote verbatim unless asked to paraphrase.

### Universal anti-patterns

- Never call `get_transcript` speculatively. It is by far the largest payload.
- Never fetch every page eagerly. Pagination is lazy.
- Dedup by `create_time` + title, never by filename (see Part A step 1 for why).
- Split recordings over ~3 hours before deep processing.

## Mode 1: Browse

For "what recordings do I have", "show my recent recordings", "next page".

1. `list_files` with `page=1`, `page_size=20`. No filter params unless the phrasing matches Mode 2.
2. Present a compact table: **ID**, **NAME**, **DATE**, **DURATION**.
3. If fewer than `page_size` come back, say there is no next page.
4. "More" means increment `page` and call again.

Do not call `get_note` or `get_transcript` during a browse. That is Mode 3 and it burns tokens.

## Mode 2: Find

For "find the Weekly Sync", "the meeting from Monday", "the call about Q2".

The Plaud REST API ignores unknown params, so filtering is client-side. The MCP `list_files` tool accepts the three params below and paginates up to 5 pages for you.

1. **Elicit criteria if vague.** Need at least one of: a name keyword (partial is fine), a rough date or range, or (last resort) a duration range.
2. **Call `list_files`** with what you have:
   - `query=<keyword>`: case-insensitive substring match on `name`
   - `date_from=YYYY-MM-DD`, `date_to=YYYY-MM-DD`: inclusive window on `created_at`
   - Omit anything the user did not specify.
3. **Zero matches:** ask the user to broaden one axis.
4. **More than 10 matches:** return the top 10 by `created_at` desc and state the total.
5. **Never auto-load transcripts.** Present matches, wait for the user to pick, then go to Mode 3.

### Date interpretation

| Phrase | Filter |
|---|---|
| today / yesterday | both bounds = that day |
| this week | Monday of this week to today |
| last week | Monday to Sunday of last week |
| this month | 1st of this month to today |
| last month | 1st to last day of previous month |
| from Monday | `date_from` = most recent Monday, no `date_to` |

Resolve relative dates against the **current date** from conversation context, never the training cutoff.

## Mode 3: Read

For "show the transcript", "summarize this", "what was said", "get the audio", or a structured extraction. If no recording was named, use Mode 2 (by topic) or Mode 1 (by recency) first.

| User wants | Tool | Notes |
|---|---|---|
| Summary, TL;DR, action items | `get_note` | Markdown; usually enough. Try before `get_transcript` |
| Verbatim quotes, full dialogue | `get_transcript` | Timestamped, large |
| Audio download link | `get_file` then `presigned_url` | Expires in 24h; say so |
| Metadata + availability | `get_file` | Check `source_list` / `note_list` are populated before claiming content exists |

**Structured extraction.** If the user supplies a schema: `get_note` first (the summary usually already has the fields), only reach for `get_transcript` if a required field is missing, then return JSON matching their schema with missing fields `null` and a note on why. Common schemas: sales `{pain_points, follow_ups, deal_stage}`; clinical `{diagnoses, medications, next_appointment}`; project `{action_items, decisions, attendees}`.

## Mode 4: Digest

For "weekly report", "what meetings did I have this week", "recap of last quarter".

1. **Resolve the window** using the Mode 2 date table.
2. **List the corpus:** `list_files` with the date bounds. Cap at 50; if the window returns more, ask the user to narrow.
3. **Fetch notes in batch:** `get_note` per recording. No transcripts unless one specifically merits a deeper pull.
4. **Synthesize:** a one-line **headline** theme; **by recording** as `- name (date, duration) - one-sentence takeaway`; **recurring themes** appearing in 2 or more recordings; **open action items**, aggregated and deduplicated.
5. **Cite sources.** Every non-trivial claim references its recording by name (not raw ID unless asked).

Hard cap 50 `get_note` calls. Skip recordings with an empty `note_list` and list them at the end under "unsummarized". Do not invent action items that are not in the notes, and do not widen the window the user asked for.

## Mode 5: Follow-up

For "draft follow-up", "what were the action items", "turn this into a SOAP note", "write the recap".

1. **Identify the recording** (Mode 1 or 2 if not named).
2. **Fetch source:** `get_note` first. `get_transcript` only when the artifact needs verbatim quotes (legal memo) or speaker attribution (SOAP).
3. **Generate**, grounding every claim in the source. Never invent attendees, dates, decisions, or numbers.
4. **Present in chat**, then offer to refine or export.

**Templates**

- **Follow-up email:** To = attendees from notes. Subject `Follow-up - {name}, {date}`. Thanks plus one-line summary, 3 to 5 key-point bullets, numbered action items with owner and due date, close with "Let me know if I missed anything."
- **Thank-you email:** short, one paragraph, one concrete thing learned or appreciated.
- **Action-item list:** `- [ ] {owner}: {item} (due {date})`. Owner `?` if unclear. Never guess.
- **SOAP note:** Subjective (patient's words from transcript), Objective (observations, not inferred), Assessment (summary's diagnosis if present), Plan (action items, next appointment).
- **Meeting brief:** attendees, date, duration, decisions, risks, next steps.

Never invent recipients or due dates. Mark unknown dates `due: TBD`. This mode drafts only; sending is Mode 6.

If the artifact should also land in the vault (tasks to Things 3, a daily-note entry), switch to Part A's routing rules rather than reinventing them here.

## Mode 6: Export

For "save to Notion", "post to Slack", "send to webhook", "file this in HubSpot".

Plaud MCP exposes no push tool. This mode assumes another MCP or integration is present in the session (Notion, Slack, Gmail, a webhook tool).

1. **Confirm the payload:** raw summary, a Mode 5 artifact, or a transcript excerpt.
2. **Confirm the destination and identifier.** Plaud stores no destination credentials. Notion wants a page or database ID; Slack a channel name or ID; HubSpot/Salesforce a deal, contact, or company ID; Linear a team or project ID; Gmail the recipients; a webhook its full URL.
3. **Deliver** via the available tool.
4. **Report the delivery URL** (Notion page, Slack permalink, webhook status).

Never persist destination credentials in the conversation or in files. Never send to a default destination without confirming. Never alter artifact content during delivery; reformat for the target (Slack mrkdwn) without changing meaning.
