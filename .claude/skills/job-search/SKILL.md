---
name: job-search
description: Job search assistant — audit postings for fit, research companies/people, tailor ATS-compliant cover letters, and track weekly application volume via email confirmations. Use when the user shares a job posting, asks to write a cover letter, wants company research, asks "how many apps this week", "audit this role", "is this a good fit", "help me apply", "job search status", "application tracker", or mentions applying to jobs.
---

# Job Search

Alex is actively job hunting. This skill handles the full pipeline: evaluating fit, researching the company, tailoring cover letters, and tracking application volume.

**Weekly goal**: 10–20 applications submitted per week.
**Compensation floor**: see gitignored `Projects/Get new job/Claude Reference.md` for current floor. Do not report or recommend roles that list a salary below this threshold. If salary is unlisted, still include the role but flag the unknown comp.

## Sources of Job Listings

Use multiple sources and triangulate — no single source is authoritative for "open and accepting applications." **Don't lean on a single source** — title-only LinkedIn search misses listings on firm-careers portals and ATS boards that don't crosspost, and misses responsibility-matching roles whose titles wouldn't make the title pre-filter.

1. **Gmail job alerts** (Indeed, LinkedIn, Dice, ZipRecruiter) — see `/email` for query syntax. Read full email bodies; dedupe across sources.
2. **LinkedIn MCP** (`mcp__linkedin__search_jobs`, `get_job_details`) — see `/linkedin` for read-only rules and pacing. Good for discovery by keyword + location, and for cross-checking listings found elsewhere. Also the source for hiring-contact lookup (`get_company_employees`) on Strong-Fit roles.
3. **Google search via WebSearch** (NEW — added 2026-05-19 after Alex flagged LinkedIn-only blind spot):
   - **X-ray search ATS boards**: `site:boards.greenhouse.io "<keyword>" remote`, `site:jobs.lever.co "<keyword>" remote`, `site:jobs.ashbyhq.com "<keyword>" remote`, `site:apply.workable.com "<keyword>" remote` — these often surface listings not crossposted to LinkedIn
   - **Niche remote job boards**: `site:remoterocketship.com`, `site:himalayas.app`, `site:builtin.com`, `site:weworkremotely.com`, `site:remotive.com` — different employer mix
   - **Firm careers portals**: search by responsibility keyword without site filter to surface direct-to-employer postings (`"phishing remediation" "remote" careers`)
   - **Search by JD responsibility keywords, NOT just titles** (the killer feature — see "Responsibility-keyword search" below). Alex's title-only filter misses roles whose JDs match his daily work but whose titles he'd otherwise skip.
