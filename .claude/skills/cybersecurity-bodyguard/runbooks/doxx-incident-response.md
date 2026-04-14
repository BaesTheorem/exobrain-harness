# Doxx Incident Response

Use when PII has been publicly posted about Alex. Timing matters — the first hour shapes everything downstream.

## Principle: slow down

The urge to "do something immediately" is the attacker's weapon. Pause. Breathe. Follow the protocol. You have more time than you feel like you do, unless physical safety is at stake (see `stalking-response.md`).

## Phase 1: First 15 minutes

### 1. Preserve evidence before touching anything else

For each URL where PII was posted:

```bash
# Create incident directory
INCIDENT_DIR="/Users/alexhedtke/Documents/Exobrain/Areas/Security/Incidents/$(date +%Y-%m-%d)-<short-name>"
mkdir -p "$INCIDENT_DIR/screenshots" "$INCIDENT_DIR/archives"
```

For each URL:
1. **Screenshot the full page** with URL bar + timestamp visible. Use Cmd+Shift+4 then Space to capture the whole window.
2. **Save the page** via browser File → Save As → Webpage, Complete. Save to `$INCIDENT_DIR/archives/`.
3. **Archive it externally** — submit to https://archive.org/web/ and https://archive.ph/ . Save the resulting archive URLs. If the original is deleted, these remain as evidence.
4. **Note the attacker's handle/URL** — do not visit their profile beyond what's needed to document it.

**Never** edit, annotate, or crop the original screenshots. Work from copies if you need to redact for sharing.

### 2. Assess immediate physical risk

Check the doxx contents against `targets.json`:

- Current home address posted? → **HIGH** physical risk. Go to `stalking-response.md`.
- Workplace + schedule posted together? → **HIGH** physical risk. Notify employer security.
- Partner's name + identifying info posted? → Loop partner in immediately; they need to lock down too.
- Phone + encouragement to "call/harass"? → Prepare for swatting risk. Call local PD non-emergency line and pre-warn: "I'm being harassed online and am concerned about false reports being made against my address."
- Only old/stale info (previous address, old email)? → **MED**. Follow standard takedown.

### 3. Lockdown checklist

Do all of these within 15 minutes:

- [ ] Twitter/X: Settings → Privacy → Protect your posts
- [ ] Instagram: Settings → Privacy → Private account
- [ ] Facebook: Settings → Audience → Friends only; review tagged photos
- [ ] LinkedIn: Settings → Visibility → Limit public profile; remove employer if doxx targets it
- [ ] GitHub: review public repos for PII; make private temporarily if needed
- [ ] Strava/fitness apps: Privacy Zones around home + work; hide activity map
- [ ] Venmo/CashApp: Privacy → Private for all transactions
- [ ] Google Maps: Timeline → Pause location history (does not delete)
- [ ] Reddit: check username doesn't match anything in `targets.json.usernames`
- [ ] Discord: disable DMs from server members on any public server
- [ ] Consider: temporary phone number forwarding via Google Voice / Cloaked

### 4. Open a case file

Create `$INCIDENT_DIR/README.md`:

```markdown
# Incident: <short-name>
**Started**: YYYY-MM-DD HH:MM TZ
**Status**: active | mitigating | resolved

## Summary
[One paragraph: what happened, where, by whom if known]

## Evidence
- Screenshots: ./screenshots/
- Archives: ./archives/
- External archives:
  - [archive.org URL]
  - [archive.ph URL]

## Attacker identifiers
- Handle: @...
- Platform: ...
- Notes: [first contact, prior interactions, any pattern]

## PII exposed
- [ ] Full name
- [ ] Home address (current / prior / both)
- [ ] Phone
- [ ] Email
- [ ] Employer
- [ ] Partner info
- [ ] Photos
- [ ] Other: ...

## Timeline
- HH:MM — Discovered
- HH:MM — Evidence preserved
- HH:MM — Lockdown complete
- HH:MM — Platform report filed: [URL]
- ...

## Actions taken
- [ ] Evidence preserved
- [ ] Platforms notified
- [ ] Data broker takedowns filed (see data-broker-removal.md)
- [ ] Law enforcement contacted (if applicable)
- [ ] Lawyer contacted (if applicable)
- [ ] Partner / close family notified

## Open items
- ...
```

Keep this file updated through the full incident. It becomes the evidence trail for platforms, lawyers, and LE.

## Phase 2: Next 24 hours

### Platform abuse reports

File reports on every platform hosting the PII. Cite platform-specific policies:

