---
name: exobrain-audit
description: Audit the Exobrain harness REPO itself — scans tracked files for leaked personal data, checks legibility for stranger cloning, analyzes architecture, and surfaces AI productivity ideas. SCOPE IS THIS REPO, not the laptop or the public internet. Use when the user says "audit", "exobrain audit", "harness audit", "repo audit", or "harness privacy scan", or wants to review the health, legibility, and efficiency of the Exobrain harness codebase. For online/public attack surface use cybersecurity-bodyguard; for laptop/macOS security use antivirus.
user_invocable: true
---

# Exobrain Audit

A three-phase audit that checks repo privacy, analyzes harness architecture, and researches the latest AI productivity ideas. Each phase runs semi-independently via subagents, so they can execute in parallel where possible.

## Phase 1: Privacy & Legibility Audit

This is the most critical phase. The Exobrain harness repo is designed to be publicly sharable and replicable. That means **no personal data in tracked files** AND **the repo must make sense to a stranger cloning it for the first time**.

### What to scan for

Run `git ls-files` to get all tracked files, then scan them for:

1. **Other people's real names or identifying info** — full names, phone numbers, email addresses, physical addresses, Discord-to-real-name mappings, transcript speaker corrections. Generic placeholders like `[Name]` or `[Friend]` are fine.
2. **Alex's private info** — salary, home address/ZIP, health data values, relationship details beyond what's needed for function (cycle data values, mood scores, etc.)
3. **Name-to-identity mappings** — any table, dict, or config that maps usernames/handles to real people
4. **API keys, tokens, credentials** — anything that looks like a secret (long random strings, `sk-`, `token:`, `Bearer`, etc.)
5. **Personal data logs** — mood scores, cycle data entries, event preferences, message content, processing log entries with personal details

### Legibility check

Beyond privacy, also check that the repo is **legible to someone who isn't Alex**:

1. **Missing READMEs** — every directory that contains gitignored runtime files should have a README explaining what's missing and how to set it up. Check that these READMEs exist and are accurate.
2. **Hardcoded paths** — tracked files that hardcode `/Users/alexhedtke/` or other machine-specific paths without explanation. These should either be configurable, documented, or noted in a setup guide.
3. **Unexplained conventions** — scripts, hooks, or configs that do something non-obvious without comments or docs explaining why. A newcomer should be able to understand the "what" and "why" of each component.
4. **Missing setup instructions** — could someone clone this repo and get it running? Check for gaps in onboarding: missing dependency lists, undocumented environment variables, MCP servers that need manual setup, etc.
5. **Stale READMEs** — existing READMEs that reference files, paths, or workflows that no longer exist.

### How to scan

Spawn 3-4 parallel subagents, each covering a subset of tracked files (split by directory). Each subagent should:

1. Read every tracked file in its assigned directory tree
2. Flag any line containing potential personal data with: file path, line number, the content, and why it's flagged
3. Classify each finding as:
   - **REMOVE** — data is unnecessary for function, just delete it
   - **GITIGNORE** — data is needed at runtime but shouldn't be tracked. The file should be added to `.gitignore` and a `README.md` created in the same directory explaining what's missing and how to rebuild it
   - **LEGIBILITY** — not a privacy issue, but a legibility gap (missing README, unexplained config, hardcoded path, stale docs). Needs documentation or refactoring to make the repo understandable to newcomers.
   - **FALSE POSITIVE** — looks personal but is actually fine (e.g., a generic example, a public figure's name in context)

### Reference

The full privacy policy is in CLAUDE.md under "Privacy & Legibility (CRITICAL)". Read it before scanning so you internalize the rules.

### Output

Produce a structured findings list:
```
#### Privacy Findings
- **[SEVERITY]** `path/to/file:line` — [description of what was found]
  - Action: [REMOVE / GITIGNORE+README / FALSE POSITIVE]

#### Legibility Findings
- **[SEVERITY]** `path/or/directory` — [what's missing or unclear]
  - Action: [Add README / Add comments / Document in setup guide / Update stale docs]
```

If the audit is clean, say so: "No privacy issues found in [N] tracked files. Legibility: [N] gaps / all clear."

Do NOT automatically fix findings. Present them for Alex to review first. If Alex approves fixes, then execute them (remove data, update .gitignore, create READMEs).

## Phase 2: Architecture Recon

Use the `/deep-recon` skill to analyze the Exobrain harness holistically. The goal is to spot things that are hard to see when you're working on individual pieces day-to-day.

### Recon prompt

Pass this to deep-recon (adjust based on any specific concerns Alex raises):

> Analyze the Exobrain harness at `/Users/alexhedtke/Documents/Exobrain harness/` as a complete system. Map out every component — skills, hooks, scheduled tasks, launchd watchers, scripts, MCP integrations, data flows — and how they interact. Then identify:
>
> 1. **Blindspots**: What inputs or scenarios could fall through the cracks? Where are there no error handlers or fallback paths?
> 2. **Redundancies**: Are any skills/scripts doing overlapping work? Are there duplicate data flows?
> 3. **Inefficiencies**: What wastes tokens, time, or API calls? Where do agents do work that could be cached, pre-computed, or skipped?
> 4. **Stale configs**: Any references to things that no longer exist? Dead code? Scheduled tasks that never fire?
> 5. **Missing connections**: What integrations or data flows are obviously missing given what the system already does?
> 6. **Fragility**: What would break if a single service went down? Single points of failure?
>
> Be specific — cite file paths, line numbers, and concrete examples. Prioritize findings by impact.

### Output

The deep-recon skill produces its own structured document. Summarize the top findings (max 10) in the daily note output, and link to the full recon document if one is generated.

## Phase 3: AI Productivity Research

Use the `/deep-research` skill to survey the current landscape of AI-powered productivity systems and surface ideas that could improve the harness.

### Research prompt

Pass this to deep-research:

> Research the latest developments (last 30 days) in AI-powered personal productivity systems, with a focus on:
>
> 1. **Claude Code / Claude-powered setups** — new skills, MCP servers, hooks, automation patterns, prompt engineering techniques people are using
> 2. **Token efficiency** — strategies for reducing context window usage, smarter caching, progressive disclosure patterns, when to use subagents vs inline
> 3. **Personal knowledge management** — new approaches to note-taking, CRM, task management, or daily reviews using AI
> 4. **Multi-agent architectures** — patterns for orchestrating multiple AI agents for personal productivity
> 5. **New MCP servers or tools** — anything released recently that could plug into an Obsidian + Things 3 + Google Calendar + health tracking stack
> 6. **Community projects** — interesting open-source projects, blog posts, or forum discussions about AI productivity setups similar to Exobrain
>
> For each finding, assess: How hard would it be to integrate into an existing Obsidian-based harness? What's the expected value? Is it proven or experimental?

### Output

Synthesize the top recommendations (max 8) with:
- What it is and where you found it
- Why it's relevant to this harness specifically
- Effort estimate (trivial / moderate / significant)
- Priority recommendation (do now / backlog / watch)

## Output Location

Audit reports are too large for daily notes. Write full reports to a dedicated folder:

- **Audits folder**: `/Users/alexhedtke/Documents/Exobrain/Areas/Exobrain/Audits/`
- **Report filename**: `YYYY-MM-DD-audit.md`
- **Daily note**: Add a short summary (5-10 lines max) under `### Exobrain Audit` with a link to the full report

### Full Report Format (`audits/YYYY-MM-DD-audit.md`)

```markdown
# Exobrain Audit — YYYY-MM-DD

## Privacy & Legibility Scan
[Full findings list with file paths, line numbers, classifications]

## Architecture Review
[Full deep-recon output]

## AI Productivity Research
[Full deep-research synthesis]

## Action Items
- [ ] [Specific next steps, prioritized]
```

### Daily Note Summary

```markdown
### Exobrain Audit
*[Full report](../Exobrain%20harness/audits/YYYY-MM-DD-audit.md)*

- **Privacy**: [N] issues found ([breakdown by type]) / Clean
- **Legibility**: [N] gaps found / Good
- **Architecture**: [top 2-3 findings, one line each]
- **Research**: [top 2-3 recommendations, one line each]
- **Action items**: [count] — see full report
```

Create Things 3 tasks for any action items that need follow-up (check for duplicates first per `/things3` conventions).

## Execution Flow

When invoked:

1. Read CLAUDE.md's Privacy & Legibility section to ground the privacy scan
2. Ensure `audits/` directory exists
3. Launch all three phases in parallel:
   - Phase 1: Privacy & legibility subagents scanning tracked files
   - Phase 2: Deep-recon skill invocation
   - Phase 3: Deep-research skill invocation
4. As phases complete, collect their outputs
5. Write the full report to `Audits/YYYY-MM-DD-audit.md` in the Obsidian vault
6. Write the summary to today's daily note under `### Exobrain Audit`

## When to run

- On demand when Alex asks for an audit
- Monthly as part of the `/monthly-review` skill (suggest it if it hasn't been run in 30+ days)
- After major harness changes (new skills, new integrations, restructuring)
