---
name: crm
description: Look up, manage, and surface Network CRM contacts. Cross-references People/ notes, daily digest emails, transcripts, and calendar to keep Alex's network warm. Use when the user asks about a person, wants to follow up or reach out, asks "who is [name]", "when did I last talk to", "I should reach out to", "draft a message to", "look up [name]", "tell me about [name]", "who should I follow up with", "any overdue contacts", or mentions wanting to connect with someone.
---

# Network CRM (Obsidian-native)

Alex's CRM lives entirely in Obsidian. Each People/ note has YAML frontmatter with CRM fields. The Exobrain reads frontmatter to compute overdue status, surface follow-ups, and manage the network.

**Dashboard**: `/Users/alexhedtke/Documents/Exobrain/Network CRM.base`
**People notes**: `/Users/alexhedtke/Documents/Exobrain/Areas/Relationships & Community/People/[Name].md`

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
category: A           # A / B / C / D / potential / null
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
  if category == "null": skip (reference-only, no outreach)
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
2. Skip any with `category: null` (reference-only)
3. Compute overdue status for each
4. For each overdue person:
   - Why they're overdue (X days past, frequency Y)
   - Last interaction context (from Mentions section)
   - Suggested outreach approach (with an offer to help -- see Outreach Rules)
   - Platform (from `platform` frontmatter field)
5. Sort: Cat A overdue first, then B, C, D. Within category, most overdue first.
6. Also note anyone coming due in the next 3 days as "upcoming"

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
4. Pass the draft through the /de-ai skill
5. Note which platform to send on (from `platform` field)

### 5. Log contact: `/crm log [name]`
After Alex contacts someone:

1. Update `last_contact` in their People/ note frontmatter to today's date
2. Add a dated mention to the Mentions section if context is provided

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

### 9. Karpathy wiki integration (default behavior, not opt-in)

**The canonical schema lives at [[People Note Schema]] — read it before any substantial People-note edit.** This mode is not an "advanced feature." It is the default behavior for every skill that touches a People note.

**When to run:** Every time. `/process-transcript`, `/daily-briefing` (email/iMessage/calendar), `/weekly-review`, `/process-supernote`, `/imessage`, `/discord-digest`, and ad-hoc.

**The integration discipline (mandatory)**:

1. **Read the full note first.** Open Context, Connections, Personality & Dynamics — not just Mentions. Decide where new info belongs.

2. **Integrate, don't append.**
   - **Fact updates** → `## Context` (replace stale lines, weave new ones in; each fact appears once).
   - **Relationship links** → `## Connections` on BOTH notes (bidirectional).
   - **Recurring behavior, third instance of a pattern** → name it in `## Personality & Dynamics`. Each bullet names a *pattern*, not a single instance.
   - **Open thread** → `## Follow-ups`.
   - **Pure event log line** → `## Mentions` (with `[[Day, Month Dth, YYYY]]` wikilink).

3. **Promote signal up the stack.** When a Mention represents a pattern (3+ instances) or fixed fact, lift it into the right section and prune or compact the original Mention.

4. **Conflicting info wins on recency.** Old: "Works at Acme." New: "Now at StartupX." Update Context, remove the old line; don't keep both.

5. **Cross-reference enrichment.** Transcript A mentions person B → add a Mention to B's note: `- Mentioned by [[A]] (date) — [context]`. If a fact about B emerges, also update B's `## Context`.

6. **Frontmatter discipline.** Update `last_contact` on actual contact (not on indirect mentions). Update `expertise` and other frontmatter when those drift.

**No more "lightweight mode."** Routine pleasantries ("sounds good, see you Tuesday") still update `last_contact` and skip a Mention entry — but if the email reveals anything substantive (new role, location change, relationship shift, project update), integrate it. The bar is "is there new signal?", not "is this a long email?"

### 9b. Compaction — keeping People notes sharp

The wiki only compounds if you compact. Without this, notes degrade into append-only logs and the "wiki" claim becomes aspirational.

**Triggers for compaction on a People note**:
- Mentions section has > 30 entries
- A Mention older than 30 days describes a fact or pattern that didn't make it into Context / Personality & Dynamics
- Same fact restated across 3+ Mentions but never lifted
- ✅ closed Follow-ups sitting > 30 days
- Duplicate section headers (e.g., two `## Mentions`)
- Section order doesn't match [[People Note Schema]]

**How to compact**:
1. Read the full note.
2. For each Mention older than 30 days: ask "is this load-bearing?" If yes, lift the fact into Context or the pattern into Personality & Dynamics. If no, prune.
3. Aim for ≤ 25 Mentions on active contacts.
4. Replace stale Context lines with current ones.
5. Remove ✅ Follow-ups older than 30 days.
6. Reorder sections to match the canonical schema.

### 10. Integrate: `/crm integrate [name]`

Manually trigger a full Karpathy-style refactor on a single People note.

1. Read the full note.
2. Apply the compaction triggers above.
3. Promote signal up the stack: lift facts, name patterns, prune resolved threads.
4. Reorder sections to match [[People Note Schema]].
5. Bidirectional updates: if integration reveals connections to other People notes, update those too.
6. Report a diff-style summary (lines lifted, lines pruned, sections reorganized) so Alex can spot-check.

This is the explicit "I want this note in great shape" mode. The weekly-review integration audit (mode 11) surfaces candidates automatically.

### 11. Integration audit (used by weekly review)

Every Sunday, surface the 3-5 People notes most in need of compaction. For each People note:
- Count Mentions, count days since oldest unintegrated Mention, count duplicate section headers, count ✅ Follow-ups > 30 days old.
- Score and rank.
- The weekly review's CRM section lists the top 3-5 with a one-click `/crm integrate [Name]` deep link or recommendation.

Alex runs `/crm integrate [Name]` on the ones he wants refactored, or on his most-mentioned contacts as a maintenance pass.

## Integration with Other Skills

- **`/process-transcript`**: Calls Network scan (mode 8) for every transcript. Updates `last_contact` for anyone Alex spoke with.
- **`/daily-briefing`**: Scans People/ frontmatter for all overdue contacts. Lists every overdue contact in the briefing and creates a Things 3 task for each (see Task Creation below).
- **`/weekly-review`**: CRM health summary (total contacts, overdue count, category distribution). Surfaces 1 **potential** contact to initiate with this week and creates a Things 3 task for that outreach. Also runs the **integration audit (mode 11)** — surfaces 3-5 People notes most in need of compaction, with `/crm integrate` recommendations. Does not duplicate overdue surfacing (that's the daily briefing's job).
- Ad-hoc questions like "who should I follow up with?" or "tell me about [person]" can be answered via CRM lookup

## Task Creation

When the CRM surfaces contacts for outreach (overdue contacts in daily briefing, potential contacts in weekly review, or follow-up mode), **always create a Things 3 task** for each one:
- **Title**: `Reach out to [Name]`
- **Notes**: Include platform, last interaction context, and People note deep link (`obsidian://open?vault=Exobrain&file=Areas/Relationships%20%26%20Community/People/[Name]`)
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
