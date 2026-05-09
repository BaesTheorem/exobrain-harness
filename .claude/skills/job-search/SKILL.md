---
name: job-search
description: Job search assistant — audit postings for fit, research companies/people, tailor ATS-compliant cover letters, and track weekly application volume via email confirmations. Use when the user shares a job posting, asks to write a cover letter, wants company research, asks "how many apps this week", "audit this role", "is this a good fit", "help me apply", "job search status", "application tracker", or mentions applying to jobs.
---

# Job Search

Alex is actively job hunting. This skill handles the full pipeline: evaluating fit, researching the company, tailoring cover letters, and tracking application volume.

**Weekly goal**: 10–20 applications submitted per week.
**Compensation floor**: see gitignored `Projects/Get new job/Claude Reference.md` for current floor. Do not report or recommend roles that list a salary below this threshold. If salary is unlisted, still include the role but flag the unknown comp.

## Resume Reference

**Resume PDF**: `/Users/alexhedtke/Exobrain/Alex_Hedtke_Resume.pdf`
Read the PDF at the start of any audit or cover letter to ensure you're working from the latest version.

**Key background**: Read the resume PDF at the path above at runtime to get current experience, skills, certifications, and leadership history. Do not hardcode resume details in this skill — the PDF is the source of truth and may be updated independently.

## Modes

### 1. Audit: `/job-search audit` (or paste a job posting)
When Alex shares a job posting URL or text, evaluate fit:

1. **Parse the posting** — extract: title, company, location/remote, salary (if listed), required qualifications, preferred qualifications, key responsibilities, tech stack, and any red flags (unrealistic requirements, vague scope, etc.)

2. **Fit assessment** — score against Alex's profile:
   - **Skills match**: Compare required/preferred qualifications against Alex's background (check resume if available, plus known priorities: Sec+, AZ-900, MD-102, AI governance, technical project work)
   - **Priority alignment**: Does this role align with Alex's current priorities and career direction?
   - **Growth potential**: Does it offer upskilling or advancement in areas Alex cares about?
   - **Red flags**: Unreasonable requirements, high turnover signals, MLM/scam indicators, "unicorn" postings (wanting 10 years experience for entry pay), mismatched seniority