4. **Firm careers portals direct** — the firm's own site is the most reliable signal that a role is still open. Cross-check aggregator hits against the firm portal.
5. **ATS Boards APIs** (Greenhouse, Lever) — strongest positive verification path. See mode 1 step 3 below for direct API URLs.
6. **Alex-provided URLs and pasted postings** — treat as a starting point, still run the audit + verification.
7. **80,000 Hours job board** (https://jobs.80000hours.org) — ALWAYS include in every search (Alex standing instruction 2026-06-17). Aggregates high-impact roles at EA / AI-safety / AI-policy orgs that don't crosspost to LinkedIn or mainstream ATS. Use the board's role-type + location filters; surface ops / IT / security / compliance / analyst roles (US/remote), not just research. Connects to Alex's EA / AI-governance pivot track.

### Specific employer boards to watch (warm-connection lane)

Some employers get scanned directly on every discovery pass because Alex has an inside referral path there — a warm intro is worth more than cold volume, so these clear a lower bar than the open market. **The specific employers, their careers-portal URLs, the referral context, and any per-employer gate exceptions live in the gitignored `Projects/Get new job/Claude Reference.md` under "Warm-Connection Watch Lane" — read it at the start of every scan and scan each firm listed there on top of the open-market search.** Employer identities and referral details are kept out of this file because the repo is public.

Generic handling for this lane:
- Scan each listed firm's careers portal every discovery pass, in addition to the open-market boards. Apply the per-firm filtering notes from the reference (which roles to target, which org areas / locations to skip).
- A firm in this lane may carry a **documented remote-gate exception**: if the reference marks it as a warm-referral hybrid opt-in (Alex in-metro, no relocation, comp confirmed), do NOT auto-DQ its roles for being hybrid/in-office — still apply the other three gates (full-time permanent, comp ≥$75K or strong inference, ≥80% strong fit) normally. Exceptions are per-firm and per-connection; they don't generalize to other hybrid employers. Watch the actual reporting location — an "onsite" role reporting to an out-of-state project site is relocation, not local-hybrid; flag those.

### Responsibility-keyword search (the title-blind-spot fix)

Don't limit search keywords to titles like "IT Analyst" / "Security Analyst" / "GRC Analyst". Use **responsibility phrases** from Alex's actual day-to-day work, because employers describe roles in JD bullets even when the title is unusual. From the Claude Reference, Alex's transferable responsibility keywords:

- **Identity & Access**: "Entra ID security groups", "Azure AD group management", "access provisioning", "access reviews", "SSO/MFA configuration", "IAM provisioning"
- **Phishing & Email Security**: "phishing email analysis", "phishing remediation", "Exchange message trace", "compromised account response", "phishing triage"
- **Endpoint & Device**: "Microsoft Intune", "endpoint security", "lost/stolen device triage", "device wipe", "device lifecycle"
- **Cloud & Virtual Desktop**: "Azure Virtual Desktop support", "AVD support", "Citrix Virtual Desktop support", "M365 administration", "Microsoft 365 admin"
- **Cross-timezone IT**: "global IT support", "cross-timezone IT", "SLA-driven IT support", "follow-the-sun support"
- **Legal-tech (law firm angle)**: "iManage", "Elite 3E", "Intapp", "law firm IT"
- **Frameworks (GRC angle)**: "NIST CSF", "NIST AI RMF", "SOC 2 evidence", "vendor risk assessment", "phishing simulation"
- **Current title fair game**: "IT Analyst" — Alex's current title, common at law firms and mid-market enterprises

These responsibility searches surface listings titled things like "Information Security Engineer", "Identity Administrator", "Endpoint Specialist", "Risk Analyst", "IT Coordinator" — where the JD responsibilities map 80%+ to Alex's work even though the title would normally be filtered.

**Title pre-filter caveat**: the LinkedIn-search-result title pre-filter (drop Senior/Sr/Lead etc.) applies only when reading LinkedIn search snippets *before* JD reads — to save MCP budget. For Google/WebSearch results, each search result IS a JD page, so read it directly and evaluate by the 4-gate filter without pre-screening titles.

## Resume Reference

**Resume PDF**: `/Users/alexhedtke/Exobrain/Projects/Get new job/Alex_Hedtke_Resume.pdf`
Read the PDF at the start of any audit or cover letter to ensure you're working from the latest version.

**Key background**: Read the resume PDF at the path above at runtime to get current experience, skills, certifications, and leadership history. Do not hardcode resume details in this skill — the PDF is the source of truth and may be updated independently.

## Resume + Cover Letter Generation (use the builder)

Do NOT hand-build resume/cover-letter HTML per JD anymore. Use the reusable builder at `Exobrain harness/resume-builder/` (see its README):

**Artifact output location (standing rule, Alex 2026-06-24, broadened 2026-07-15): stash every generated artifact — resume, cover letter, interview prep doc, research — in the listing's own folder, NOT in `~/Downloads/` or loose in the project root.** Each job we apply to or build ANY artifact for gets a dedicated folder at `Projects/Get new job/Job Listings/<Company> - <Role>/` that holds the listing note plus all its artifacts (PDFs, interview prep `.md`s, research `.md`s) (see "Per-Listing Notes" below for the folder-promotion mechanics). Pass the builder's `--out` flag to write straight into that folder. Keep the human filename (`Alex_Hedtke_Resume_<Tag>.pdf` / `Alex_Hedtke_Cover_Letter_<Tag>.pdf`) — it's part of the ATS defense and is what Alex uploads. Do not also leave a copy in Downloads.

- **Tailored resume**: write a surgical `tailoring/<company>.json` (overrides: `summary`, `skills_append` per row, `experience_bullets` per job id `clyde`/`geeksquad`), then `python3 build.py resume --tailor tailoring/<company>.json --out "/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings/<Company> - <Role>/Alex_Hedtke_Resume_<Tag>.pdf"`.
- **Cover letter**: write the letter body (date line down) to a `.md`, run `/de-ai` on it, then `python3 build.py cover --md <file>.md --company "<Name>" --tag <Tag> --out "/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings/<Company> - <Role>/Alex_Hedtke_Cover_Letter_<Tag>.pdf"`.
- The builder's `tailoring/*.json` and `*.md` inputs stay in the harness repo (gitignored); only the rendered PDF outputs go to the listing folder in the vault.
- Canonical resume content lives in `resume-builder/data/resume_data.json` (source of truth). Tailoring rules are still surgical-only per [[Claude Reference]]; the builder does not relax them.
- The builder bakes in the document-side ATS / AI-screening defenses (clean metadata, selectable single-column text, human filename, no Skia/Chrome fingerprint). The **prose** defense is still yours: run `/de-ai` on every tailored summary/bullet and cover letter. Full rationale: [[ATS & AI-Screening Playbook]] (`Projects/Get new job/`). Read it before tailoring.

## Contact Research (MANDATORY for every qualifying JD)

For **every** posting that clears the 4 hard gates (not just Strong Fits), research the people around the role and record them on the listing note. This is required at audit time, in scan mode, in the apply pipeline, and in the daily-briefing scan — any time a listing note is created or promoted. Read `/linkedin` first (READ-ONLY, human-paced; never send or connect). For each qualifying JD, identify and capture:

1. **Recruiter(s) / Talent Acquisition** — esp. anyone covering IT/security/technical reqs. `get_company_employees` filtered by ("recruiter" OR "talent").
2. **Hiring manager (and the chain above)** — IT/Security Manager, IT Director, Information Security Manager, CISO, or whoever the role reports into. At smaller orgs security often rolls up under IT Infrastructure/Operations — note that.
3. **Same-role employees** — current people holding the same/similar title (signals team size and whether the seat is net-new).
4. **Likely teammates** — others on the IT/Security/Infrastructure team Alex would work alongside.

Method: `search_companies` to confirm the company URN (disambiguate look-alikes), then `get_company_employees` across a few title-keyword passes, then `get_person_profile` to enrich the top ~3-5. Cross-reference every name against Alex's People/ notes (`Areas/Relationships & Community/People/`) and CRM for warm-intro paths. Record findings in the listing note: fill `contact` / `contact_url` frontmatter with the single highest-impact target, and list the rest under `## Highest-impact contact` (rename to "## People around this role" when there are several) with **Name | Title | LinkedIn | why-relevant**. For Strong-Fit roles (esp. high comp + remote), continue to mode 1 step 6 (draft outreach + `/crm potential` tasks). For weaker-but-qualifying roles, capturing the contacts on the note is enough — no outreach task required unless Alex asks.

If the LinkedIn MCP is unavailable, note "contact research pending (LinkedIn MCP unavailable)" on the listing and fall back to the company careers page / company LinkedIn.

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
   - **LinkedIn people search** (via `linkedin` MCP — read `/linkedin` for read-only rules and pacing): Find the hiring manager, team lead, or department head at the company. Use `get_company_employees` with the company LinkedIn URL and a keyword filter for titles like "IT Manager", "Hiring Manager", "IT Director", "CISO". Pull richer detail on individuals with `get_person_profile`. Draft any outreach as text for Alex to send manually — never send through the MCP.
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
3. **Key people** (via `linkedin` MCP — see `/linkedin` for full conventions; read-only, paced like a human):
   - Search for hiring manager / team lead / department head: `get_company_employees` with the company LinkedIn URL and a keyword filter for titles like "IT Manager", "Hiring Manager", "IT Director", "CISO", "Security Manager".
   - For specific people by name: `search_people` with `firstName`/`lastName` and `currentCompany` set to the target company. Use `get_person_profile` to enrich a known profile URL.
   - Check Alex's People/ notes and CRM for any existing connections at the company
4. **Network angle**: Check if anyone in Alex's network works there or has connections (search People/ notes, CRM digest). Cross-reference LinkedIn MCP results against People/ notes for mutual connections. A warm intro is 10x more valuable than a cold app
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

**Output**: The cover letter text, plus a list of ATS keywords embedded and where they appear. After Alex approves the text, generate the PDF via the builder (`build.py cover --md ... --company ... --tag ...` with `--out` pointed at the listing's folder `Job Listings/<Company> - <Role>/`, see "Resume + Cover Letter Generation" above) so it lands in that folder with clean metadata, NOT in `~/Downloads/`. Generate a tailored resume alongside it (`build.py resume --tailor ...`) whenever the role meaningfully benefits per [[Claude Reference]].

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

- Base folder: `Projects/Get new job/Job Listings/`
- **Plain listing (scanned/candidate, no artifacts, not applied)**: a flat note `Job Listings/<Company> - <Role>.md` (e.g., `Nerdio - Support Engineer.md`). If a company has multiple roles, list them as separate files. Strip illegal filename characters.
- **Active listing (we built ANY artifact for it, or applied)** — folder convention (Alex 2026-06-24, broadened 2026-07-15): the moment we create *any* artifact for a listing — tailored resume, cover letter, **interview prep doc**, company/interviewer **research**, notes, anything — promote it to its own dedicated folder `Job Listings/<Company> - <Role>/` and put **everything** for that role inside: the note `<Company> - <Role>.md` PLUS every artifact (resume + cover letter PDFs, interview prep `.md`s, research `.md`s). Do NOT scatter interview prep or research loose in `Projects/Get new job/` or the Job Listings root. When promoting an existing flat note, move the `.md` into the new same-named folder. This keeps everything for one application in one place. (One folder per role; a separate declined/inactive role at the same company keeps its own flat note or folder.)
- The Bases tracker is unaffected by the flat-vs-folder split: its filter `file.inFolder("Projects/Get new job/Job Listings")` is **recursive** (matches subfolders), and the `file.ext == "md"` + `type == "job-listing"` clauses exclude the PDFs, so artifacts never pollute the table and foldered notes still aggregate. Wikilinks resolve by basename, so `[[<Company> - <Role>]]` keeps working after a note moves into its folder.

### Frontmatter schema (REQUIRED)

```yaml
---
type: job-listing
company: <string>
role: <string>
status: candidate          # candidate | applied | interviewing | rejected | offer | withdrawn | closed
applied: false             # boolean — used as the .base checkbox
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

> [!info]- Raw JD (archived verbatim)
> <source URL + archive date>
>
> <the FULL job description text, copied verbatim, every line prefixed with `> `>
```

**Always archive the full raw JD inline.** Postings get pulled, ATS pages 404, and recruiter screens happen weeks after the listing disappears (Nerdio 2026-06-02: original Rippling page was down by interview day; had to recover the JD from a Built In mirror). At create/audit time, copy the complete posting text verbatim into a **collapsible callout** (`> [!info]- Raw JD (archived verbatim)`) at the bottom of the listing note — intro/about, all responsibilities, required + preferred qualifications, comp, benefits. The `-` after the callout type makes it collapsed by default so it doesn't clutter the note. Do not summarize or trim; the "Why this fits" / "Gaps" bullets are the summary, this callout is the source of truth. Lead the callout with the source URL and archive date. Keep it **inline in the listing note** — do not split it into a sibling file.

### Bases file conventions

The `.base` lives at `Projects/Get new job/Job Listings.base` (sibling of the folder, not inside). It must filter on `file.inFolder("Projects/Get new job/Job Listings")` and `type == "job-listing"`. Standard views to include:

- **Active**: `applied == false AND declined != true AND status not in (closed, withdrawn, rejected)`, sorted by comp DESC
- **Applied**: `applied == true`, sorted by `application_date` DESC
- **All**: ungrouped, all listings, sorted by file.name ASC

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
- **`/linkedin`**: Canonical reference for the LinkedIn MCP. READ-ONLY — discovery and lookup only, never send messages or connection requests. Used as one source of job listings (`search_jobs`, `get_job_details`) and for hiring-contact identification (`get_company_employees`)
- Ad-hoc questions like "how's my job search going?" can be answered via tracker mode
- **`/verify`**: Background fact-check on company research claims
- **`/de-ai`**: Applied to all cover letter output to ensure human voice
- **`/evening-winddown`**: Include daily application count in the recap

## Daily Briefing

When called as part of the daily briefing (weekdays only — skip on weekends):

1. **Tracker maintenance**: The canonical tracker is the `Job Listings` Bases file at `/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings.base` plus the per-listing notes in `Projects/Get new job/Job Listings/`. Search Gmail for new application confirmations and rejection emails since the last entry. For each new confirmation: if a listing note already exists for that company+role, set `applied: true`, `status: applied`, and `application_date: <today>`. If no note exists, create one per the schema in the "Per-Listing Notes & Bases Tracker" section above. For rejections: set `status: rejected` and `rejection_date: <date>`.

2. **Google/WebSearch discovery scan** (NEW — added 2026-05-19 to fix LinkedIn-only blind spot):
   - Rotate 2-3 Google X-ray searches per day across ATS boards and niche remote boards. Suggested rotation (alternate which to skip):
     - `site:boards.greenhouse.io "<responsibility phrase>" remote` — pick a different responsibility phrase each day (Entra ID, phishing remediation, access provisioning, M365 admin, compromised account, Intune endpoint, etc.)
     - `site:jobs.lever.co "<responsibility phrase>" remote`
     - `site:jobs.ashbyhq.com "<keyword>" remote`
     - `site:remoterocketship.com "IT analyst" OR "security analyst" OR "compliance analyst"`
     - `site:himalayas.app "IT analyst" remote $75K`
     - `site:builtin.com "compliance analyst" OR "security analyst" remote`
   - Vary which responsibility phrase you search each day (see "Responsibility-keyword search" in Sources section). Rotating across days makes the activity pattern look like a human exploring rather than a script.
   - For each promising search result: open with `/defuddle` or WebFetch to read the JD directly (no need for separate "verify the title" step — the page IS the JD).
   - **Staleness check**: Google's index lags real-time. Lever (`jobs.lever.co/*`) silently returns 404 when a listing is removed. If `defuddle` returns empty content or `WebFetch` returns 403, fall back to `curl -sL -A "<browser UA>"` to confirm — many JS-rendered pages need a real UA, but a 404 page means the listing is dead. Discard 404s.
   - **Cloudflare-protected aggregators**: RemoteRocketship and a few others 1010-block curl with a Cloudflare challenge. Those are not blockers for Alex (he can open them in a browser), so still surface the URL — just note "verification incomplete, Alex must spot-check JD" in the listing note.
   - Apply the 4-gate hard requirements (remote / FT permanent / comp $75K+ or strong inference / ≥80% strong fit).
   - Dedupe against `Projects/Get new job/Job Listings/` folder.
   - Create per-listing notes for survivors with `source: greenhouse` / `source: lever` / `source: company-portal` / etc. as appropriate.

3. **LinkedIn discovery scan** (verified workflow — never skip the JD read or the comp DQ check):
   - Read `/linkedin` first for read-only rules, pacing, and the `references[]` mapping gotcha.
   - Run 3-4 `mcp__linkedin__search_jobs` calls across rotating angles to vary the daily activity pattern. Suggested rotation (pick 3-4 each day, alternate which to skip):
     - `IT analyst` / `IT operations`
     - `identity access management` / `IAM analyst`
     - `security analyst` / `cybersecurity analyst`
     - `GRC compliance analyst` / `information security GRC`
     - `IT auditor` / `compliance auditor`
   - Filters: `work_type=remote`, `job_type=full_time`, `date_posted=past_24_hours` (so we don't re-scan yesterday's pool), `sort_by=date`.
   - **Use ONLY job_id→title mappings from each response's `references[]` block.** Discard any job_ids from `job_ids[]` not present in `references[]` — positional alignment is unreliable. (See [[feedback-linkedin-search-job-id-mapping]].)
   - **Title pre-filter** (before any JD read — saves MCP budget on guaranteed-decline candidates per [[feedback-entry-level-target]]):
     - Drop titles containing: Senior, Sr., Sr, Lead, Principal, Staff, Manager, Director, Head of, Architect, Engineer III/IV/V
     - Drop obvious specialist mismatches: Epic, Cerner, Workday HRIS, Oracle ERP, SAP, Salesforce admin, Dynamics 365, Mainframe, Geospatial/GIS, AI/ML Engineer, EE/ME engineering, sourcing/procurement (Ariba/Coupa/Jaggaer), Tier I (too junior in tools Alex doesn't have)
     - Drop obvious sales/CSM: Account Executive, Customer Success, Solutions Engineer (pre-sales), Sales Engineer, Sales Development Rep
     - Keep: plain Analyst/Administrator/Specialist, Junior/Associate, "I"/"II" (with JD-verify experience cap, see below)
     - For "II" titles: if JD requires ≥6 years specialty tenure, treat as stretch and skip.
   - Dedupe candidates against the existing `Projects/Get new job/Job Listings/` folder (filename `<Company> - <Role>.md`) — skip any company+role already noted, regardless of status.
   - For each fresh candidate from references[]:
     a. Call `mcp__linkedin__get_job_details` — **read the actual JD before any fit label**. No title-only audits.
     b. Apply the 4-gate hard requirements (`feedback-job-hard-requirements`):
        - Fully remote (JD says remote, not just LinkedIn label — Cyderes 2026-05-19 was hybrid despite "Remote" label)
        - Full-time permanent (not contract, contract-to-hire, 1099, temp)
        - **Comp ≥$75K listed**, OR brief market-data check (Glassdoor/Salary.com/ZipRecruiter median for that title) shows strong evidence the role clears the floor — *if unlisted and you can't reach high confidence in <2 min of research, DQ*
        - Strong fit ≥80% (no failed JD hard reqs — degree, years, named tools, clearance, bilingual — AND ≥80% of top responsibilities/qualifications match Alex's resume)
     c. Create a per-listing note **only** if all 4 gates pass. Use the schema in "Per-Listing Notes & Bases Tracker" above. Set `verified: true` and record the comp-evidence inference (if applicable) in `verification_signals`.
   - Pacing: no numerical cap, but follow `/linkedin` qualitative rules — batch JD reads in small groups (2-4 per turn) with reasoning between, vary keyword angles day-to-day, no tight loops. The natural ceiling is "I've exhausted reasonable search angles," not an arbitrary count.
   - Target volume: 2-5 new verified candidates per day → hits the 10-20 weekly app goal.

4. **Contact research + cold outreach surfacing**: For **every** new verified candidate, run the mandatory Contact Research (see "Contact Research" section above) — recruiter(s), hiring manager(s), same-role employees, likely teammates — and record them on the listing note. Then, for candidates scoring Strong Fit (especially high comp + remote), follow mode 1 step 6: draft outreach and create `/crm potential <name>` Things 3 tasks for the top 1-2 targets. Cap outreach-task creation at the top 1-2 candidates per day to keep MCP pacing reasonable; the contact *capture* on the note applies to all qualifying candidates.

5. **Weekly pace check**: Count apps submitted since Monday vs 10-20 goal. If behind mid-week, suggest time blocks from calendar gaps.

6. **Upcoming interviews**: Surface any job-related events from today's calendar.

7. **Return for briefing** (per `feedback-briefing-compact` — jobs/contacts go to Things 3, not the briefing body):
   - Under `#### New tasks created`: any Things 3 tasks created during this run (cold outreach, advance-to-package, etc.) with `things:///show?id=ID` deep links.
   - Under `#### Flags`: only mention job-search items if exceptional — behind pace mid-week, interview today, or a stand-out Strong Fit posting that warrants same-day action. The candidate count goes here ("3 new verified candidates added to tracker — see Bases for triage") not the candidate list itself.
   - Append a `## Job Search Log` entry to the hub note (`Projects/Get new job.md`) summarizing: scan counts (titles searched / JD-verified / passed all gates), new candidate names with apply URLs, declined names with one-line reason. Be honest about counts — don't pad the survivor list.

## Proactive Behaviors

- During `/daily-briefing`, if it's midweek and Alex is behind on applications, flag it with suggested time blocks from calendar gaps
- When processing transcripts that mention job leads, companies, or networking contacts relevant to job search, surface them
- If Alex hasn't submitted any applications in 3+ days, mention it constructively in ad-hoc interactions
- Track which types of roles Alex applies to most — surface patterns that might help narrow or broaden the search
