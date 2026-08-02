---
name: unemployment
description: File and manage Alex's Missouri unemployment (UInteract) claim -- weekly requests for payment, work-search evidence, correspondence, and eligibility questions. Use when Alex says "file my unemployment", "weekly claim", "UInteract", "unemployment claim", "request payment", "work search log", "did I file my claim", "DES", or when the weekly-request deadline is approaching.
---

# Unemployment (Missouri DES / UInteract)

Alex was laid off from Clyde on **2026-07-17** (IT outsourced to Accenture -- a
clean no-fault separation). Initial claim **filed 2026-07-19**. Portal:
[uinteract.labor.mo.gov](https://uinteract.labor.mo.gov).

Deep background lives in `Research/Layoff Benefits Playbook (Missouri 2026).md`
in the vault. Read it before answering anything about eligibility, severance, or
benefit math. Don't restate its numbers from memory.

## The one rule that outranks everything else

**MIST never submits the weekly request for payment.**

The weekly certification is a sworn statement. Missouri prosecutes false
statements made to obtain benefits (RSMo 288.380), and the penalties land on
Alex, not on the assistant that filled the form. Several of its questions have
answers that exist only in Alex's head:

- Did he work, in any capacity, during the week? **Working Order LLC is an
  active consultancy** -- self-employment and coaching hours count as work even
  when unpaid or unbilled, and gross earnings are reported for the week they
  were *earned*, not the week they were paid.
- Severance. Alex has an 8-week package (~$10,422.32). DES's FAQ says severance
  is "not reportable"; RSMo 288.036 says lump-sum severance is prorated as
  wages. **These do not reconcile in the public sources.** The playbook flags
  this as an open question requiring a call to DES at **800-320-2519**
  (Mon-Fri 8-5). Do not resolve it by picking whichever reading looks likelier.
- Was he able to and available for full-time work all week?
- Did he refuse any offer of work or referral?

So the division of labor is: **MIST prepares, Alex certifies.** Gather the
work-search evidence, log in, park the browser on the form, hand him the
answers he needs to confirm, and let him click submit himself. Then verify
afterward that the week shows as filed.

If Alex says "just submit it," that is not a fix. Give him the three or four
specific questions, take his answers, and let him press the button -- it's
thirty seconds of his time and it keeps the attestation his.

## The rules that lose money

| Rule | Detail |
|---|---|
| Weekly request | Filing the claim is **not** getting paid. A request must be filed **every week** or that week is forfeited, no rollover. |
| 14-day window | The window closes 14 days after the Saturday the week ends. Miss it and the money is gone. |
| 3 work searches | At least **3 activities per week**, logged in UInteract *before* the request. Fewer = denial for that week. |
| Waiting week | The first eligible week is unpaid, but the request **still must be filed** to bank the credit. |
| MoJobs | jobs.mo.gov registration is automatic on filing; visit at least monthly (the visit itself counts as an activity). |
| Waiver | Enrolling in WIOA-approved training can **waive** the 3/week work-search requirement. Ties to the FEC-KC dislocated-worker intake. Worth chasing -- it kills the weekly chore and funds a cert. |

Weeks run **Sunday through Saturday**. `python3 unemployment/uinteract.py weeks`
prints the recent week-endings with their deadlines rather than doing the date
math by hand.

## What counts as a work-search activity

Job applications (online or in person), interviews and recruiter screens, job
fairs, Job Center workshops / RESEA appointments, resume creation or revision,
networking conversations aimed at employment, and jobs.mo.gov searches.

## Building the work-search evidence

Never invent activities. Every logged item must trace to something that
actually happened, with a date. The sources, in order of reliability:

1. **Application confirmation emails** (Gmail). The hardest evidence -- an
   employer acknowledgment with a timestamp. Note that a submitted-looking
   Workday form with no confirmation email may never have submitted; the
   Saint Luke's case on 7/27 is the cautionary example.
2. **Job listing notes** -- `Projects/Get new job/Job Listings/*.md`, where
   `status: applied` and `application_date` is set. The `application_date`
   field is often left blank, so don't rely on it alone.
3. **Daily notes** -- interviews, screens, and networking calls are usually
   captured in the day's transcript or briefing sections.
4. **Plaud transcripts** -- recruiter screens and career conversations.

Cross-check the count against what Alex remembers before logging anything. If a
week comes up short of 3, say so plainly rather than padding it. A short week is
a real problem with real options (the MoJobs visit, a resume revision, a
networking reach-out) that are worth doing *now* if the window is still open,
and lying about is worth nothing.

## Driving the portal

```bash
python3 unemployment/uinteract.py open     # launch Chrome, log in, park it
python3 unemployment/uinteract.py status   # same, plus dump the homepage
python3 unemployment/uinteract.py weeks    # week-endings + deadlines
```

Credentials live in the gitignored harness `.env` as `UINTERACT_USERNAME` /
`UINTERACT_PASSWORD`. Never inline them, never commit them, never echo them into
a transcript.

### The rendering gotcha

UInteract's Angular app **blanks itself to `about:blank`** unless the page was
opened by Chrome itself:

- `launch_persistent_context(...)` -> blank
- `browser.new_page()` over CDP -> blank
- URL passed as a Chrome **command-line argument**, then `connect_over_cdp` -> renders

So: spawn real Google Chrome with the target URL in argv, sleep, then attach and
drive the page that already exists. Never `new_page()` against this site.
`connect_over_cdp` also tends to fail on a second attach with "Browser context
management is not supported" -- relaunch Chrome instead of reattaching.

**Automated login does not work.** Clicking LOG IN reliably closes the Chrome
window (reproduced several times on 2026-08-02). Credentials fill fine; the
click is what kills it. So don't burn time on it. Open the login page with
`open "https://uinteract.labor.mo.gov/benefits/#/benefits/login"` and let Alex
sign in himself. The site is plainly not built to be automated, which is
another reason the human-submits split is the right one.

The useful division: MIST does the research (which weeks are open, what the
work-search evidence is, what the correspondence says) and Alex does the
clicking.

### Login sends Alex a text

Every login fires an SMS to Alex ("Your account was accessed on ..."), and DES
also texts when new correspondence lands. So don't poll the portal idly -- each
check costs him a notification and makes a genuinely suspicious login harder to
spot. If Alex reports a login notice he can't account for, that's a real
security question: call 800-320-2519.

## Correspondence

UInteract correspondence is often time-sensitive (fact-finding questionnaires,
eligibility determinations, wage-audit forms) with short response windows that
can suspend payment. **Viewing is not responding.** When a notice arrives, read
it, work out what it actually asks for, and create a Things task with the real
deadline.

Fact-finding questionnaires in particular can change the answers on a weekly
request, so read the queue *before* preparing a week.

## Routine

1. Check for unread correspondence first, and handle anything with a deadline.
2. Run `weeks` and work out which weeks are unfiled and what their deadlines are.
3. Build the work-search evidence for each open week from the sources above.
4. Flag any week short of 3 activities while the window is still open.
5. Launch the portal, log in, park it on the weekly request.
6. Hand Alex the specific questions: earnings/self-employment, severance,
   able-and-available, work refused.
7. He answers and submits.
8. Verify the week reads as filed, log the outcome in the daily note, and check
   the repeating Things task.

## Related

- `/finances` -- benefit income against the budget
- `/job-search` -- the application pipeline that generates work-search activities
- `/things3` -- the repeating weekly-request task
- Vault: `Research/Layoff Benefits Playbook (Missouri 2026).md`,
  `Projects/Get new job/Get new job.md`