3. **Verify the posting is still open** (stale leads waste Alex's time — and 2026-05-08 showed they happen often):

   **CRITICAL — these signals do NOT prove a listing is open:**
   - The careers page renders without error
   - The LinkedIn job ID is recent (43xxxxx+)
   - The role is cross-listed on aggregators (Built In, Himalayas, RemoteRocketship, Glassdoor, Indeed, ZipRecruiter, etc.)
   - The company has many other open jobs
   - The careers index lists the role
   - Recent "posted X days ago" labels on aggregator mirrors
   - **The full job description renders intact when Alex pastes it** (some ATS systems, notably UltiPro, render expired postings with the complete JD content and no visible expiry banner — the expiry date is in metadata only). Discovered 2026-05-08 with Husch Blackwell: posting expired 2026-04-28 but the listing page still rendered the full JD ten days later, fooling both an automated agent and Alex's direct visual check.

   These all persisted on closed roles in 2026-05-08 verification (4 of 5 initially-promoted Tier 1 roles were actually closed on direct check, including one — Husch Blackwell — where Alex pasted the full JD believing it was open). The signals above prove the listing PAGE EXISTS, not that it ACCEPTS APPLICATIONS.

   **Always check explicit posting/expiry date metadata.** Look for:
   - "Posted on" / "Date posted" labels (anything >30 days old without a refresh signal is a yellow flag)
   - Explicit "expires on" or "deadline" labels
   - "Job is open for no less than N days" language (Netflix uses this — strong positive signal of an active window)
   - For UltiPro specifically: there is often an expiry date buried in the URL parameters or metadata; if you can't find one and the role is older than 30 days, treat as suspect.

   **The ONLY definitive signal: load the apply flow and confirm a working submission form.**

   For each candidate role, agents must:
   - Click through to the apply URL (not the listing URL — the application/submission URL).
   - Confirm the page returns a usable application form: input fields for name/email/resume upload, a working "Submit" button, no banner saying "no longer accepting applications" or "position filled" or "closed."
   - For ATS systems (Greenhouse, Lever, Ashby, Workday, iCIMS, Rippling), navigate the "Apply" button to the actual form and verify it loads.
   - If the apply button redirects to the careers homepage, an error page, a "thanks for your interest" page, or a 404, the role is closed.

   If the apply flow cannot be confirmed via WebFetch (JavaScript-heavy SPAs may not render server-side), explicitly flag the role as **"verification incomplete — Alex must spot-check the apply form before any package work."** Do NOT promote the role into Tier 1-3 until Alex has confirmed.

   **Other useful signals (corroborating only, never sufficient on their own):**
   - Click through to the actual application form. If it 404s, redirects to a general page, or says "no longer accepting applications," it's dead.
   - LinkedIn job ID age (37xxxxx = 2023-2024; 41-42xxxxx = late 2025; 43xxxxx+ = 2026). Old IDs are a red flag.
   - Cross-reference headcount: if multiple people already hold the exact title, the role may be filled.
   - Posting date >60 days old without refresh indicators is a red flag.

   **Strongest positive verification path (use whenever possible):**
   - Greenhouse: hit the Boards API directly at `https://boards-api.greenhouse.io/v1/boards/<board>/jobs/<id>`. A 200 with content body = open. A 404 = closed. The user-facing `job-boards.greenhouse.io/<board>/jobs/<id>` URL silently redirects to the company index page when a posting is closed, which is misleading.
   - Lever: `api.lever.co/v0/postings/<board>` returns the live JSON list of open postings.
   - Workable: individual job pages are JS-rendered and only return metadata to WebFetch — flag for Alex spot-check.
   - UltiPro: browser-blocks bot fetchers AND renders expired postings with full content. Always look for an explicit "posted" or "expires" date in the listing — if absent and >30 days from posting, treat as suspect.

   **Reporting**: When agents return verified-open roles, the verification_signals frontmatter must include the apply-form check explicitly: e.g., "Apply form loaded successfully on Greenhouse 2026-05-08 with active Submit button." If the apply form check was not performed, the role is "verification incomplete" — not "verified open."

4. **Output a fit report**:
   ```
   ## [Job Title] — [Company]
   **Location**: [location] | **Salary**: [if listed]
   **Apply here**: [direct link to posting]
   **Status**: [Verified open / Possibly filled / Unable to verify]

   ### Fit Score: [Strong Fit / Moderate Fit / Weak Fit / Skip]

   **Matches**:
   - [Bullet each matching qualification with Alex's relevant experience]

   **Gaps**:
   - [Bullet each gap — note if it's learnable vs. hard blocker]

   **Red Flags**:
   - [Any concerns]

   **Verdict**: [1-2 sentence recommendation: apply, apply with caveats, or skip with reason]
   ```

5. If the verdict is "apply" or "apply with caveats," ask if Alex wants a cover letter and/or company research.

6. **Cold outreach trigger** (Strong Fit only, especially when compensation and remote opportunity are both good):
   - **LinkedIn people search** (via Monid CLI): Find the hiring manager, team lead, or department head at the company:
     `monid run -p apify -e /harvestapi/linkedin-company-employees --input '{"companies": ["https://www.linkedin.com/company/COMPANY"], "profileScraperMode": "Short ($4 per 1k)", "maxItems": 5, "jobTitles": ["IT Manager", "Hiring Manager", "IT Director", "CISO"]}'`
   - Cross-reference results against Alex's People/ notes and CRM for warm intro paths
   - Create Things 3 tasks for cold outreach via `/crm potential [name]` for each identified person, with context about the role and why reaching out matters
   - Include in the task notes: the role title, why it's a strong fit, LinkedIn profile URL, and a suggested outreach angle
   - This is highest priority when the role offers strong compensation AND remote/hybrid flexibility — that combination warrants extra effort beyond just submitting an application

### 1b. Bulk Scan: `/job-search scan [list of companies]`
When Alex provides a list of companies to investigate for open positions:

1. **Search each company's careers page** and major job boards for IT/technology openings
2. **Filter for fit**: Only report roles that are a plausible match for Alex's skills and experience. Skip roles that are clearly out of scope (e.g., senior developer requiring 5+ years of Python, DBA requiring Oracle expertise, CISO-level roles requiring 15+ years management). Use the resume reference above as the baseline.
3. **Verify each posting is still open** (same rules as mode 1, step 3):
   - Check multiple sources — firm's careers portal AND job board listings. Triangulate with at least 2 signals.
   - Cross-reference LinkedIn job ID age (37xxxxx = 2023-2024; 43xxxxx+ = 2026). Old IDs are a red flag.
   - Search for people already holding the title at that firm — multiple holders suggests it's filled.
   - Click through to the application form to confirm it's live and accepting submissions.
   - Be skeptical of listings older than 60 days with no signs of refresh.
4. **Every reported role MUST include**:
   - Job title and company
   - Location (and remote/hybrid status)
   - Salary if listed (flag if below $75K floor; omit if unlisted but note it)
   - A direct link to the posting — preferably the firm's own careers portal, not just a job board mirror
   - A brief fit assessment (1-2 lines: why it matches, any notable gaps)
   - Verification method (e.g., "confirmed on firm portal 2026-04-01" or "LinkedIn ID 43xxxxx, posted March 2026")
5. **Do NOT report** roles that score "Weak Fit" or "Skip" — only surface roles worth Alex's time (Strong or Moderate fit)
6. **Do NOT report** roles that cannot be verified as currently open — list them in a brief "Stale/Filled" section at the end for awareness only
7. Group results by fit strength, with strongest matches first

### 2. Research: `/job-search research [company]`
Deep-dive on a company before applying:

1. **Company overview**: What they do, size, funding stage, recent news
2. **Culture signals**: Glassdoor themes, LinkedIn presence, tech blog, open-source contributions
3. **Key people** (via Monid CLI LinkedIn endpoints):
   - Search for hiring manager / team lead / department head: `monid run -p apify -e /harvestapi/linkedin-company-employees --input '{"companies": ["https://www.linkedin.com/company/COMPANY"], "profileScraperMode": "Short ($4 per 1k)", "maxItems": 10, "jobTitles": ["IT Manager", "Hiring Manager", "IT Director", "CISO", "Security Manager"]}'`
   - For specific people by name: `monid run -p apify -e /harvestapi/linkedin-profile-search-by-name --input '{"profileScraperMode": "Short", "firstName": "...", "lastName": "...", "currentCompanies": ["https://www.linkedin.com/company/COMPANY"]}'`
   - Poll results: `monid runs get --run-id <id> --wait`
   - Always prepend `export PATH="$HOME/.local/bin:$PATH" && NO_COLOR=1` to monid commands
   - Check Alex's People/ notes and CRM for any existing connections at the company
4. **Network angle**: Check if anyone in Alex's network works there or has connections (search People/ notes, CRM digest). Cross-reference Monid LinkedIn results against People/ notes for mutual connections. A warm intro is 10x more valuable than a cold app
5. **AI/tech stance**: For tech roles, note the company's position on AI, security, governance (relevant to Alex's interests)
6. **Interview intel**: Any publicly available interview process info (Glassdoor, Blind, etc.)

