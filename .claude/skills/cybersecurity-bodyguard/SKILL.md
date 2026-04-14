---
name: cybersecurity-bodyguard
description: Defensive security partner focused on doxxing, stalking, and targeted harassment. Use when the user says "bodyguard", "security scan", "doxx scan", "privacy scan", "threat check", "I'm being harassed", "I think I'm being stalked", "am I being doxxed", "scrub me from the internet", or asks about their public attack surface, data broker presence, credential breaches, or how to respond to a security incident. Also use for pre-flight exposure audits before publishing content, and for vetting unusual inbound contacts.
user_invocable: true
---

# Cybersecurity Bodyguard

Active **defense** against doxxing, stalking, and targeted harassment. This skill does four things:

1. **Passive OSINT self-scan** — what the internet knows about Alex right now
2. **Outbound exposure audit** — catch PII leaks before they ship
3. **Inbound social-engineering detection** — flag suspicious contacts
4. **Incident response** — playbooks for when something is actively going wrong

**This skill is strictly defensive.** Never engage attackers, never scrape harassment forums, never take offensive action. If the situation escalates beyond what a playbook can handle, the correct action is always "escalate to a human professional" (lawyer, platform trust & safety, law enforcement cyber unit).

## Config: what to monitor

PII to monitor lives in a gitignored config at `.claude/skills/cybersecurity-bodyguard/targets.json`. If that file is missing, read `targets.example.json` and prompt Alex to fill it in. The config lists:

- Legal name + common variants
- Email addresses (personal, work, throwaway)
- Phone numbers (current + prior)
- Physical addresses (current + prior 5 years — stalkers use old addresses)
- Usernames/handles across platforms
- Date of birth
- Partner's name + identifiers (optional — stalkers pivot through family)
- Employer name
- Known aliases and pen names

Never commit this file. Never read it into a response to the user verbatim — refer to entries by key (e.g., "email[0]") when showing scan results.

## Mode 1: Passive OSINT self-scan

Triggered by: "bodyguard scan", "what's public about me", "doxx scan", weekly schedule, or incident response.

### Scan steps

Run in parallel where possible:

1. **Credential breaches** — query Have I Been Pwned for each email in targets.json. Report new breaches since the last scan (compare against `Security Log.md`).
2. **Google dorking** — run these searches via WebSearch:
   - `"<full name>" "<city>"` (adjust city from targets)
   - `"<email>"` (each email)
   - `"<phone>"` and `"<phone with dashes>"`
   - `"<username>" site:pastebin.com OR site:ghostbin.com OR site:paste.ee`
   - `"<full name>" filetype:pdf OR filetype:xlsx OR filetype:csv`
   - `"<full name>" "<employer>"`
   - For each alias/username: `"<alias>"` plus `"<alias>" site:github.com`
3. **Data broker presence** — check each of:
   - spokeo.com, beenverified.com, whitepages.com, fastpeoplesearch.com, radaris.com, mylife.com, peoplefinders.com, intelius.com, truepeoplesearch.com, familytreenow.com, thatsthem.com
   - For each, WebFetch `https://<site>/...<name-in-their-URL-format>` or run Google search `site:<broker> "<full name>"` and note whether a result exists.
   - Cross-reference against the takedown tracker (see runbook `data-broker-removal.md`) — flag any site where Alex previously opted out but has reappeared (common — they re-list every 3-6 months).
4. **GitHub/social leak check** — Google search `"<each email>" site:github.com` and `"<each username>" site:github.com`. Flag any commits in public repos (including this one) that contain PII.
5. **Reverse image search** (optional, on request) — if Alex provides a profile photo, suggest running TinEye + Google Images manually. Do not download images for him.
6. **Domain WHOIS** — if Alex owns any domains (check targets.json.domains), WebFetch `https://who.is/whois/<domain>` and flag any personal info that should be behind a privacy proxy.

### Output

