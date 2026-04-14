---
name: kc-streetcar-report
description: Draft and send an issue report email to the KC Streetcar team (info@kcstreetcar.org). Use this skill whenever the user mentions reporting a problem with the KC Streetcar — tracker displays showing fallback data instead of live arrivals, service disruptions, station issues, safety concerns, accessibility problems, or any other streetcar infrastructure issue. Also trigger when the user says things like "report this to the streetcar", "email KC Streetcar", "let the streetcar people know", or references a streetcar problem they want escalated. If the user uploads a photo taken near a KC Streetcar station and describes an issue, use this skill. Requires Gmail MCP tool access and Pillow (pip install).
---

# KC Streetcar Issue Report

Draft a concise, actionable issue report email to the KC Streetcar operations team.

## Workflow

### Step 1: Identify the station

**If the user uploaded a photo**, try two approaches in order:

1. **Visual identification** — read the station name from the photo itself (the blue vertical platform signs are labeled, e.g., "River Market West", "Armour").
2. **EXIF fallback** — run the extraction script for timestamp and device info:

```bash
pip install Pillow --break-system-packages -q
python3 /path/to/this/skill/scripts/extract_metadata.py /mnt/user-data/uploads/<filename>
```

The script returns JSON with `timestamp`, `device`, and nearest-station match. Visual identification from the photo is more reliable than GPS matching — prefer the station name you can read on the sign.

**Directional disambiguation**: Some stops have separate northbound and southbound platforms. If the photo or context makes clear which direction (e.g., the sign says "River Market West" vs "River Market East", or the user mentions NB/SB), include that in the report. If unclear, just use the base station name.

**If no photo**, gather the station name from conversation context or ask the user.

### Step 2: Gather remaining details

Extract from context before asking:
- **Issue type** — classify: Tracker/Display, Service Disruption, Safety, Accessibility, Station Condition, Other.
- **Description** — what's wrong, in the user's words or inferred from context.
- **Date/time** — from EXIF timestamp, conversation context, or today's date.
- **Pattern data** — if the user has observed the same issue at multiple stops or on multiple occasions, note that. Pattern reports are far more actionable than single-instance reports.

Only ask the user if you can't infer the issue type or description from context.

### Step 3: Draft the email

Use `Gmail:gmail_create_draft` with:
- **To:** `info@kcstreetcar.org`
- **Subject:** `[Issue Report] <Issue Type> – <Station Name>`
- **Body:** Professional but brief. Must include:
  - What the issue is (1–2 sentences)
  - Station name (with directional platform if known), date, and time
  - Pattern data if applicable (multiple stops, repeat observations)
  - Whether photo evidence is available
  - **Why this matters** — always include a brief line explaining the value of the feature being reported on. For tracker/display issues: real-time arrival data is one of the streetcar system's strongest features for rider confidence and ridership growth, and fallback to static intervals undermines that. For safety issues: frame in terms of rider or pedestrian safety. For accessibility issues: frame in terms of ADA compliance and inclusive access. This context helps the ops team prioritize.
  - A line inviting follow-up
  - User's contact info: Alex Hedtke, 816-541-6685, alex.hedtke@gmail.com

### Step 4: Remind user to attach and send

After drafting, remind the user to:
- Attach any photos before sending (Gmail draft API cannot attach images)
- Review and hit send

## Email Template

```
Subject: [Issue Report] <Issue Type> – <Station Name>

Hello,

I'd like to report an issue observed at the <Station Name> station on <Date> at approximately <Time>.

<1–2 sentence description of the problem.>

<If pattern: I've observed the same issue at [other stops/times], which may suggest a system-wide [feed/infrastructure] issue rather than a localized problem.>

<Why this matters — 1 sentence contextualizing the value of the feature or the risk of the issue. Examples:
- Tracker: "Real-time arrival data is one of the streetcar's strongest rider-facing features, and fallback to static intervals reduces rider confidence and the system's competitive advantage over driving."
- Safety: "This poses a risk to [rider/pedestrian] safety, particularly during [peak hours / low-visibility conditions]."
- Accessibility: "This creates a barrier for riders who depend on [accessible boarding / audio announcements / etc.].">

<If photo: I have a photo documenting the issue that I've attached for reference.>

Please let me know if additional detail would be helpful.

Alex Hedtke
816-541-6685
alex.hedtke@gmail.com
```

## Notes

- KC Streetcar contact: info@kcstreetcar.org / 816.627.2527
- Phone is provided in case the user prefers to call.
- Keep the tone constructive — helpful feedback from a regular rider, not a complaint.
- Do not include raw GPS coordinates in the email body — the station name is sufficient.