Output a briefing, then run `/verify` as a background agent to fact-check claims.

### 3. Cover Letter: `/job-search cover-letter`
Generate an ATS-compliant, tailored cover letter:

**ATS Compliance Rules** (apply to ALL cover letters):
- Plain text formatting — no tables, columns, headers/footers, images, or special characters
- Standard section structure: contact info, date, greeting, body paragraphs, sign-off
- Use keywords and phrases directly from the job posting (ATS keyword matching)
- Spell out acronyms on first use, then abbreviate (e.g., "Application Tracking System (ATS)")
- Standard fonts implied (the content itself should not rely on formatting to convey meaning)
- No fancy bullet characters — use standard dashes or asterisks if needed
- Keep to one page (~300-400 words)

**Tailoring Process**:
1. Extract the top 5-7 keywords/phrases from the job posting (these are what ATS scans for)
2. Map each to a concrete example from Alex's experience
3. Mirror the company's language and values (from research if available)
4. Structure:
   - **Opening**: Specific role + company name + why this role specifically (not generic)
   - **Body 1**: Strongest qualification match with a concrete achievement/example
   - **Body 2**: Secondary match + how Alex's unique background (AI governance, security upskilling, technical projects) adds value beyond the basic requirements
   - **Body 3** (optional): Culture/mission alignment if the company has clear values
   - **Closing**: Enthusiasm + availability + call to action
