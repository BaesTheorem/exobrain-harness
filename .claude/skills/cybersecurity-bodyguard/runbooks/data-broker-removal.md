# Data Broker Removal

Data brokers are the invisible backbone of doxxing. Almost every doxx begins with a broker query. Removing yourself from brokers closes most of the on-ramps.

## Reality check

- **Free brokers re-list you every 3-6 months** even after successful opt-out. This is not a one-time job.
- There are hundreds of brokers. The list below covers the top ~15 that matter most.
- Paid services (DeleteMe, Optery, Kanary) automate ongoing removals for ~$100-130/yr. After an incident, these are worth the cost.

## Tracker

Maintain removal state in `/Users/alexhedtke/Documents/Exobrain/Areas/Security/broker-removals.md`:

```markdown
| Broker             | URL                      | Last removed | Status   | Notes           |
|--------------------|--------------------------|--------------|----------|-----------------|
| Spokeo             | https://spokeo.com/...   | 2026-03-22   | removed  |                 |
| BeenVerified       | https://beenverified.com | 2026-04-14   | pending  | wait 7 days     |
| ...                |                          |              |          |                 |
```

Check re-listings monthly via the bodyguard passive scan.

## Per-broker procedures

### Spokeo
- Search: https://www.spokeo.com/ — find your profile
- Opt-out: https://www.spokeo.com/optout — paste profile URL + email
- Verify email link within 24 hours
- Removal: ~24 hours
- Re-lists: every 3-4 months

### BeenVerified
- Search: https://www.beenverified.com/
- Opt-out: https://www.beenverified.com/app/optout/search
- Search by name + state → claim → submit email
- Verify email
- Removal: ~24 hours
- Re-lists: yes, quarterly

### Whitepages
- Search: https://www.whitepages.com/
- Opt-out: https://www.whitepages.com/suppression_requests
- Requires phone verification (use a burner or Google Voice)
- Removal: ~24-72 hours
- Re-lists: occasional; a paid "Whitepages Premium" account is separately harder to remove — contact support@whitepages.com

### FastPeopleSearch
- Search: https://www.fastpeoplesearch.com/
- Opt-out: https://www.fastpeoplesearch.com/removal — paste profile URL
- No email verification
- Removal: ~24-72 hours
- Re-lists: yes, frequently

### Radaris
- Search: https://radaris.com/
- Opt-out: https://radaris.com/control/privacy — requires creating an account (use a throwaway email)
- Claim each listing individually
- Removal: ~24-48 hours
- Re-lists: yes; among the most aggressive

### MyLife
- Search: https://www.mylife.com/
- Opt-out: https://www.mylife.com/ccpa/index.pubview
- Phone call sometimes required (855-836-3755)
- Removal: 7-14 days
- Re-lists: occasional
- **Note**: MyLife is notorious for being hard to remove from. Keep records of all contact attempts.

### PeopleFinders
- Search: https://www.peoplefinders.com/
- Opt-out: https://www.peoplefinders.com/manage/
- Verify email
- Removal: ~48 hours
- Re-lists: yes

### Intelius
- Search: https://www.intelius.com/
- Opt-out: https://www.intelius.com/opt-out
- Requires email verification + government ID (!!). Consider covering SSN / DL number with sticky note if they demand ID.
- Removal: 7-14 days
- Re-lists: yes

### TruePeopleSearch
- Search: https://www.truepeoplesearch.com/
- Opt-out: https://www.truepeoplesearch.com/removal
- Paste profile URL + email + verification code
- Removal: ~24-48 hours
- Re-lists: yes, frequently

### FamilyTreeNow
- Search: https://www.familytreenow.com/
- Opt-out: https://www.familytreenow.com/optout
- Verify identity via phone
- Removal: ~24-48 hours
- Re-lists: yes
- **Note**: Exposes relatives. Important to remove after any incident that includes family info.

### ThatsThem
- Search: https://thatsthem.com/
- Opt-out: https://thatsthem.com/optout
- Paste profile URL + email + captcha
- Removal: ~24-72 hours
- Re-lists: yes

### Acxiom (data broker behind many others)
- Opt-out: https://isapps.acxiom.com/optout/optout.aspx
- Covers multiple downstream brokers
- Removal: 30-60 days
- Re-lists: no (but doesn't cover all brokers)

### LexisNexis
- Opt-out: https://optout.lexisnexis.com/ (for consumer databases only — not the legal research product)
- Requires ID + proof of residence
- Removal: 30-90 days
- Re-lists: no
- **Note**: LexisNexis feeds skip-tracing services used by PIs. Worth the hassle.

### Oracle Data Cloud (BlueKai)
- Opt-out: https://datacloudoptout.oracle.com/
- One-click, cookie-based (re-opt-out whenever you change browsers)
- Covers ad-targeting data brokers

### Epsilon
- Opt-out: https://www.epsilon.com/consumer-information-privacy-request
- Removal: 30 days
- Re-lists: no

## Bulk / paid services

After a doxx incident, seriously consider one of:

- **DeleteMe** (joindeleteme.com) — ~$130/yr, covers 38 brokers, quarterly reports
- **Optery** (optery.com) — ~$99/yr, covers 300+ brokers, generous free tier for basic sites
- **Kanary** (kanary.com) — ~$149/yr, 300+ brokers, aggressive re-check cadence
- **Privacy Duck** — manual, white-glove, ~$500 one-time

These pay for themselves in time saved and peace of mind during an active incident.

## California / EU residents

You have stronger rights under CCPA / GDPR. Many brokers have a "California residents" or "GDPR request" form that is easier than the standard opt-out. Use that form even if you're not physically there — the broker typically can't verify and processes the request anyway.

## Template: CCPA request (works on most US brokers even outside CA)

```
To: [broker privacy contact]
Subject: California Consumer Privacy Act Request — Delete

Under the California Consumer Privacy Act (Cal. Civ. Code §§ 1798.100
et seq.), I am requesting that you:

1. Disclose the categories and specific pieces of personal information
   you have collected about me.
2. Delete all personal information you have collected about me from your
   records.
3. Cease selling or sharing my personal information to third parties.

My identifiers: [full name, email, approximate age range, general
geographic region — provide only what's needed to locate records].

Please confirm completion within 45 days as required by law.

Thank you,
[Name]
```

## Post-removal verification

One week after submission, search each broker for your name again. If you still appear, re-submit. If they claim completion but you're still visible, file a complaint with:

- California AG: https://oag.ca.gov/privacy/ccpa
- FTC: https://reportfraud.ftc.gov/
- Your state AG's consumer protection division

## Cadence

- **Immediately after an incident**: full sweep of all brokers above
- **Quarterly**: re-check and re-submit the free brokers (they re-list)
- **Annually**: renew paid services + audit what's in `broker-removals.md`