- **Twitter/X**: https://help.twitter.com/forms/private_information — cite "posting private information" policy.
- **Reddit**: https://www.reddit.com/report — cite "sharing personal and confidential information" (rule against doxxing).
- **Facebook/Instagram**: https://www.facebook.com/help/contact/144059062408922 — cite "sharing private information."
- **YouTube**: https://support.google.com/youtube/answer/7582512 — privacy complaint form.
- **Discord**: https://dis.gd/request — select "Doxxing / Personal info."
- **TikTok**: in-app report → Privacy → Personal information.
- **Google Search**: https://support.google.com/websearch/troubleshooter/9685456 — "remove personal info from search results." Google now removes doxx content from search even when the source page remains.
- **Forum/blog hosts**: identify the hosting provider via `whois` on the domain; file abuse with both the forum and its host. If on WordPress.com / Medium / Substack / Ghost.org, use their abuse forms.
- **Pastebin**: https://pastebin.com/doc_abuse_faq — usually prompt takedowns.

**Template** (adapt per platform):

```
Subject: Urgent — doxxing / private information posted without consent

Hello [Platform] Trust & Safety team,

I am writing to report a violation of your [specific policy name] policy.
On [date], user [@handle] posted the following content at [URL]:
[brief description of what was posted — do NOT paste the PII itself]

This content includes my personal information that I have not authorized
to be shared publicly: [list categories — do not paste the actual values].
Its publication is causing direct harm and, if your policy against sharing
private information is to have effect, requires immediate removal.

Evidence: [archive.org / archive.ph URL] — please prioritize review before
the original content is altered or deleted.

I request:
1. Immediate removal of the URL above
2. Review of the posting account for pattern of violations
3. Confirmation of action taken

I am available at [safe contact — consider a dedicated email for this] for
any clarification.

Thank you,
[Name]
```

### Search engine de-indexing

Even after the source page is removed, cached copies persist in search results for days to weeks. File:

- Google: https://search.google.com/search-console/remove-outdated-content (after source removal) + https://support.google.com/websearch/troubleshooter/9685456 (for doxxing content specifically — this works even while source remains).
- Bing: https://www.bing.com/webmasters/tools/contentremoval

### Data broker takedowns

If the attacker harvested PII from data brokers (common), those brokers will keep feeding new attackers. File takedowns at every broker in `data-broker-removal.md`. This takes ~2 hours but closes the faucet.

### Law enforcement (if applicable)

File when:
- Threats of violence (even vague)
- SWATting concerns
- Explicit stalking behavior
- CSAM or CSAM-adjacent content involving Alex
- Attacker identity known + ongoing

Steps:
1. **FBI IC3**: https://www.ic3.gov/ — internet crime report. Takes 15 minutes. Creates federal record even if not immediately actioned.
2. **Local PD**: non-emergency line first. Ask for the cyber crimes unit or detective on duty. File a report and get a case number. This is essential for later civil action.
3. **911**: only if immediate physical threat.

Bring to the appointment: the incident README, printed screenshots (not just digital), and a one-page timeline.

### Lawyer

Worth consulting when:
- The doxx is sustained or escalating
- You want to pursue civil action (defamation, harassment, IIED)
- The attacker is identifiable and has assets
- There's employer / reputational fallout

Resources:
- Cyber Civil Rights Initiative referral: https://cybercivilrights.org/professionals-helping-victims/
- EFF: https://www.eff.org/issues/online-harassment (not direct representation but guidance + referrals)
- Local bar association lawyer referral service (usually free 30-min consult)

## Phase 3: Week 1–4

- [ ] Monitor for reappearance on data brokers (they re-list every 3–6 months)
- [ ] Re-run the bodyguard passive scan weekly — watch for new URLs, derivative posts, and platform migration
- [ ] Check breach databases weekly — attackers often dump credential sets after doxxing
- [ ] Rotate any credentials that appeared in the doxx
- [ ] Consider a new phone number if yours was posted (T-Mobile / Verizon / AT&T can port-freeze to prevent SIM swaps)
- [ ] Consider address masking: https://www.usps.com/manage/mail-forwarding.htm + PO Box, or a service like Earth Class Mail
- [ ] Consider a privacy service: DeleteMe, Optery, Kanary — they automate ongoing broker removals. Costs ~$100/yr. Worth it after any major incident.
- [ ] Close or harden old accounts — the attacker probably found the doxx by chaining old accounts. Audit with `haveibeenpwned.com` and the passive scan.

## Phase 4: Close-out

When the incident is stable (no new activity for 2+ weeks):

1. Update `$INCIDENT_DIR/README.md` status to `resolved` and add a post-mortem section.
2. Identify root cause: where did the attacker first find Alex's PII? Close that source.
3. Update `hardening-checklist.md` with any new protections adopted.
4. Schedule a 90-day follow-up scan to verify nothing resurfaces.
5. Archive the incident directory — keep it, do not delete.

## When to escalate beyond this runbook

- Attacker is known to have your physical location and is acting on it → immediate LE, consider temporary relocation
- Campaign spans multiple attackers / platforms over weeks → dedicated lawyer + crisis comms professional
- Employer / professional reputation at acute risk → lawyer + PR counsel
- Suicidal ideation from harassment (victim or attacker threatening self-harm) → 988 (Suicide & Crisis Lifeline) and crisis intervention

The runbook is a starting point. Real incidents are messier. Trust professionals for edge cases.
