---
name: linkedin
description: Best practices and conventions for all LinkedIn MCP interactions. Canonical reference for read-only profile/company/job lookups, bot-detection avoidance, and pacing rules. Referenced by other skills (job-search, crm). Use when you need to look up a person, company, or job on LinkedIn, or verify what's allowed before calling a `mcp__linkedin__*` tool.
---

# LinkedIn -- Best Practices Reference

This is the canonical reference for how the Exobrain interacts with LinkedIn via the `linkedin-scraper-mcp` server. All skills that touch LinkedIn MUST follow these conventions.

## CRITICAL -- Read-Only Rule

**The LinkedIn MCP is READ-ONLY for Alex.** This is a hard rule, not a default. The cost of getting his account flagged or banned is much higher than any convenience gained from automated writes.

- **Allowed**: search and lookup tools (`search_*`, `get_*`)
- **Forbidden**: any action that creates content, sends messages, or modifies Alex's network
- **If Alex needs to send a message or connection request**: draft it for him as text, and tell him to send it manually from the LinkedIn UI. Never invoke a write tool, even if Alex asks -- confirm out loud that he wants it manual, then hand off the draft.

| Status | Tools |
|--------|-------|
| ✅ ALLOWED | `get_my_profile`, `get_person_profile`, `search_people`, `get_sidebar_profiles`, `search_companies`, `get_company_profile`, `get_company_employees`, `get_company_posts`, `search_jobs`, `get_job_details`, `get_feed`, `get_inbox`, `get_conversation`, `search_conversations`, `close_session` |
| ❌ FORBIDDEN | `send_message`, `connect_with_person`, and any future like/comment/post/react/follow/endorse tools |

The inbox and conversation read tools are allowed (Alex can see his own messages), but never reply or send through them.

## Bot-Detection Avoidance

The `linkedin-scraper-mcp` server uses a real Chromium browser via Patchright. LinkedIn TOS prohibit automation, and bulk/rapid usage is what gets accounts banned. Treat every call like a human action.

### Pacing rules

No numerical call cap -- Alex confirmed 2026-05-19 that the prior soft/hard caps (15-20 / 30) were overly conservative and not grounded in any published LinkedIn threshold. Keep the qualitative rules below; they matter more than absolute volume.

1. **No tight loops.** Never chain LinkedIn calls in a `for` over a list without spacing. If you need to look up 10 people, surface the first few and check with Alex before burning through the rest silently. Same for bulk JD reads -- batch with reasoning between batches, not a single fire-and-forget queue of 30.
2. **No parallel calls.** The server serializes anyway (single shared browser), but don't queue many lookups in one tool-use block -- issue them sequentially in small batches (2-4 per turn), with brief reasoning between, so the activity pattern looks like a human reading results.
3. **Prefer narrow over broad.** A targeted `get_person_profile` on one known URL beats a `search_people` that returns 25 results you then enrich. Pull only what you need.
4. **Keyword-filter `get_company_employees`.** When looking for hiring contacts at a company, always pass a title keyword filter (`IT Manager`, `CISO`, `Director`) rather than dumping all employees.
5. **Vary patterns across sessions.** Don't run the same query at the same time every day with the same parameters -- for daily scans, rotate keyword angles (see `/job-search` Daily Briefing) so the activity profile looks like a person exploring, not a script.

### Session hygiene

- The browser profile lives at `~/.linkedin-mcp/profile/`. The session persists across Claude conversations.
- If a tool call returns "setup in progress," Patchright is downloading Chromium in the background. Retry once after a brief pause; don't loop.
- Call `close_session` only when explicitly winding down -- leaving the session warm avoids repeated logins (each login is itself a bot-detection signal).
- If a call returns a challenge/CAPTCHA error, stop immediately and tell Alex. Don't retry -- repeated challenges escalate to account locks.

### Volume signals that get accounts banned

- Sending many connection requests in a short window (especially with low acceptance rate)
- Scraping hundreds of profiles per day
- Repeated identical-pattern searches
- Logins from unusual IPs in rapid succession

None of these apply to the read-only flow described here, but **never** add features that drift toward them. If a task seems to require bulk write activity, push back rather than implement it.

## MCP Tools

### People

| Tool | Purpose | Common args |
|------|---------|-------------|
| `mcp__linkedin__get_my_profile` | Alex's own profile | -- |
| `mcp__linkedin__get_person_profile` | Detailed profile by URL | `linkedin_url`, section flags (`experience`, `education`, `contact_info`, `skills`, `certifications`, `posts`) |
| `mcp__linkedin__search_people` | Find people by name/keyword | `firstName`, `lastName`, `keywords`, `currentCompany` (URN or URL), `location`, `connectionOf` |
| `mcp__linkedin__get_sidebar_profiles` | "People you may know" from a profile page | `linkedin_url` |

