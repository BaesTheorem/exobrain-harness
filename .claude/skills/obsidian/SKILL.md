---
name: obsidian
description: Best practices and conventions for all Obsidian vault interactions. Canonical reference for daily note formatting, People notes, wikilinks, vault structure, and append-only rules. Referenced by other skills. Use when you need to check Obsidian conventions, note structure, or vault paths before reading or writing to the vault.
---

# Obsidian Vault — Best Practices Reference

This is the canonical reference for how the Exobrain interacts with the Obsidian vault. All skills that read from or write to the vault MUST follow these conventions.

## Vault Root

`/Users/alexhedtke/Documents/Exobrain/`

## Key Locations

| Path (relative to vault root) | Purpose |
|-------------------------------|---------|
| `Daily notes/` | Daily journal notes |
| `People/[Name].md` | Network CRM contact notes |
| `Projects/[Project Name]/` | Project folders (contain project note + related files) |
| `Dashboard.md` | Current priorities and overview |
| `Network CRM.md` | CRM dashboard (Dataview queries) |
| `Media/[Title].md` | Individual media notes (books, movies, shows, games) — rendered by `Media.base` |
| `Mood Journal.md` | Longitudinal mood tracking |
| `Plaud/` | Raw Plaud transcript files |
| `Supernotes` | Symlink to Supernote .note files |
| `[Campaign Name]/` | TTRPG campaign folders |

## Best Practices

### CRITICAL Rules

1. **NEVER overwrite existing content.** All vault writes are append-only. Read the file first, then append new content at the end. Destroying existing content is the single worst failure mode.

2. **Daily note filename format.** Use `dddd, MMMM Do, YYYY` -- e.g., `Wednesday, March 25th, 2026`. This format is strict. A wrong filename creates an orphan note that breaks navigation.

3. **Navigation header.** Every daily note MUST start with:
   ```
   << [[Yesterday Name|Yesterday]] | [[Tomorrow Name|Tomorrow]] >>
   ```
   If creating a new daily note, add this header first before any content.

4. **Late-night date handling.** Alex stays up past midnight. Before any operation that touches dates (daily notes, calendar, Fitbit, task completion, mood scoring), determine the "logical day":
   - **Before 2:00 AM** = treat as the **previous calendar day**
   - **2:00 AM or later** = treat as the **current calendar day**
   Lock the target date at the start of operations and do not re-derive it mid-execution, even if the clock crosses midnight or 2am. This applies to ALL date-sensitive operations across ALL skills.

5. **No blank lines before headers.** Obsidian renders spacing above headers automatically. Adding blank lines before `##` headers creates unwanted visual gaps.

6. **Check before creating.** Before creating any new note (topic, person, project), search the vault to confirm it does not already exist. Duplicate notes fragment knowledge.

7. **Wikilinks must target existing notes.** Before inserting `[[Note Name]]`, verify the target file exists in the vault. Broken wikilinks create noise in the graph view.

### Important Rules

8. **Transcript entries are standalone H3s.** Each processed transcript gets its own `### ` heading in the daily note. Never nest transcripts under a parent heading. Never use H2 for transcript entries. Never create a grouping heading like "### Transcripts".

9. **No H1 in People notes.** The filename displays as the title in Obsidian. Adding `# Name` creates a redundant heading.

10. **Things 3 deep links.** When referencing tasks in vault notes, always use:
    ```markdown
    - [ ] [Task name](things:///show?id=UUID)
    ```

11. **Obsidian backlinks for Things 3 projects.** The reciprocal link stored in the Things 3 project's notes field:
    ```
    obsidian://open?vault=Exobrain&file=Projects/[Project%20Name]/[Project%20Name]
    ```
    See the things3 skill for the full project backlink workflow.

12. **Project folder structure.** Active projects live in sub-folders under `Projects/`. Each project folder contains the primary project note (same name as the folder) plus any related files, sub-notes, or attachments:
    ```
    Projects/
      Get new job/
        Get new job.md          <-- primary project note
        Job Applications.md     <-- related tracking note
        Resume drafts/          <-- sub-folder for files
      PauseAI KC/
        PauseAI KC.md
        DC Trip Prep.md
    ```
    When creating a new project note, create the folder first, then the note inside it.

12. **Mood goes to yesterday's daily note.** During the morning briefing, mood scoring writes the `### Mood` section to YESTERDAY's daily note, not today's. Today's briefing shows only a 1-line summary.

13. **Media extraction.** When any content mentions movies, shows, anime, books, podcasts, articles, games, TTRPGs, or other media:
    - Extract: title, who recommended it, context, brief description
    - Create a note in `Media/[Title].md` with frontmatter (see CLAUDE.md "Media Extraction" for schema). For books, include `author` and `word_count` properties.
    - Check for duplicates first (Glob `Media/` folder). If a note already exists, append new context to the body.
    - Note in the daily note: "Added X media items to [[Media.base|Media]]"

14. **Write transcripts to the recording date.** Transcript entries go to the daily note matching the recording's local date (convert `create_time` from UTC to America/Chicago), NOT the date of processing.

## People Note Structure

Every People note follows this structure (in order):

```markdown
---
category: B
frequency: 21
last_contact: 2026-03-30
platform: Signal
expertise: AI safety
how_we_met: BlueDot
---
## Contact
- **Phone**:
- **Email**:
- **City**:
- **LinkedIn**:
- **Discord**:
- **Platform**:
- **Website**:
## Context
- First mentioned: [date] -- [how/where]
## Mentions
- [[Daily note link]] -- [1-line context]
## Follow-ups
- [pending items]
## Personality & Dynamics
[Optional -- communication style, social role, interaction patterns with specific examples.]
```

**People note rules:**
- Always include the full Contact card template, even if most fields are blank
- Additional contact fields can be appended (Venmo, Twitter/X, Bluesky, Instagram, Signal, Substack, etc.)
- Accumulate knowledge over time -- every transcript, email, meeting, and message is a chance to enrich the note
- Skip generic/unknown speakers ("Speaker 1", "unknown")
- Plaud mis-transcribes certain names — check People/ folder for canonical spellings before creating new notes
- Check the process-transcript skill's name mapping protocol for common Plaud corrections

## Daily Note Content Order

Content accumulates throughout the day in this general order:
1. Navigation header
2. `### Morning Briefing` (weather, health, schedule, tasks, Discord, iMessages, email)
3. Transcript entries (standalone H3s, written to recording date)
4. `### Supernote` (OCR'd handwritten notes)
5. Ad hoc sections (captures, call notes, etc.)
6. `### Local Events`
7. `### Evening Wind-Down` (day score, completed/rolled tasks, tomorrow's top 3)
8. `### Mood` (written by next morning's briefing or evening winddown)
9. `### Weekly Review` (Sundays only)

## Frontmatter Conventions

- Frontmatter is the source of truth for People note CRM data
- Always read current frontmatter before computing status -- never cache values
- If Alex overrides `frequency` to a non-default value, honor it
- CRM-operational fields stay in frontmatter: category, frequency, last_contact, platform, expertise, how_we_met
- Contact details live in the `## Contact` section, not frontmatter