Write findings to `/Users/alexhedtke/Documents/Exobrain/Areas/Security/Security Log.md` (create if missing) with today's date as a section header. Format:

```markdown
## 2026-04-14 — Passive scan

### New findings
- **[HIGH]** beenverified.com — full name + partial address visible
  - Action: [data-broker-removal.md#beenverified]
- **[MED]** github.com/someuser/repo — email in commit 3fa4b2
  - Action: contact repo owner, request scrub + force-push

### Delta from last scan
- Removed: spokeo.com (successful takedown 2026-03-22)
- Reappeared: radaris.com (re-listed after 2026-01-15 removal)

### No-change
- HIBP: no new breaches since last scan
```

Create a Things 3 inbox task for each HIGH finding. MED findings go into a batched "Security review: N items" task. LOW findings are logged only.

Send a macOS notification summarizing the count per severity.

## Mode 2: Outbound exposure audit

Triggered by: "check before I post", "exposure audit", "am I leaking anything", or automatically when Alex asks to commit/push to a public repo.

This extends the existing `exobrain-audit` privacy phase. Difference: that skill audits the harness repo; this audits **any outgoing artifact** — social posts, public PRs, blog drafts, images, resumes being sent out, etc.

### Checks

1. **Staged git changes** — run `git diff --cached` and scan for entries matching anything in targets.json. Also scan for classic leaks: `.env` patterns, API key shapes (`sk-...`, `AIza...`, `AKIA...`, GitHub `ghp_...`), private IPs, home directory paths with full names.
2. **Images** — if the artifact includes images, run `scripts/exif-strip.py --check <path>`. Report if EXIF contains GPS, device ID, or creator fields. Offer to strip.
3. **Free-form text** — scan drafts/messages for: full address, phone number, employer + role + location combo (pivot risk), partner's identifying info, real names of non-public people.
4. **Document metadata** — for PDFs and Office docs, warn if author/title/comments fields are populated with real name. Suggest running `exiftool -all= <file>` before sending.

### Output

Inline findings with line numbers and suggested redactions. Do NOT auto-edit the artifact — surface the findings and let Alex decide.

## Mode 3: Inbound social-engineering detection

Triggered by: passively during email/iMessage/Discord processing, or explicitly ("is this sender sketchy", "vet this contact").

### Signals to flag

For each new inbound message from a sender not already in the People/ CRM:

1. **Urgency + authority** — "this is your bank, account compromised, click now"
2. **Out-of-band asks** — contact claims to be someone you know but from a new number/email/handle (pretexting)
3. **Info-fishing** — asks for location, schedule, partner's name, employer details, or anything that isn't required for the stated purpose
4. **Mimicry** — display name matches a known contact but the underlying address/handle differs (verify against People/ frontmatter)
5. **Cross-platform pivoting** — same unknown party appears on multiple channels in short succession
6. **Anonymized requests about Alex** — someone in the People/ CRM mentions a stranger asking about Alex, their location, schedule, or relationships. This is an early-warning signal for stalking.

### Process

1. Look up sender in People/ CRM. If not present, search Obsidian for any prior mention.
2. If sender is unknown AND any signal above is present, log to `Security Log.md` under today's date with section `### Suspicious inbound`.
3. Create Things 3 task `Review suspicious contact: <sender>` with brief context and a link to the source message.
4. If the signal is "mimicry of a known contact," escalate immediately via URGENT macOS notification — this is the pattern used in targeted attacks.

Never auto-block, auto-reply, or take any action on the sender. Only surface.

## Mode 4: Incident response

Triggered by: "I'm being doxxed", "I think I'm being stalked", "someone's harassing me", "my address is out there", or any HIGH-severity finding from Mode 1 that suggests active targeting.

### First 15 minutes (do these in order)

