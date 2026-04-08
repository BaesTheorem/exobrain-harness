---
name: crm
description: Look up, manage, and surface Network CRM contacts. Cross-references People/ notes, daily digest emails, transcripts, and calendar to keep Alex's network warm. Use when the user asks about a person, wants to follow up or reach out, asks "who is [name]", "when did I last talk to", "I should reach out to", "draft a message to", "look up [name]", "tell me about [name]", "who should I follow up with", "any overdue contacts", or mentions wanting to connect with someone.
---

# Network CRM (Obsidian-native)

Alex's CRM lives entirely in Obsidian. Each People/ note has YAML frontmatter with CRM fields. The Exobrain reads frontmatter to compute overdue status, surface follow-ups, and manage the network.

**Dashboard**: `/Users/alexhedtke/Documents/Exobrain/Network CRM.md`
**People notes**: `/Users/alexhedtke/Documents/Exobrain/People/[Name].md`

## Category Frequencies

| Category | Frequency (days) |
|----------|-------------------|
| A | 14 (every 2 weeks) |
| B | 21 (every 3 weeks) |
| C | 45 (every 6 weeks) |
| D | 90 (every 3 months) |
| potential | no frequency -- tracked for future outreach |

## Frontmatter Schema

Frontmatter holds only CRM-operational fields. Contact details live in the `## Contact` section (see below).

```yaml
---
category: A           # A / B / C / D / potential
frequency: 14         # days (defaults from category, but user can override)
last_contact: 2026-03-30
platform: Signal      # preferred outreach method (optional)
expertise: AI safety  # optional
how_we_met: BlueDot   # optional
why_interesting: ...  # potential contacts only
reached_out: false    # potential contacts only
---
```

**Alex edits frontmatter directly in Obsidian.** The Exobrain must always read the current frontmatter before computing status -- never cache or assume values. If Alex changed a category or frequency manually, honor it.

## Contact Card

Every People note MUST have a `## Contact` section immediately after the frontmatter, before `## Context`. This is the visible contact card. Include all fields even if blank (so Alex can fill them in later):

```markdown
## Contact
- **Phone**: 555-1234
- **Email**: foo@bar.com
- **City**: Kansas City
- **LinkedIn**: https://linkedin.com/in/...
- **Discord**: username
- **Platform**: Signal
- **Website**: https://...
```

Additional fields can be appended as needed (e.g., **Venmo**, **Twitter/X**, **Bluesky**, **Instagram**, **Facebook**, **Signal**, **Substack**).

When creating a new People note, always include the full contact card template with blank fields. When processing transcripts or other inputs, populate any contact info discovered into the contact card.

## Computing Overdue Status

To determine who needs attention, scan all People/ notes that have `category` frontmatter:

```
for each People/ note with frontmatter:
  days_since = today - last_contact
  if days_since > frequency:
    OVERDUE by (days_since - frequency) days
  else:
    OK, due in (frequency - days_since) days
```

Sort overdue contacts by urgency: most overdue first, Cat A before Cat B at equal overdue days.

## Modes

### 1. Lookup: `/crm [name]`
When the user asks about a specific person:

1. Read `People/[Name].md` -- display frontmatter fields + all body content
2. Compute overdue status from frontmatter
3. Search Things 3 (`search_todos`) for tasks mentioning that person
4. Search recent calendar events (`gcal_list_events` with `q=[name]`, past 30 days)
5. **LinkedIn enrichment** (via Monid CLI): If no LinkedIn data yet:
   - `monid run -p apify -e /harvestapi/linkedin-profile-search-by-name --input '{"profileScraperMode": "Short", "firstName": "...", "lastName": "...", "strictSearch": true, "maxPages": 1}'`
   - If LinkedIn URL known: `monid run -p apify -e /dev_fusion/linkedin-profile-scraper --input '{"profileUrls": ["..."]}'`
   - Poll: `monid runs get --run-id <id> --wait`
   - Add `linkedin:` to frontmatter, add `## LinkedIn` section to body
   - Always prepend `export PATH="$HOME/.local/bin:$PATH" && NO_COLOR=1` to monid commands
