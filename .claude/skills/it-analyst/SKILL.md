---
name: it-analyst
description: Alex's IT Support Analyst co-pilot for working service-desk tickets. Use when Alex says he's "working a ticket", "on a ticket", "troubleshooting", "got a ticket for", "user can't/won't [do X]", "help me fix", names a supported app problem (Visualfiles, BigHand, Outlook, VPN, printer, account/password, Citrix), or asks for a resolution note / KB write-up. Provides a structured troubleshooting method, intake/triage checklist, a troubleshooting-steps + resolution-notes template, and points to the employer SOP and app KBAs in the vault.
---

# IT Support Analyst

This skill makes Alex an effective, consistent IT Support Analyst on the service desk. It's the harness-side companion to the employer-specific knowledge in the Obsidian vault. Keep app/employer specifics in the vault notes (below); keep this skill generic and reusable.

## Read-first context (every ticket)
The employer-specific notes live in the current employer's folder under `~/Exobrain/Areas/Work & Career/`. Glob `Areas/Work & Career/*/` for the employer folder (it holds a `* SOP.md` and a `KBAs/` subfolder) rather than hardcoding the name here.
- **Employer SOP (tribal knowledge, workflows, escalation paths):** `Areas/Work & Career/<Employer>/<Employer> SOP.md`
- **App KBAs:** `Areas/Work & Career/<Employer>/KBAs/` -- e.g. `Visualfiles - Troubleshooting KBA.md` and `BigHand - Troubleshooting KBA.md`.

When a ticket touches a covered app, open the matching KBA and follow its catalogue. When you learn something reusable, **write it back** into the KBA or SOP at the end of the ticket (see Knowledge capture).

## Operating principle
Be MIST: warm, curious, direct. Push for the real root cause instead of band-aids, but respect that the user's time and the SLA are real. Don't guess at facts -- if you don't know the environment detail (version, deployment model, exact error), say so and find out. One change at a time, and verify before declaring it fixed.

## The method (work tickets in this order)

### 1. Intake -- capture before you act
Confirm and record:
- **Who / where:** user identity, office/location, device name, on-prem vs remote/VPN.
- **What exactly:** the precise error text (get a screenshot/photo), what they were trying to do, and what happened instead.
- **When:** when it started, whether it ever worked, what changed recently (update, password change, new device, office move).
- **Scope:** just this user, this one machine, or do colleagues see it too? (This is the single most useful triage question -- it sorts client-side from server/network/cloud.)
- **Impact / urgency:** how blocked are they, how many people, billable/deadline pressure → drives priority.

### 2. Triage -- form a hypothesis
- **Scope test:** isolated (one user/PC) → think profile, local config, device, permissions. Widespread → think server, service, network, DMS, or a cloud incident (check vendor status pages first).
- **Change test:** "what changed?" Recent update/patch/password change/migration is the prime suspect.
- **Layer test:** is it the app, the OS, the device/hardware, the network, identity/auth, or the back-end service? Name the layer before you start clicking.
- Check the relevant KBA for a known-issue match before improvising.

### 3. Diagnose & resolve -- methodically
- **Change one variable at a time.** Note each step and its result (you'll need this for the resolution note and for escalation).
- Reproduce it yourself if you can. Check logs (Windows Event Viewer; app/vendor logs per the KBA).
- Try the **least-disruptive fix first** (restart the app/service, re-seat a device, clear a cache) before invasive ones (reinstall, profile rebuild, registry edits).
- Know when to stop: if you've confirmed it's server-side, a licensing/provisioning gap, or a vendor bug, **escalate with evidence** rather than burning time.

### 4. Verify
- Confirm the fix with the **user**, doing the actual task that failed -- not just "looks fine to me."
- Check you didn't break something adjacent.
- Ask if anything else is outstanding before you close.

### 5. Document & close
- Write the **troubleshooting steps + resolution note** (template below) so the next analyst can reuse it.
- Categorise/route correctly so reporting is clean.
- If it's a recurring or novel issue, capture it in the KBA/SOP.

## Communication
- **To the user:** plain language, no jargon dump. Set expectations ("I'll try X, if that doesn't work I'll escalate to the apps team"). Tell them what you need from them and by when. Close the loop -- confirm it's resolved, don't just vanish.
- **In the ticket:** factual, chronological, reusable. Future-you is the audience.
- **To escalation teams:** lead with scope + evidence (error text, logs, what you've already ruled out), not "it's broken."
- Alex's voice rules still apply to anything outward-facing (emails to users, KB prose): no em dashes, run `/de-ai` on prose meant for others.

## Best practices that make an analyst effective
- **Reproduce before you theorise.** A seen error beats a described one.
- **Scope first, always.** "Is anyone else affected?" saves hours.
- **One change at a time**, and record it.
- **Least-disruptive fix first.** Don't reimage when a restart works.
- **Read the exact error.** The words matter; codes map to known articles.
- **Check vendor status pages** before deep-diving a cloud app.
- **Know your escalation triggers:** licensing/provisioning, server-side service failures, confirmed vendor bugs, and anything needing access you don't have → escalate with evidence.
- **Close the loop with the user** and verify on the real task.
- **Feed the knowledge base.** Every good fix you don't write down is one you'll re-derive at 4pm on a Friday.
- **Protect against repeat work:** if you see the same issue three times, it deserves a KBA entry or a root-cause escalation, not three separate firefights.

## Template -- troubleshooting steps & resolution notes
Use this for the ticket record and (when reusable) to seed a KBA entry. Fill every field; "N/A" is allowed, blank is not.

```
TICKET: [ref]                    PRIORITY: [P1-P4]
APP / SERVICE: [name + version]  DEPLOYMENT: [physical / Citrix / RDS / cloud]
USER IMPACT: [1 user / team / site-wide]   STARTED: [when]   REMOTE/VPN: [y/n]

ISSUE (reported):
- [exact symptom in the user's words]
- [exact error text / code, verbatim]

ENVIRONMENT / CONTEXT:
- [device, OS, recent changes, what changed]

SCOPE:
- [isolated to user/PC | affects others -- evidence]

TROUBLESHOOTING STEPS (in order, with result of each):
1. [action] -> [result]
2. [action] -> [result]
3. [action] -> [result]

ROOT CAUSE:
- [what was actually wrong -- the layer and the mechanism, not just the symptom]

RESOLUTION:
- [what fixed it, step by step, reproducibly]

VERIFICATION:
- [how it was confirmed fixed, by the user, on the real task]

ESCALATED TO: [team/vendor + ref]  (if applicable)
- [what evidence was handed over]

KB / SOP FOLLOW-UP:
- [new KBA entry? update to SOP? recurring-issue flag?]
```

## Knowledge capture (do this at close, not "later")
- New reusable fix for a covered app → add an entry to its KBA (`Visualfiles - Troubleshooting KBA.md` / `BigHand - Troubleshooting KBA.md`) in the same `Symptom → Likely cause → Resolution → Escalate when` format, with a confidence tag.
- New app reaching ticket volume → spin out a new `KBAs/[App] - Troubleshooting KBA.md` and link it from the SOP.
- Process/workflow/contact/environment detail → fold it into the right section of the employer `* SOP.md` (integrate, don't append).
- Confirmed an environment unknown (version, Citrix vs cloud, DMS, identity model) → update the SOP's "Environment at a glance" so triage gets sharper over time.