### Companies

| Tool | Purpose | Common args |
|------|---------|-------------|
| `mcp__linkedin__search_companies` | Find companies by keyword | `keywords` |
| `mcp__linkedin__get_company_profile` | Company info with optional sections | `linkedin_url`, section flags (`posts`, `jobs`, `about`) |
| `mcp__linkedin__get_company_employees` | Employees at a company | `linkedin_url`, `keywords` (title filter -- **always set this**) |
| `mcp__linkedin__get_company_posts` | Recent company feed posts | `linkedin_url` |

`get_company_profile` with the `about` section usually returns a `company_urn` -- that's the numeric ID needed for `search_people`'s `currentCompany` URL facet.

### Jobs

| Tool | Purpose | Common args |
|------|---------|-------------|
| `mcp__linkedin__search_jobs` | Keyword + location job search | `keywords`, `location`, `experience_level`, `remote` |
| `mcp__linkedin__get_job_details` | Full posting detail | `linkedin_url` or `job_id` |

LinkedIn job IDs encode age: 37xxxxx = 2023-2024, 41-42xxxxx = late 2025, 43xxxxx+ = 2026. Old IDs on supposedly-open roles are a red flag -- see `/job-search` verification rules.

### Feed & messaging (read-only)

| Tool | Purpose |
|------|---------|
| `mcp__linkedin__get_feed` | Authenticated home feed |
| `mcp__linkedin__get_inbox` | Alex's message inbox |
| `mcp__linkedin__get_conversation` | One conversation thread |
| `mcp__linkedin__search_conversations` | Search inbox |
| `mcp__linkedin__close_session` | Close the browser session |

## Best Practices

### CRITICAL Rules

1. **Read-only or refuse.** See the section above. No exceptions.
2. **Pace calls like a human.** No bulk loops, soft cap ~15-20 calls per session.
3. **Never assume a search hit is the right person.** LinkedIn search is fuzzy -- verify with current company, location, and headshot/title before propagating identity into a People note or CRM entry.

### Important Rules

4. **Stale-data awareness.** Profiles, job titles, and company headcounts change. Treat anything older than a few months as needing a refresh before acting on it (e.g., before drafting outreach that references a specific role).
5. **Cross-reference with People/ notes.** Whenever you pull a profile that matches a name in `/Users/alexhedtke/Exobrain/Areas/Relationships & Community/People/`, surface the connection -- that's a warm lead, not a cold one. Update the People note's `linkedin` frontmatter field if missing.
6. **Quote, don't paraphrase, for due diligence.** When using LinkedIn data to verify someone's role/company (e.g., for a recruiter outreach), quote the exact title and company verbatim rather than summarizing -- paraphrases drift.
7. **Inbox reads are private.** Alex's inbox content is private even by Exobrain standards. Never commit inbox text to the repo, surface message bodies in shared logs, or paste them into briefings without Alex confirming he wants them there.

## Common Patterns

### Find a hiring contact at a target company (job-search mode 1, step 6)

```
1. get_company_profile(linkedin_url=<company>)              # confirm company, grab URN
2. get_company_employees(linkedin_url=<company>,
                         keywords="IT Manager")             # narrow by title
3. get_person_profile(<one promising URL>,
                      sections=[experience, contact_info])  # only on the best match
```

Then create a `/crm potential <name>` task with the role context -- never send through LinkedIn directly.

### Research a person mentioned in a Plaud transcript (CRM mode)

```
1. search_people(firstName=..., lastName=..., currentCompany=<URN if known>)
2. get_person_profile(<best match URL>)
```

Update the People/ note's frontmatter (`linkedin`, `current_role`, `current_company`) and append a dated entry under `## Mentions`. Do not auto-connect.

### Scan job listings (job-search source)

```
1. search_jobs(keywords="IT Manager", location="Remote US")
2. get_job_details(<promising URL>) for each candidate
3. Apply the verification protocol in /job-search step 3
```

Use this alongside Gmail job alerts, firm careers portals, and Greenhouse/Lever Boards APIs -- never as the sole source for declaring a role open.

## Integration with Other Skills

- **`/job-search`**: LinkedIn is one source of job listings (alongside email alerts, firm portals, ATS Boards APIs). Use `search_jobs` for discovery and `get_company_employees` to find hiring contacts on Strong-Fit roles.
- **`/crm`**: Profile enrichment for People/ notes, and finding warm-intro paths into companies.
- **`/daily-briefing`** and **`/evening-winddown`**: Do not call LinkedIn directly -- these skills are read-heavy on Gmail/calendar/Things 3, and adding LinkedIn calls inflates the bot-pattern risk for marginal value.

## Related Memory

- [[feedback_linkedin_mcp_read_only]] -- read-only rule with the original reasoning
- [[reference_linkedin_mcp]] -- server install details, auth, retired-Monid context
