---
name: session-memory
description: Cross-session continuity and context-aware data prioritization. Saves structured summaries at session end, loads context at session start to guide what data to pull and how deep to go. Runs automatically via startup hook (load) and CLAUDE.md instruction (save). Also use when the user says "save session", "what did we do last time", or "context".
---

# Session Memory

Two modes: **save** (end of session) and **load** (start of session). The startup hook handles load automatically. Save is triggered by Claude before ending a significant session.

## Storage

- **Directory**: `/Users/alexhedtke/Documents/Exobrain/Claude/` (lives inside the Obsidian vault so memories are browsable and YAML frontmatter renders as Properties)
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

### Be surgical (not comprehensive)

Use the context profile to skip work, not just plan it. Key heuristics:

- **Trust the cache.** If session memory says "Data Pulled: Fitbit/Withings" today, read raw data from the daily note's `<!-- health-raw-data -->` HTML comments instead of re-querying. Same for weather (<3h), calendar (read today), Gmail (use `after:` timestamp).
- **Frontmatter first, body second.** For the CRM overdue check, read frontmatter on each People note (first 10 lines). Only open the full note for contacts that are actually overdue or due within 3 days.
- **Glob before Read.** When a transcript mentions N people, Glob `People/` once to see who exists, then Read only those.
- **Batch don't interleave.** One broad `search_todos` for many contacts. Collect all `last_contact` updates, then write. One ToolSearch with `max_results: 10` instead of N `select:` calls.
- **Skip trivial writes.** Don't append empty sections, don't add Mentions for "sounds good" replies, don't save session memory for one-off lookups.
- **Memory is context, not truth.** Use it to decide *what* to do; verify against live data before *acting*.

## Integration Points

- **Startup hook** (`session-start.sh`): Reads and outputs last 3 session files
- **Daily briefing**: Context profile guides which health data to pull deep vs. shallow, which email categories to prioritize
- **Evening winddown**: Reads today's session memories to compile the day's recap without re-scanning everything
- **Weekly review**: Reads the week's session memories to identify recurring themes and open threads
- **Process transcript**: After processing, saves a session memory so the next session knows what was just routed
- **CLAUDE.md**: Instruction to save session memory before ending significant sessions
