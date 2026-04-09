# Monthly Review

Comprehensive end-of-month review covering system health, weekly review synthesis, values alignment, area balance, and project vitality. Outputs to a dedicated section in the last Sunday's daily note for the month.

## Trigger

Use when: the user asks for a monthly review, it's the last weekend of the month, or the user says "how was my month", "monthly check-in", "month in review".

## Instructions

This is a LONG skill. Run all independent data-gathering steps in parallel. Present findings conversationally and interactively — this is a collaborative review, not a dump. Pause for Alex's input at key decision points (especially values, areas, and project pruning).

The monthly review has five sections. Execute them in this order:

---

### SECTION 1: Weekly Review Synthesis

**Goal**: Summarize the month's weekly reviews into themes, wins, and recurring issues.

**Steps**:
1. Identify all Sundays in the current month
2. Read each Sunday's daily note from the Obsidian vault (`/Users/alexhedtke/Documents/Exobrain/Daily notes/`)
3. Extract the `## Weekly Review` section from each
4. Synthesize across all weekly reviews:
   - **Wins**: What went well repeatedly? What got done?
   - **Recurring blockers**: What kept showing up as unfinished, procrastinated, or flagged?
   - **Health trends**: Month-over-month trajectory (steps, sleep, mood, Withings body composition — weight, fat %, muscle mass; do NOT use Fitbit for weight)
   - **Social patterns**: Who showed up most? Any relationships that deepened or cooled?
   - **Priority alignment**: How well did actual time spent match Dashboard.md priorities?
   - **Mood arc**: Plot the weekly mood scores across the month — is the trend up, down, or flat? What drove it?

**Output format** (for the daily note):
```markdown
## Monthly Review — [Month Year]
### Month in Review
**Wins**: [3-5 bullets]
**Recurring blockers**: [what kept coming back]
**Health trajectory**: [summary with actual numbers from weekly reviews]
**Social patterns**: [who appeared most, relationship dynamics]
**Priority alignment**: [honest assessment]
**Mood arc**: [week-by-week scores if available, trend, primary drivers]
```

---

### SECTION 2: Values Alignment

**Goal**: Help Alex reflect on how well he embodied each core value this month, and brainstorm how to embody them next month.

**Alex's five core values** (from `⭐️ Core values and interests.md` and individual value notes):

1. **Life** — Sapience matters. Death is bad. Life extension, preventing species death, protecting humanity.
2. **Truth** — Objective reality, Bayesian rationality. Desiring to know what is true for its own sake.
3. **Freedom** — Agency, consent, dignity. Opposing coercion and multipolar traps.
4. **Responsibility** — Heroic responsibility. No excuses. If you can fix suffering, you must.
5. **Happiness** — Hedonic AND eudaimonic. Pleasure, relationships, hard work aligned with values, mindfulness, preventing suffering.

**Alex's mission statement**: "To be a friend, leader, and romantic partner that fosters a culture of empathy and courageous truth seeking to make the world a better place. To live a life that makes a good story."

**Steps**:
1. Read all daily notes from the month (not just Sundays) — scan for evidence of each value being lived or neglected
2. Cross-reference with:
   - Things 3 completed tasks (via `get_logbook` or checking weekly review completion lists)
   - Calendar events attended (meetings, social, activism, learning)
   - Transcript summaries (from weekly reviews or processing log)
   - Discord/iMessage patterns (social engagement quality)
   - Health data (self-care as embodiment of Happiness and Responsibility)
   - Mood journal entries (which sub-categories thrived or suffered)
3. For each value, draft:
   - **This month**: A SHORT (2-3 sentence) honest blurb about how well Alex embodied this value. Be specific — cite actual events, decisions, or patterns. Don't sugarcoat but don't be harsh. Flag tensions between values if they appeared (e.g., Freedom vs Responsibility).
   - **Next month ideas**: 2-3 CONCRETE suggestions for embodying this value better. These are prompts and ideas for Alex to react to, NOT prescriptions. Draw from:
     - Stalled projects that align with this value
     - Someday items that could be promoted
     - Relationships that could be deepened
     - Events or commitments on the horizon
     - Gaps observed in the month's data

**IMPORTANT**: Do NOT write the final blurbs yourself. Present your evidence and draft ideas, then ASK Alex to react. He writes the final version. Your job is to surface the raw material and spark reflection.

