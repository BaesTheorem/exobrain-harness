---
name: process-transcript
description: Process Plaud Note transcripts from the Plaud/ folder in the Obsidian vault. Extracts tasks, events, notes, and insights, routing them to Things 3, Google Calendar, and the daily note. Use when the user mentions transcripts, recordings, Plaud, conversations to process, "I just recorded something", "any new recordings", "process my notes", "what did I talk about", or when triggered by a scheduled task.
---

# Process Transcript

## Steps

### 0. Canonical name mapping
Plaud transcripts frequently mis-transcribe names. Before processing any transcript, apply these corrections throughout the text:

Plaud transcripts frequently mis-transcribe names. Before processing any transcript, check the People/ folder in the Obsidian vault for canonical spellings. Common Plaud mis-transcriptions include phonetically similar substitutions (e.g., "Linda" for a name ending in "-inda", "Bryce" for "[Friend]").

To build the correction table:
1. Glob `/Users/alexhedtke/Documents/Exobrain/Areas/Relationships & Community/People/*.md`
2. Use those filenames as the canonical names
3. Apply phonetic matching when Plaud produces a name that's close but not exact

Also normalize variations of the same person to one canonical name for People/ notes (e.g., don't create both a nickname file and a full name file). When in doubt, use the fullest version of the name that exists in the People/ folder. Always check for existing People/ notes with similar names before creating a new one.

### 1. Find unprocessed transcripts
- List all `.txt` files in `/Users/alexhedtke/My Drive/Plaud/`
- Read `/Users/alexhedtke/Documents/Exobrain harness/processing-log.json`
- Identify files not yet in the log. **Filename matching alone is insufficient** — the same recording can appear under different filenames (e.g., `create_tim ... .txt` renamed to `2026-04-08_0955_...txt`). A file is considered already processed if ANY of the following match an existing log entry:
  1. The filename matches an `id` or `filename` field in the log
  2. The `create_time` in the file's JSON matches (within a few minutes) the date+time encoded in a log entry's `id`
  3. The `title` in the file's JSON closely matches an existing log entry's `title` field on the same date
- If no unprocessed files, notify and stop

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

Use `create_time` for the recording date (convert UTC → Central Time). Use `title` for the transcript heading. Use `summary` (speaker-labeled) as the primary content to analyze; fall back to `transcript` (raw timestamped) for additional detail.

Extract these categories from the transcript content:

**Tasks**: Action items, to-dos, commitments, follow-ups, things to buy/research/contact
**Events**: Meetings, appointments, deadlines with dates/times
**Notes**: Ideas, reflections, information worth remembering, key decisions
**Insights**: Connections to existing knowledge, patterns, recommendations

### 3. Route tasks to Things 3
For each task:
1. **Sanitize text**: Ensure task titles and notes are clean plaintext — no URL encoding (`+` for spaces, `%20`, etc.). If the transcript JSON contains URL-encoded strings, decode them first.
2. Use `search_todos` to check if a similar task already exists
3. If exists → `update_todo` to append new context as a note
4. If new → `add_todo` to Inbox (or to a specific project if clearly matching)
5. After creating each task, note its UUID so you can include a `things:///show?id=UUID` deep link in the daily note

### 4. Route events
- **Clear date/time** → `gcal_create_event` directly
- **Ambiguous** → `add_todo` to Things 3 Inbox as "Review: [event description]" with details in notes

### 5. Write to daily note
Determine the **transcript's recording date** from the `create_time` field in the JSON. Each transcript file is JSON with a structure like `{"create_time": "2026-03-25T12:19:59Z", "summary": "...", "title": "...", "transcript": "..."}`. Parse `create_time` and convert to the daily note filename format (e.g., `Wednesday, March 25th, 2026`). Convert from UTC to America/Chicago (Central Time) before determining the date — a recording at `2026-03-26T04:30:00Z` is March 25th local time.

**Always write to the recording date's daily note, NOT today's daily note.** A transcript from March 25th processed on March 27th goes in the March 25th note.

Read the existing daily note for that date. If it doesn't exist, create it with:
```
<< [[Yesterday Name|Yesterday]] | [[Tomorrow Name|Tomorrow]] >>
```

Append a section for the transcript using this compact format. **Each transcript is a standalone H3 — never nest transcripts under a parent heading, never use H2 for transcript entries, and never create a "### Transcripts" or "### Transcript Processing" group heading.** Use bold text for sub-sections, no markdown headings below the H3:
```markdown
### 📼 Transcript: [filename or topic]
**Source**: [file info and timestamp]
**Speaker(s)**: [who was involved]

**Summary** — [2-3 sentence overview of the conversation/recording]

**Key points**
- [main subjects, decisions, notable details as bullets]

**Open questions**
- [unresolved items that came up]

**Tasks created**
- [ ] [Task name](things:///show?id=UUID) — [brief context]

**Recommendations** — [your suggestions for follow-ups, efficiency, connections to [[existing notes]]]
```

Keep it tight — aim for one screen of content per transcript. Merge key topics, people, and connections inline rather than giving each its own section.

Before adding wikilinks, check that the target note exists by listing files in the vault.

### 6. Update People/ notes
For every person mentioned in the transcript:
1. Check if `/Users/alexhedtke/Documents/Exobrain/Areas/Relationships & Community/People/[Name].md` exists
2. If it doesn't exist, create it:
   ```markdown
   ## Context
   - **First mentioned**: [today's date] — [brief context from transcript]
   ## Mentions
   - [[Daily note link]] — [1-line context of interaction]
   ## Follow-ups
   - [any pending follow-ups from the transcript]
   ```
3. If it already exists, append to the `## Mentions` section:
   ```
   - [[Daily note link]] — [1-line context of interaction]
   ```
   And update `## Follow-ups` if new follow-ups were identified.
4. Also add any new factual information about the person (role, company, interests, relationships, contact info, opinions, life events) to their `## Context` section. The People note should accumulate knowledge over time — every transcript is a chance to enrich it.
5. **Personality & social dynamics**: Follow the `/crm` skill's mode 9 (Continuous Integration) protocol — enrich `## Context`, `## Connections`, and `## Personality & Dynamics` sections with observations from the transcript. Use specific examples, not vague labels.
5. Use `[[wikilinks]]` to link People notes from the daily note Network table.
6. Skip generic/unknown speakers (e.g., "Speaker 1", "unknown") — only create notes for identifiable people.

### 7. Log job-related content to job hub
If the transcript contains any job search-related content — job leads, companies mentioned, networking contacts for job hunting, interview prep, upskilling discussion, application strategy — append a dated log entry to `/Users/alexhedtke/Documents/Exobrain/Projects/Get new job.md` under `## Job Search Log`. Use the appropriate type (Networking, Research, Upskilling, Interview, etc.) and include the key details.

### 8. Flag proactive observations
- If anything sounds like procrastination on a priority item, note it
- If something could be done more efficiently, suggest it
- If a task relates to current priorities (from Dashboard.md), highlight the connection

### 9. Rename transcript file
After processing, rename the transcript file to include the recording date/time for easy searching. Parse `create_time` from the JSON (convert UTC → Central Time) and the `title` field, then rename:

```
create_tim ...  (N).txt  →  2026-03-25_1219_Voice-Memo-Topic-Description.txt
```

Format: `YYYY-MM-DD_HHmm_[sanitized-title].txt` where:
- Date and time come from `create_time` (converted to Central Time)
- Title comes from the `title` field with the date prefix stripped (e.g., `03-25 Voice Memo: Topic Description` → `Voice-Memo-Topic-Description`)
- Replace spaces and special characters with hyphens, collapse multiple hyphens

Use `mv` to rename in place within `/Users/alexhedtke/My Drive/Plaud/` (files stay in Google Drive). Update the processing log entry (step 10) to use the **new** filename as the `id`.

### 10. Update processing log
Append to `processing-log.json`:
```json
{
  "id": "filename.md",
  "processedAt": "ISO-8601 timestamp",
  "source": "plaud",
  "itemsCreated": { "tasks": N, "notes": N, "events": N }
}
```