1. **Stop and breathe.** The instinct to engage is the wrong instinct. Do not respond to the attacker on any channel.
2. **Preserve evidence.** Screenshot everything (full page, with URL bar visible). Save to `/Users/alexhedtke/Documents/Exobrain/Areas/Security/Incidents/YYYY-MM-DD-<short-name>/`. Do not edit, crop, or annotate originals.
3. **Assess immediate physical risk.** If the doxx includes current home address AND there is any credible threat of in-person action, skip to runbook `stalking-response.md` (which includes calling 911 / local PD non-emergency).
4. **Contain the spread.** Lock down public accounts (Twitter → protected, Instagram → private, LinkedIn → limit connections, GitHub → review public repos). Runbook: `doxx-incident-response.md#lockdown-checklist`.
5. **Open a case file.** Create `Incidents/YYYY-MM-DD-<name>/README.md` with: timeline, URLs, screenshots, attacker handles, actions taken. This is evidence for platforms, lawyers, and LE.

### Next 24 hours

See runbook `doxx-incident-response.md` for full protocol. High level:

- File abuse reports at each platform where PII was posted (templates in runbook).
- File data-broker takedowns for every site the attacker linked (template per broker in `data-broker-removal.md`).
- Contact EFF cyberstalking resources if the harassment involves threats or a sustained campaign: https://www.eff.org/issues/online-harassment
- If there are threats of violence, report to FBI IC3 (ic3.gov) and local law enforcement.
- Consider engaging a lawyer. The Cyber Civil Rights Initiative maintains a referral list: https://cybercivilrights.org/

### What NOT to do

- Do not dox the attacker back. Beyond being wrong, it destroys your legal standing.
- Do not engage on the attacker's preferred platform. Move everything to channels you control.
- Do not delete evidence even if it's painful to keep. Archive, then hide, but do not delete.
- Do not publicize the incident prematurely — it amplifies the attacker's reach. Consider crisis-comms help first.

## Runbooks

Detailed playbooks in `runbooks/`:

- `doxx-incident-response.md` — step-by-step response when PII has been publicly posted
- `stalking-response.md` — physical-safety protocol when a stalker is identified
- `data-broker-removal.md` — per-broker opt-out procedures and tracker
- `social-engineering-detection.md` — patterns, examples, and verification workflow
- `hardening-checklist.md` — proactive steps (2FA, email aliases, phone number hygiene, etc.)

## Scheduling

- **Weekly** (Sunday morning): Run Mode 1 (passive OSINT self-scan) and append to Security Log. Notify with count-per-severity summary.
- **Daily** (morning briefing): Quick HIBP check only. Full scan only weekly to avoid rate limits and noise.
- **On every commit to a public repo**: Mode 2 (exposure audit) should run automatically. Add this to the evening wind-down gitignore audit if not already integrated.
- **On every new inbound sender**: Mode 3 (social-engineering detection) runs passively during email/iMessage/Discord processing.

## Integration with existing skills

- **exobrain-audit** → Mode 2 extends its privacy phase. When exobrain-audit runs, it should additionally invoke the targets.json check.
- **crm** → Mode 3 reads the People/ CRM for sender verification. When a new contact passes verification, the CRM skill creates the People/ note as usual.
- **email**, **imessage**, **discord-digest** → each should call into Mode 3 for new senders. Pattern: after fetching messages, pass the sender list through the bodyguard filter before processing.
- **evening-winddown** → already runs a gitignore audit; extend it to invoke Mode 2 on staged changes.

## Ethical guardrails

Never:
- Access or scrape doxxing/harassment forums (Kiwi Farms, 4chan, etc.). If mentions are Google-indexed, the Google search result is sufficient — do not visit or save forum pages.
- Attempt to identify or "out" attackers. Collect evidence of what they did; leave identification to investigators.
- Recommend vigilante actions. If Alex suggests one, push back and redirect to the legal/platform path.
- Store attacker-provided PII (their real name, address, etc.) in the vault, even if known. That data is a legal landmine.

If a scan surfaces something that feels like it requires a professional (ongoing harassment, credible threat, legal ambiguity), say so explicitly and recommend the appropriate resource (lawyer, LE, EFF, crisis line).