5. Run through `/de-ai` principles — the letter must sound like a real human, not ChatGPT. No "I am writing to express my interest," no "I am excited to leverage my synergies," no corporate fluff. Alex's voice: direct, genuine, slightly informal, knowledgeable.

**Output**: The cover letter text, plus a list of ATS keywords embedded and where they appear.

### 4. Tracker: `/job-search status`
Weekly application tracking via email confirmations:

1. Search Gmail for application confirmation emails from the past 7 days:
   ```
   gmail_search_messages with queries like:
   - "application received" OR "application confirmed" OR "thank you for applying"
   - "we received your application" OR "application submitted"
   - "your application for" OR "successfully applied"
   ```
2. Parse each confirmation for: company name, role title, date applied
3. Cross-reference against previous tracker entries to avoid double-counting
4. Present a weekly summary:
   ```
   ## Application Tracker — Week of [date]
   **Total this week**: [N] / 10-20 goal
   **Status**: [On track / Behind / Ahead]

   | # | Company | Role | Date Applied | Source |
   |---|---------|------|-------------|--------|
   | 1 | [Co]    | [Role] | [Date]    | [Email subject] |
   ...

   **Pace check**: [If behind, calculate how many per remaining days to hit 10]
   ```
5. Append the summary to today's daily note under a `## Job Search` section
6. Append the same summary to the job hub note (`Projects/Get new job.md`) under `## Job Search Log` as a dated `Applications` entry
7. If behind pace (fewer than ~1.5/day average to hit 10), flag it proactively

### 5. Full Pipeline: `/job-search apply [URL or pasted posting]`
Runs modes 1→2→3 in sequence:
1. Audit the posting for fit
2. If fit is "Strong" or "Moderate," automatically research the company
3. Generate a tailored cover letter
4. Surface any network connections at the company
5. Create a Things 3 task: "Apply to [Role] at [Company]" with the cover letter and research in the notes field. If routing to a project (e.g., "Job hunting"), verify the project has an Obsidian backlink in its notes field (`obsidian://open?vault=Exobrain&file=Projects/...`). If missing, add it via `update_project`.

## Per-Listing Notes & Bases Tracker (canonical)

**Folder**: `/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings/`
**Bases file**: `/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings.base`

Every researched, audited, or scanned job listing **MUST get a dedicated note** in the Job Listings folder. The `.base` file aggregates them into a checkable tracker. This is the canonical surface — not the hub-note tables, which are dated snapshots that drift.

### When to create or update a listing note

- `/job-search audit`: create a note for every audited posting (any verdict — Strong, Moderate, Weak, or Skip; status reflects the verdict)
- `/job-search scan`: create a note for every reported role (skip the dead/aggregator section)
- `/job-search apply`: create a note as part of the pipeline; set `applied: true` + `application_date` when Alex confirms submission
- `/job-search research`: update the contact, posted date, verification status on the existing note (or create one if research preceded an audit)
- Alex says "I applied to X": set `applied: true`, `application_date: <today>`, `status: applied`

### Note location and naming

- Folder: `Projects/Get new job/Job Listings/`
- Filename: `<Company> - <Role>.md` (e.g., `Nerdio - Support Solutions Engineer AMER MSP.md`). If a company has multiple roles, list them as separate files. Strip illegal filename characters.