**Output format** (for the daily note, AFTER Alex has reacted):
```markdown
### Values Check-In
#### Life
**This month**: [Alex's reflection, with your help]
**Next month**: [Alex's intentions]

#### Truth
**This month**: [...]
**Next month**: [...]

[...repeat for Freedom, Responsibility, Happiness]
```

---

### SECTION 3: Areas Balance

**Goal**: Check that no life area is consuming Alex disproportionately (especially romantic relationships), and ensure every area has at least one active project.

**Things 3 Areas** (current structure):
- Morning (bootup routine)
- Exobrain (system)
- Relationships & Community
- Health & Fitness
- Values & Purpose
- Cognition & Learning
- Emotions & Wellbeing
- Location & Tangibles
- Money & Finances
- Adventure & Creativity
- Contribution & Impact
- Work & Career
- Evening (power down routine)

**Steps**:
1. Pull all active projects and tasks from Things 3:
   - `get_projects` — list all active projects with their areas
   - `get_areas` — list all areas
   - `get_someday` — list someday items (potential promotions)
   - `get_anytime` — list anytime tasks
2. For each area, determine:
   - Number of active projects
   - Number of active tasks
   - Number of completed tasks this month (from weekly review summaries or logbook)
   - Rough time investment (inferred from calendar events, daily notes, transcript topics)
3. Flag imbalances:
   - **Over-indexed areas**: Disproportionate time/energy vs stated priorities. Pay SPECIAL attention to romantic relationship patterns — scan daily notes, iMessages, transcripts, calendar for dating/relationship time. If this area is consuming Alex, flag it directly but constructively.
   - **Under-indexed areas**: Areas with zero active projects or zero activity this month
   - **Stagnant areas**: Areas where the same tasks have been sitting untouched
4. For each area with NO active project:
   - Search `get_someday` for items that could be promoted
   - Search Obsidian vault for related notes or ideas
   - Suggest 1-2 lightweight projects to keep the area alive (not burdensome — just enough to prevent stagnation)
5. Present findings to Alex and discuss. This is a CONVERSATION, not a report.

**Output format** (for the daily note):
```markdown
### Areas Balance
| Area | Active Projects | Activity Level | Flag |
|------|----------------|----------------|------|
| [area] | [count] | High/Medium/Low/None | [over-indexed/stagnant/healthy] |

**Over-indexed**: [areas getting too much time relative to priorities]
**Needs attention**: [areas with no projects or no activity]
**Someday promotions**: [suggested items to move from Someday to active]
```

---

### SECTION 4: Project Vitality Check

**Goal**: Review every active project. If no progress was made this month, help Alex decide whether to keep, pause, or kill it.

**Steps**:
1. Get all active projects from Things 3 (`get_projects`)
2. Verify each project has an Obsidian backlink in its notes field (`obsidian://open?vault=Exobrain&file=Projects/...`). If missing, add it via `update_project` and create the corresponding Obsidian note if needed.
3. For each project, assess progress this month:
   - Check completed tasks within the project
   - Search daily notes for mentions of the project
   - Check calendar for related events
   - Check transcripts/processing log for discussions about it
3. Categorize each project:
   - **Active**: Clear progress this month (tasks completed, work done, events attended)
   - **Stalled**: No meaningful progress. May still be important.
   - **Dormant**: No activity AND no mentions. Candidate for pruning.
4. For each **Stalled** project:
   - Surface the original motivation (from project notes in Obsidian or Things 3)
   - Ask Alex directly: "Is this still worth your time? What would need to change for you to make progress?"
   - If Alex wants to keep it: suggest ONE concrete next action and a deadline
   - If Alex wants advice: offer to draft a message to someone in the network who could help (check People/ notes for relevant contacts with expertise)
5. For each **Dormant** project:
   - Recommend moving to Someday unless Alex objects
   - If it aligns with a core value or Dashboard priority, flag that tension

**IMPORTANT**: Do NOT unilaterally move or delete projects. Present your assessment and let Alex decide. For projects Alex wants to keep but is stuck on, offer to draft outreach to a relevant contact (using /crm conventions — always include an offer to help).

