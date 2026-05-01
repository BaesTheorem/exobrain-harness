---
name: job-search
description: Job search assistant — audit postings for fit, research companies/people, tailor ATS-compliant cover letters, and track weekly application volume via email confirmations. Use when the user shares a job posting, asks to write a cover letter, wants company research, asks "how many apps this week", "audit this role", "is this a good fit", "help me apply", "job search status", "application tracker", or mentions applying to jobs.
---

# Job Search

Alex is actively job hunting. This skill handles the full pipeline: evaluating fit, researching the company, tailoring cover letters, and tracking application volume.

**Weekly goal**: 10–20 applications submitted per week.
**Compensation floor**: see gitignored `Projects/Get new job/Claude Reference.md` for current floor. Do not report or recommend roles that list a salary below this threshold. If salary is unlisted, still include the role but flag the unknown comp.

## Resume Reference

**Resume PDF**: `/Users/alexhedtke/Documents/Exobrain/Alex_Hedtke_Resume.pdf`
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

3. **Verify the posting is still open** (stale leads waste Alex's time):
   - **Check multiple sources**: Check the firm's own careers portal AND the job board listing. Neither alone is definitive — some firms only post on third-party ATS systems.
   - **LinkedIn job ID age**: LinkedIn job IDs are roughly sequential. IDs in the 37xxxxx range are from 2023-2024; 41-42xxxxx range is late 2025; 43xxxxx+ is 2026. Old IDs are a red flag — corroborate with other signals.
   - **Cross-reference headcount**: Search for the job title + company on LinkedIn/ZoomInfo. If multiple people already hold that exact title, the role may be filled.
   - **Application portal test**: Click through to the actual application form. If it 404s, redirects to a general page, or says "no longer accepting applications," it's dead.
   - **Posting date**: Be skeptical of listings older than 60 days with no signs of refresh. Look for repost dates, "updated" indicators, or recent applicant activity.
   - **Triangulate**: Use at least 2 independent signals before reporting a role as open. One stale LinkedIn listing alone is not enough. But a listing on a live ATS portal with an active application form counts even if the firm's main website doesn't mention it.

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

## Job Hub Note — "Get new job"

**Path**: `/Users/alexhedtke/Documents/Exobrain/Projects/Get new job.md`

This note is the one-stop dashboard for all job hunting activity. **Every job-search action must append a log entry to this note** (after the existing Things 3 data / Notes section). Don't touch the existing task sections — only append below them.

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

1. **Tracker maintenance**: Read `[[Job Applications]]` at `/Users/alexhedtke/Documents/Exobrain/Projects/Job Search/Job Applications.md`. Search Gmail for new application confirmations and rejection emails since the last entry. Add new apps, update statuses for rejections/interviews, update totals.
2. **Weekly pace check**: Count apps submitted since Monday vs 10-20 goal. If behind mid-week, suggest time blocks from calendar gaps.
3. **Upcoming interviews**: Surface any job-related events from today's calendar.
4. **Return for briefing**: Only include in the briefing output if there's something notable — behind pace, interview today, or exceptional posting from the email scan. Otherwise silent.

## Proactive Behaviors

- During `/daily-briefing`, if it's midweek and Alex is behind on applications, flag it with suggested time blocks from calendar gaps
- When processing transcripts that mention job leads, companies, or networking contacts relevant to job search, surface them
- If Alex hasn't submitted any applications in 3+ days, mention it constructively in ad-hoc interactions
- Track which types of roles Alex applies to most — surface patterns that might help narrow or broaden the search