### Frontmatter schema (REQUIRED)

```yaml
---
type: job-listing
company: <string>
role: <string>
status: candidate          # candidate | applied | interviewing | rejected | offer | withdrawn | closed
applied: false             # boolean — used as the .base checkbox
tier: 1                    # 1 (top priority) → 5 (worth a flyer); 99 = skip
fit: strong                # strong | moderate | stretch | skip
comp_min: 65000            # USD/yr; null if unlisted
comp_max: 80000            # USD/yr; null if unlisted
comp_listed: true
remote: true
location: "Remote US"
apply_url: "https://..."
contact: "Dan Diaz, Sr Technical Recruiter"
contact_url: "https://linkedin.com/in/..."
verified: true             # boolean — survived 2-signal verification
verification_signals: "Live on Rippling ATS; LinkedIn job ID 43xx; application form active"
posted: 2026-05-08         # date the listing was first surfaced or research was done
application_date:          # date Alex submitted; null until applied
rejection_date:            # date a rejection was received; null otherwise
last_research: 2026-05-08
source: rippling-ats       # short tag: greenhouse, lever, ashby, workday, icims, rippling, linkedin, indeed, etc.
---
```

Truthful nulls: omit `comp_min` / `comp_max` if unlisted (set `comp_listed: false`); leave `application_date` blank until Alex submits.

### Note body (concise, Alex-readable)

```markdown
# <Company> — <Role>

**Apply**: [<URL>](<URL>)

## Snapshot
- **Comp**: <range or "unlisted">
- **Location**: <details, remote/hybrid posture>
- **Tier**: <1-5> — **Fit**: <strong/moderate/stretch>
- **Status**: <verified-open / possibly stale / etc.>
- **Verified via**: <signals>

## Why this fits
- <2-4 bullets mapping JD requirements to Alex's experience>

## Gaps
- <2-3 bullets — concede honestly, note learnable vs hard blocker>

## Highest-impact contact
**<Name>**, <Title> — [<LinkedIn>](<URL>)
<1-2 sentence outreach angle>

## ATS keywords
<comma-separated list of the top JD keywords this role hits>

## Notes
<freeform — interview prep, follow-up reminders, cold-outreach status, etc.>
```

### Bases file conventions

The `.base` lives at `Projects/Get new job/Job Listings.base` (sibling of the folder, not inside). It must filter on `file.inFolder("Projects/Get new job/Job Listings")` and `type == "job-listing"`. Standard views to include:

- **Active**: `applied == false AND status != "closed" AND status != "withdrawn"`, sorted by tier ASC then fit
- **Applied**: `applied == true`, sorted by `application_date` DESC
- **By Tier**: grouped by `tier`, sorted by `fit` then `company`
- **Strong Fits**: `fit == "strong"`, sorted by tier ASC

The `applied` boolean is the inline checkbox in the Bases table view — flipping it updates the note's `applied` frontmatter property in place. Obsidian Bases is a view layer with no property-trigger automation, so flipping the checkbox does NOT directly cascade to other fields. The cascade is handled by a launchd file watcher in the Exobrain harness:

- **Watcher**: `com.exobrain.job-listings-sync` (plist at `~/Library/LaunchAgents/`)
- **Script**: `Exobrain harness/job-listings-sync/reconcile.py`
- **Trigger**: file changes in `Projects/Get new job/Job Listings/` + 5-minute periodic safety net
- **Logic**:
  - `applied=true` AND `status=candidate` (the "checkbox just flipped" case) → set `status=applied` and stamp `application_date=<today>` if empty
  - `status=rejected` AND no `rejection_date` → stamp `rejection_date=<today>`
  - All other states are left alone (avoids back-stamping migrated records or interviewing-stage roles with today's date)

When Alex says "I applied to X" in conversation, Claude can update the frontmatter directly with the same logic. The watcher will then no-op since the state is already correct (the script is idempotent).

For interviewing/offer/withdrawn transitions, Alex updates `status` manually — the watcher does not infer those state changes.

## Job Hub Note — "Get new job"

**Path**: `/Users/alexhedtke/Exobrain/Projects/Get new job.md`

This note is the one-stop dashboard for all job hunting activity. **Every job-search action must append a log entry to this note** (after the existing Things 3 data / Notes section). Don't touch the existing task sections — only append below them.

**Relationship to per-listing notes**: the hub note holds dated narrative log entries (research dives, cover letter text, networking touches). The Job Listings folder + `.base` file holds the live, queryable, checkable tracker. Both are canonical for different purposes — keep them in sync but don't duplicate. Hub-note tables are snapshots; the `.base` is the live source.

### What to log (append under a `## Job Search Log` section, most recent first):

- **Application tracker** (`/job-search status`): Append the weekly summary table with counts and pace check
- **Audits** (`/job-search audit`): Append a compact entry — role, company, fit score, verdict, link to posting
- **Cover letters** (`/job-search cover-letter`): Append the full cover letter text under a dated sub-heading with the role/company
- **Company research** (`/job-search research`): Append key findings — company overview, culture signals, network angles, interview intel
- **Full pipeline** (`/job-search apply`): Append the complete pipeline output (audit + research + cover letter) as one dated entry
- **Upskilling milestones**: When cert study sessions are completed, exams passed, or training attended, log it (e.g., "Completed AZ-900 Virtual Training Day Part 2")
- **Interview activity**: Any interview scheduling, prep, or outcomes
- **Networking for job search**: Cold outreach sent, warm intros made, informational interviews conducted

### Log entry format:
```markdown
### [YYYY-MM-DD] [Type]: [Brief description]
[Content — tables, summaries, cover letters, etc.]
```

Types: `Applications`, `Audit`, `Cover Letter`, `Research`, `Pipeline`, `Upskilling`, `Interview`, `Networking`

## Integration with Other Skills

- **`/daily-briefing`**: Include application count for the current week and pace check. Log daily app count to the job hub note.
- **`/weekly-review`**: Full application tracker summary, trends, and suggestions for next week's targets. Append the weekly job search summary to the job hub note.
- **`/crm`**: Cross-reference company employees with Alex's network for warm intros. For Strong Fit roles (especially high comp + remote), auto-create `/crm potential` tasks for cold outreach to relevant people at the company
- Ad-hoc questions like "how's my job search going?" can be answered via tracker mode
- **`/verify`**: Background fact-check on company research claims
- **`/de-ai`**: Applied to all cover letter output to ensure human voice
- **`/evening-winddown`**: Include daily application count in the recap

## Daily Briefing

When called as part of the daily briefing (weekdays only — skip on weekends):

1. **Tracker maintenance**: The canonical tracker is the `Job Listings` Bases file at `/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings.base` plus the per-listing notes in `Projects/Get new job/Job Listings/`. Search Gmail for new application confirmations and rejection emails since the last entry. For each new confirmation: if a listing note already exists for that company+role, set `applied: true`, `status: applied`, and `application_date: <today>`. If no note exists, create one per the schema in the "Per-Listing Notes & Bases Tracker" section above. For rejections: set `status: rejected` and `rejection_date: <date>`.
2. **Weekly pace check**: Count apps submitted since Monday vs 10-20 goal. If behind mid-week, suggest time blocks from calendar gaps.
3. **Upcoming interviews**: Surface any job-related events from today's calendar.
4. **Return for briefing**: Only include in the briefing output if there's something notable — behind pace, interview today, or exceptional posting from the email scan. Otherwise silent.

## Proactive Behaviors

- During `/daily-briefing`, if it's midweek and Alex is behind on applications, flag it with suggested time blocks from calendar gaps
- When processing transcripts that mention job leads, companies, or networking contacts relevant to job search, surface them
- If Alex hasn't submitted any applications in 3+ days, mention it constructively in ad-hoc interactions
- Track which types of roles Alex applies to most — surface patterns that might help narrow or broaden the search