6. Present unified view:
   ```
   ## [Name]
   - **Category**: [A/B/C/D] | **Last contact**: [date] ([X] days ago) | **Status**: [OK/OVERDUE by Y days]
   - **Email**: [email] | **City**: [city] | **Expertise**: [expertise]
   - **LinkedIn**: [URL]
   - **How we met**: [context]
   - **Recent interactions**: [from Mentions section]
   - **Open tasks**: [from Things 3]
   - **Upcoming calendar**: [any scheduled meetings]
   ```

### 2. Follow-up: `/crm follow-up` or `/crm overdue`
Surface everyone who needs attention:

1. Read all People/ notes that have `category` frontmatter (use Glob for `People/*.md`, then read each)
2. Compute overdue status for each
3. For each overdue person:
   - Why they're overdue (X days past, frequency Y)
   - Last interaction context (from Mentions section)
   - Suggested outreach approach (with an offer to help -- see Outreach Rules)
   - Platform (from `platform` frontmatter field)
4. Sort: Cat A overdue first, then B, C, D. Within category, most overdue first.
5. Also note anyone coming due in the next 3 days as "upcoming"

### 3. New contact: `/crm add [name]`
When Alex meets someone new:

1. Ask for or extract from context: name, email, how they met, city, expertise, category
2. **LinkedIn lookup** via Monid (see mode 1)
3. Create `People/[Name].md` with:
   - Frontmatter (category, frequency, last_contact, platform, expertise)
   - `## Contact` card (all fields, populated where known, blank where not)
   - `## Context`, `## Mentions`, `## Follow-ups` sections
4. Set `last_contact` to today
5. If there's a clear follow-up action, create a Things 3 task

### 4. Outreach draft: `/crm draft [name]`
Help Alex compose a message:

1. Read their People/ note for full context
2. Compute overdue status
3. Draft a concise, warm message that:
   - References last interaction or shared context
   - Includes a concrete offer to help (signal-boost writing, make intros, share resources, be a sounding board)
   - Asks an open-ended question to re-engage
   - Matches tone (closer contacts = more casual)
   - No em dashes (Alex's preference)
4. Note which platform to send on (from `platform` field)

### 5. Log contact: `/crm log [name]`
After Alex contacts someone:

1. Update `last_contact` in their People/ note frontmatter to today's date
2. Add a dated mention to the Mentions section if context is provided
3. That's it -- no more "create a task to update the Google Sheet"

### 6. Potential contact: `/crm potential [name]`
Track someone Alex wants to eventually connect with:

1. Create `People/[Name].md` with frontmatter:
   - `category: potential`
   - `why_interesting: ...`
   - `reached_out: false`
   - `date_added: [today]` (in body Context section)
2. Sources: transcript mentions, event speakers, article authors, LinkedIn connections of existing contacts

### 7. Graduate potential: `/crm graduate [name]`
When a potential contact becomes an active contact:

1. Update frontmatter: change `category` from `potential` to appropriate tier (default B)
2. Set `frequency` based on new category
3. Set `last_contact` to today
4. Remove `why_interesting` and `reached_out` fields (or leave for history)

### 8. Network scan (used during transcript/note processing)
When processing transcripts, emails, or calendar events:

1. Extract all identifiable people mentioned
2. For each person:
   - Check if they have a People/ note -> update Mentions section
   - If they have CRM frontmatter, update `last_contact` if the transcript represents actual contact
   - If no People/ note exists, create one
3. Classify new people as active vs potential
4. Surface in the daily note's Network section

### 9. Continuous integration — Karpathy wiki pattern
**Every input source that touches a person should enrich their People note, not just log a mention.** This is the compounding CRM's growth engine. The People/ directory is a self-updating wiki: new information gets integrated into existing pages rather than stored as raw append-only logs.

**When to run:** During every skill that encounters people — `/process-transcript`, `/daily-briefing` (email scan, iMessage scan, calendar review), `/weekly-review` (calendar retrospective, interaction highlights), `/process-supernote`, and ad-hoc conversations.

**What to integrate (beyond `last_contact` and Mentions):**

1. **Factual updates to `## Context`**: New job, moved cities, started a project, changed roles, got married, had a kid, adopted a pet, started a hobby, health updates, life events. Don't re-add what's already there — read the existing Context section first and only add genuinely new information.

2. **Relationship graph updates**: If the input reveals a connection between two people (e.g., "Sarah introduced me to James"), update BOTH People notes. Add a line like `- Connected to [[James Chen]] — introduced by Sarah at BlueDot meetup (2026-04-07)` to a `## Connections` section (create it if it doesn't exist, place it after `## Contact`).

3. **Interest/topic evolution**: If someone's interests or expertise shift (e.g., they used to talk about ML but now they're focused on policy), update `expertise` in frontmatter and add context to `## Context`.

4. **Communication pattern observations**: If you notice patterns across multiple interactions (e.g., "always responds quickly on Signal but ignores email", "tends to reach out when stressed"), add to `## Personality & Dynamics`.

5. **Cross-reference enrichment**: When processing a transcript that mentions Person A talking about Person B, update Person B's note with `- Mentioned by [[Person A]] in conversation (date) — [context]` in Mentions. This captures indirect intel.

**How to integrate (not append):**
- Read the full People note before writing
- If new info contradicts old info, update the old info (e.g., old: "Works at Acme Corp" → new email signature says "Now at StartupX" → update Context, don't append both)
- If new info extends existing info, weave it into the existing paragraph/bullet rather than adding a new one
- Keep `## Mentions` as an append-only chronological log (this is the raw audit trail)
- Keep `## Context`, `## Connections`, and `## Personality & Dynamics` as living documents that get refined over time

**Lightweight mode for daily briefing:** The daily briefing processes dozens of emails and messages. For efficiency, only do deep enrichment when the input contains substantive new information about a person (new job, life event, project update, relationship insight). For routine emails ("sounds good, see you Tuesday"), just update `last_contact` — don't add a Mention entry for every pleasantry.

## Integration with Other Skills

- **`/process-transcript`**: Calls Network scan (mode 8) for every transcript. Updates `last_contact` for anyone Alex spoke with.
- **`/daily-briefing`**: Scans People/ frontmatter for all overdue contacts. Lists every overdue contact in the briefing and creates a Things 3 task for each (see Task Creation below).
- **`/weekly-review`**: CRM health summary (total contacts, overdue count, category distribution). Surfaces 1 **potential** contact to initiate with this week and creates a Things 3 task for that outreach. Does not duplicate overdue surfacing (that's the daily briefing's job).
- **`/hey-claude`**: Can answer "who should I follow up with?" or "tell me about [person]"

## Task Creation

When the CRM surfaces contacts for outreach (overdue contacts in daily briefing, potential contacts in weekly review, or follow-up mode), **always create a Things 3 task** for each one:
- **Title**: `Reach out to [Name]`
- **When**: `today` (for daily briefing) or `anytime` (for weekly review)
- **Notes**: Include platform, last interaction context, and People note deep link (`obsidian://open?vault=Exobrain&file=People/[Name]`)
- **Tags**: `["networking"]`
- Search Things 3 first (`search_todos`) to avoid duplicates -- don't create a task if one already exists for that person
- Do NOT create tasks for potential contacts outside of the weekly review's "1 potential per week" pick -- let the CRM surface them naturally

## Outreach Rules (from Alex's preferences)
- **Always include an offer to help** in any outreach message
- Specific offers > generic offers (use Alex's actual capabilities: AI safety network, PauseAI connections, technical skills, signal-boosting writing)
- Re-engagement before big asks (don't ask for mentorship on first re-contact)
- Keep messages concise -- match the platform (Messenger = shorter, email = slightly longer)
- **No em dashes** in outward-facing text
- Always humanize content Alex shares with others
