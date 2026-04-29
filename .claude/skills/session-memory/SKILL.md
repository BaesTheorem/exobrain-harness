---
name: session-memory
description: Cross-session continuity and context-aware data prioritization. Saves structured summaries at session end, loads context at session start to guide what data to pull and how deep to go. Runs automatically via startup hook (load) and CLAUDE.md instruction (save). Also use when the user says "save session", "what did we do last time", or "context".
---

# Session Memory

Two modes: **save** (end of session) and **load** (start of session). The startup hook handles load automatically. Save is triggered by Claude before ending a significant session.

## Storage

- **Directory**: `/Users/alexhedtke/Documents/Exobrain harness/.claude/session-memory/`
- **File formats**:
  - Per-session memory: `YYYY-MM-DD_HHMM.md` (e.g., `2026-04-07_1741.md`)
  - Delta memory (post-save activity in same session): `YYYY-MM-DD_HHMM_delta.md`
  - Daily digest (rolling cross-day summary, written by 11pm consolidator): `YYYY-MM-DD_DIGEST.md`
- **Retention**: Sessions and deltas pruned at 14 days; digests at 30 days. The 11pm consolidator handles this automatically.
- **Startup hook loads**: last 3 daily digests + last 3 individual session memories.

## Save Mode

Run this **before ending any session that involved meaningful work** — not for quick one-off questions, but for sessions that processed data, made decisions, created tasks, or discussed plans.

Write a session memory file with this structure:

```markdown
---
date: 2026-04-07
time: "17:41"
type: briefing | processing | planning | research | review | conversation
session_id: <current Claude Code session UUID, if known — see below>
covered_through: 2026-04-07T17:40:55-05:00
---
## Decisions
- [Key decisions made, with brief rationale]

## Data Pulled
- [Which APIs were queried, for what dates, key values]
- [e.g., "Fitbit: steps 14,200 (Apr 6), sleep 7h12m score 82"]
- [e.g., "Withings: weight 137.1 lbs, fat 10.5%"]
- [e.g., "Gmail: scanned 24h, 3 actionable items found"]

## Tasks Created
- [Task title] (things:///show?id=ID)

## People Updated
- [Name] — [what changed: last_contact, new context, new connection]

## Open Threads
- [Unfinished work, things Alex said he'd do, questions raised but not answered]
- [Include enough context that next session can pick up without re-reading everything]

## Active Themes
- [What Alex is focused on right now — job search, BlueDot prep, specific project]
- [Emotional context if relevant — stressed, energized, procrastinating]

## Next Session Hint
- [1-3 bullets: what the next session should prioritize or check on]
- [e.g., "Follow up on recruiter email from Acme Corp"]
- [e.g., "BlueDot starts in 6 days — check prep status"]
```

**Keep it concise.** Each section should be 2-5 bullets max. The goal is a 30-second scan at next session start, not a full transcript.

### `session_id` and `covered_through` (for delta detection)

The 11pm consolidator (`scripts/session-memory-consolidator.sh`) reads these fields to decide whether a session has new activity since its last memory. Always include them when writing a memory:

- **`session_id`**: the current Claude Code session UUID. Find it via the transcript path (`~/.claude/projects/<encoded-cwd>/<uuid>.jsonl`) — typically the most recently modified jsonl in that directory. If you cannot determine it confidently, omit the field; the consolidator will fall back to time-window matching.
- **`covered_through`**: ISO8601 timestamp of the last message included in this memory. Use the current time (`date -u +%Y-%m-%dT%H:%M:%SZ` or local equivalent) at the moment you write the memory.

If the user keeps interacting with the session after a memory is saved, the consolidator will write a `<HHMM>_delta.md` file covering only the new activity, with `previous_memory` pointing back to the original.

## Load Mode

The startup hook reads the last 3 session memory files and outputs them. Claude then generates a **Session Context Profile** — a mental model of what matters right now that guides behavior for the rest of the session.

### Generating the Context Profile

After reading the session memories injected by the startup hook, synthesize them into awareness of:

1. **Continuity**: What was Alex working on? Any open threads to pick up?
2. **Data freshness**: What data was already pulled today? Don't re-query APIs unnecessarily — check if raw health data is cached in today's daily note (HTML comments) before hitting Fitbit/Withings again.
3. **People in focus**: Who has Alex been interacting with? If the same person appears across multiple sessions, they're top-of-mind — prioritize their context in any CRM work.
4. **Emotional read**: Is Alex stressed, energized, procrastinating? Adjust tone and proactivity accordingly.
5. **Priority alignment**: What are the active themes? Weight everything toward those.

### Resource-Efficient Data Prioritization

As the Exobrain scales (more People notes, more daily notes, more skills, more MCP servers), the "read everything every time" approach wastes tokens, time, and API calls. Use the context profile to be **surgical** about what to read, query, and write.

#### 1. API Call Efficiency