**Output format** (for the daily note):
```markdown
### Project Vitality
| Project | Area | Status | Progress This Month |
|---------|------|--------|-------------------|
| [name] | [area] | Active/Stalled/Dormant | [brief description] |

**Decisions made**:
- [Project X]: [kept/paused/killed] — [reason]
- [Project Y]: Next action: [task] by [date]
```

---

### SECTION 5: System Audit

**Goal**: Ensure the Exobrain harness itself is healthy, reliable, and not rotting.

**Steps**:
1. **Scheduled tasks health**:
   - List all scheduled tasks (`list_scheduled_tasks`)
   - Check `lastRunAt` for each — flag any that haven't run in expected timeframe
   - Check if any are disabled

2. **Processing log health**:
   - Read `processing-log.json`
   - Count items processed this month by source (plaud, supernote)
   - Flag any processing gaps (days where transcripts existed but weren't processed)

3. **launchd jobs health**:
   - `launchctl list | grep exobrain` — verify jobs are loaded and running
   - Check `/tmp/exobrain-plaud-watcher.log` and `.err` for errors

4. **MCP server health**:
   - Test Things 3 MCP: `get_inbox` (should respond)
   - Test Fitbit MCP: `get_profile` (should respond, check token freshness)
   - Test Google Calendar: `gcal_list_events` for today (should respond)
   - Test Gmail: `gmail_get_profile` (should respond)
   - Note any MCP servers that fail or timeout

5. **Script health**:
   - Verify `supernote-parser.py` runs: `python3 transcript-processing/supernote-parser.py --help` or similar
   - Verify `imessage-reader.py` runs: `python3 imessage/imessage-reader.py list --limit 1`
   - Verify `get-weather.py` runs: `python3 weather/get-weather.py`
   - Check Python dependency versions: `pip3 list | grep -iE "supernote|openmeteo"`

6. **Dependency freshness**:
   - Check Python version (`python3 --version`)
   - Check Node version (`node --version`)
   - Check if `uv` is functional (`python3 -m uv --version`)
   - Flag any EOL or significantly outdated versions

7. **Vault health**:
   - Check for orphaned People/ notes (mentioned nowhere)
   - Check daily note naming consistency (any files that don't match `dddd, MMMM Do, YYYY` format)
   - Count total People notes, daily notes, project notes — month-over-month growth

8. **Memory system review**:
   - Read MEMORY.md index
   - Flag any memories that may be stale or outdated
   - Suggest new memories if patterns from this month's review warrant them

9. **Skill health**:
   - List all skills, note any that haven't been used this month (check processing log and daily notes for invocation evidence)
   - Flag skills that may need updating based on issues encountered this month

10. **Security check**:
    - Verify `.gitignore` still excludes `.mcp.json`, `settings.local.json`, channels/
    - Check no secrets have leaked into tracked files
    - Verify Fitbit token is refreshing (check `.fitbit-token.json` modification date)

**Output format** (for the daily note):
```markdown
### System Audit
**Scheduled tasks**: [all healthy / issues found]
**Processing**: [N items processed this month (X plaud, Y supernote)]
**MCP servers**: [all responding / issues found]
**Scripts**: [all functional / issues found]
**Dependencies**: [current / needs update]
**Vault stats**: [N people notes, N daily notes, N project notes]
**Issues found**: [list any problems with remediation steps]
**Recommendations**: [improvements to implement next month]
```

---

## Writing the Output

After all five sections are complete and Alex has had a chance to react to the values and project sections:

1. Write the full monthly review to the **last Sunday's daily note** for the month
   - If Sunday falls in the next month, use the last day of the current month instead
   - Append after any existing content (including weekly review if present)
   - Use the section headers shown above
2. Send macOS notification: `"Monthly review complete — check today's daily note"`
3. Update processing log is NOT needed (monthly review is not a processing event)

## Interaction Style

This is the most reflective, high-level review in the system. Be:
- **Honest but constructive** — surface hard truths about stalled projects and value misalignment, but frame them as opportunities
- **Collaborative** — pause for Alex's input at key moments (values, project decisions). Don't just dump a report.
- **Specific** — cite actual events, dates, people, numbers. Vague encouragement is useless.
- **Forward-looking** — every finding should connect to a concrete action or intention for next month

## Timing

Ideal cadence: last Sunday of each month, after the weekly review is complete. Can also be triggered manually anytime.

Estimated duration: 20-30 minutes of collaborative review (not a quick automated dump).