| Signal | Action |
|--------|--------|
| Health data already pulled today (session memory says "Data Pulled: Fitbit/Withings") | **Skip APIs entirely.** Read raw data from today's daily note `<!-- health-raw-data -->` HTML comments. Zero API calls. |
| Health data pulled but >12 hours ago | **Selective refresh.** Only re-pull metrics that change intraday (steps, active zone minutes). Skip weight/body comp (once-daily morning weigh-in doesn't change). |
| No health data pulled today | **Full pull.** Query all Fitbit + Withings endpoints. Cache in HTML comments for later sessions. |
| Gmail already scanned this session | **Incremental scan.** Use `after:` timestamp from session memory's "Data Pulled" section instead of re-scanning 24h. |
| Calendar already read today | **Skip gcal_list_events** unless Alex explicitly asks or it's a new session type (e.g., briefing → winddown transition needs tomorrow's calendar, not today's). |
| Weather pulled <3 hours ago | **Skip.** Weather doesn't change that fast. |

#### 2. File Read Efficiency

| Signal | Action |
|--------|--------|
| CRM overdue check needed (daily briefing step 10) | **Don't glob + read all 50+ People notes.** First, read only the frontmatter (first 10 lines) of each file. Only read the full note for contacts that are actually overdue or coming due within 3 days. |
| People enrichment during email/iMessage scan | **Batch reads.** Collect all mentioned people first, then read their notes in one pass. Don't read → enrich → read → enrich one at a time. |
| Weekly review reading daily notes | **Read session memories first.** If session memories cover the week, use them as the primary source. Only read daily notes to fill gaps or verify specific claims. |
| Evening winddown recapping today | **Read today's session memories + today's daily note only.** Don't re-scan email, calendar, or health APIs — the briefing already captured that. |
| Processing a transcript that mentions 8 people | **Check People/ file existence with Glob first** (one call), then only Read the notes that exist. Don't Read-then-404 for each person. |
| Deep Recon vault search | **Use Grep with targeted queries**, not Read on every matching file. Read only the top 3-5 most relevant hits per search. |

#### 3. Tool Call Efficiency

| Signal | Action |
|--------|--------|
| Creating multiple Things 3 tasks | **Batch duplicate checks.** Run one `search_todos` with a broad query (e.g., "Reach out") instead of separate searches per contact. Parse results locally. |
| CRM tasks already created this session | **Track in session memory.** Before creating a "Reach out to [Name]" task, check session memory's "Tasks Created" section first — cheaper than an MCP call. |
| Multiple People notes need `last_contact` updates | **Batch writes.** Collect all updates, then write them sequentially. Don't interleave reads and writes. |
| Subagent work (Deep Recon, deep-research) | **Set model intentionally.** Use Sonnet for Explorer/Associator/Critic. Only use Opus for Synthesizer or when the task genuinely requires it. Never default all agents to Opus. |
| MCP tool search (deferred tools) | **Fetch in bulk.** One `ToolSearch` call for a category (e.g., "fitbit", max_results: 10) instead of individual `select:` calls per tool. |

#### 4. Write Efficiency

| Signal | Action |
|--------|--------|
| Daily note already has a `### Morning briefing` section | **Don't re-append.** Check for the heading before writing. If it exists, update in place or skip. |
| People note enrichment with trivial info ("sounds good" email) | **Skip the write entirely.** Only update `last_contact` in frontmatter. Don't add a Mention entry for routine messages. |
| Multiple transcript entries for the same day | **Append all to the same daily note in one write** if possible, rather than separate read-write cycles per transcript. |
| Session memory from a trivial interaction | **Don't save.** Quick lookups, one-off questions, and "what's the weather" don't warrant a session memory file. |

#### 5. Context Window Efficiency

| Signal | Action |
|--------|--------|
| Skill requires reading a large file (Mood Journal, Network CRM) | **Read targeted sections.** Use `offset` and `limit` parameters to read just the relevant date range, not the entire file. |
| Previous session memory mentions data values | **Trust the memory for planning purposes** (deciding what to do). Only re-read source files when you need to **act** on the data (create tasks, write notes, verify claims). |
| Briefing output getting long | **Omit empty sections.** If no flags, no new tasks, no overdue contacts — don't write placeholder sections. Shorter daily notes = less to read in future sessions. |
| Multiple skills need the same file (Dashboard.md, daily note) | **Read once at session start, reference from memory.** Don't re-read Dashboard.md in every skill that checks priorities. |
| Session has been running long (context pressure) | **Save a session memory proactively** before compression hits. Cheaper than losing context and re-deriving it. |

#### Decision Framework

When deciding whether to pull data, read a file, or make a tool call, apply this quick test:

1. **Is it cached?** Check session memory "Data Pulled" and daily note HTML comments first. If the data exists and is <12h old, use the cache.
2. **Do I need it now?** If the data only matters for a later step, defer the read. Don't front-load all reads at session start.
3. **How many items?** If >5 People notes, Things 3 tasks, or API calls needed, batch them. If >20, consider whether a subagent should handle it.
4. **Will the output be used?** If a daily note section would be empty, don't write it. If a People note update is trivial, skip the Mention entry.
5. **Is this the right session?** CRM deep enrichment can wait for weekly review. Flight buffer checks can wait for daily briefing. Don't do everything in every session.

### What NOT to do

- Don't read session memories aloud to Alex unless he asks ("what did we do last time?")
- Don't re-query APIs if today's data is already cached in the daily note
- Don't treat session memories as ground truth for current state — they're context clues, not authoritative. Always verify against live data when acting on a memory.
- Don't save a session memory for trivial interactions (quick lookups, one-off questions, "what's the weather")
- Don't glob + read all 50+ People notes when you only need 3
- Don't spawn Opus subagents for tasks Sonnet can handle
- Don't write empty sections to daily notes ("No flags today" wastes tokens on every future read)

## Integration Points

- **Startup hook** (`session-start.sh`): Reads and outputs last 3 session files
- **Daily briefing**: Context profile guides which health data to pull deep vs. shallow, which email categories to prioritize
- **Evening winddown**: Reads today's session memories to compile the day's recap without re-scanning everything
- **Weekly review**: Reads the week's session memories to identify recurring themes and open threads
- **Process transcript**: After processing, saves a session memory so the next session knows what was just routed
- **CLAUDE.md**: Instruction to save session memory before ending significant sessions
