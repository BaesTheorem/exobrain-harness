---
name: setup-exobrain
description: Walk a NEW person (not the repo owner) through standing up their own Exobrain-style assistant, adapted to whatever tools THEY already use (Notion, OneNote, Obsidian, Todoist, Google/Apple/Outlook, etc.) instead of the owner's exact stack. Use when someone says "set up my own exobrain", "help me adapt this harness", "I want this but I use Notion/OneNote", "onboard me", "port this to my tools", or when a friend's AI is reading this repo to replicate the system. Written to be portable: it works as a Claude Code skill AND as a plain guide any assistant can follow.
user_invocable: true
metadata:
  requires:
    bins: []
---

# Set Up Your Own Exobrain

You are helping a person -- call them **the user** -- build their own version of this "exobrain" assistant. **You are probably not running on the original owner's machine, and the user does not use the owner's exact tools.** Do not assume Obsidian, Things 3, or Google. Your job is to adapt the *patterns* in this repo to *their* stack with as little friction as possible.

This guide is deliberately tool-agnostic and assistant-agnostic. It works whether you are Claude Code with filesystem access, Claude.ai with connectors, or a browser chatbot the user is pasting this into.

## The one idea that makes this portable: capability ports

The exobrain doesn't actually need Obsidian or Things 3. It needs a handful of **capabilities**. Each is a "port" with a small contract of verbs. Any product that can satisfy the verbs can be plugged in.

| Port | What it's for | Verbs it must satisfy | Common backends |
|---|---|---|---|
| **Notes** | the memory substrate (daily log, people CRM, health log, project notes) | append-to-daily, read-daily, append/read a titled note, search | Obsidian (files), Notion, OneNote, Apple Notes, Logseq, Google Docs, a plain markdown folder |
| **Tasks** | capture and track to-dos | create (title, notes), list (filter), complete, search | Things 3, Todoist, TickTick, Notion DB, Apple Reminders, Google Tasks, MS To Do |
| **Calendar** | events and scheduling | create-event, list-events (range) | Google Calendar, Apple Calendar, Outlook/M365, Fastmail/CalDAV, ICS file |
| **Capture** | raw thought coming *in* to be processed | list-new, read, mark-processed | voice recorder + transcript (Plaud, Otter, Whisper), handwriting (Supernote), messages, or manual paste |
| **Health** *(optional)* | steps/sleep/weight/HR | read-metric (metric, date) | Fitbit, Withings, Apple Health export, Garmin, Oura, Google Fit, or skip |

Everything else in this repo (the persona, the daily briefing, the wind-down, the weekly review, the CRM discipline, transcript processing, session memory) is **logic that speaks in these verbs**. Once the ports are bound to the user's real tools, the logic just works. Your setup job is: pick the runtime tier, interview the user, bind each port, translate the concepts, verify.

## Step 0 -- Figure out your runtime, which sets the tier

Before anything, establish what *you* (the assistant) can actually do on the user's setup. Ask yourself / the user:

- Do I have **filesystem** read/write on a machine the user controls?
- Do I have **MCP tools / connectors** to their apps?
- Can I run **shell commands**?
- Is there a way to run **scheduled jobs** (cron, launchd, Task Scheduler) on an always-on machine?

That answer picks the honest tier. **Tell the user their tier up front so nobody expects magic that their runtime can't deliver.**

- **Tier 0 -- Conversational.** Any chatbot, zero setup. You run the *thinking* skills (briefing structure, wind-down, weekly review, CRM reasoning, transcript summarizing) but the user pastes data in and saves your output by hand. Works today, in this chat.
- **Tier 1 -- Connected.** You have MCP/connectors to their notes + tasks + calendar, so you read and write directly. No background automation yet. This is the sweet spot for most people.
- **Tier 2 -- Automated.** You run on an always-on machine with filesystem + shell + a scheduler (e.g. Claude Code on a Mac/Linux box). Now you get the full harness: input watchers, scheduled briefings/wind-downs, backups. This is the owner's setup and the most work.

Most users should aim for **Tier 1 first** and graduate to Tier 2 only if they want unattended automation.

## Step 1 -- Interview the user (don't assume)

Ask, in plain language, one port at a time. Keep it short:

1. **Notes:** "Where do you keep notes today? (Notion, OneNote, Obsidian, Apple Notes, Google Docs, nothing yet?)"
2. **Tasks:** "What do you use for to-dos? (Todoist, Things, Apple Reminders, a Notion board, nothing?)"
3. **Calendar:** "Whose calendar? (Google, Apple/iCloud, Outlook?)"
4. **Capture:** "How do thoughts come in that you'd want processed? (voice memos, a smart recorder, handwriting, texts, or you'll just paste them?)"
5. **Health:** "Do you want health tracking, and from what? (Fitbit, Apple Watch, Oura, Garmin, or skip.)"
6. **Persona:** "Do you want your assistant to have a name and voice? (The owner's is 'MIST.' Yours can be anything, or none.)"

If they don't have a tool for a port, that's fine -- recommend a low-friction default (a plain notes folder or their phone's built-in notes/reminders) rather than making them adopt something heavy.

## Step 2 -- Bind each port to their tool

For each port, wire the verbs to the user's tool using the best access you have. Preference order: **native MCP/connector → official API → local files → manual paste.**

Known recipes (use these when they match; improvise from the contract when they don't):

- **Notes → Obsidian / Logseq / plain folder:** files on disk. If you have filesystem access, read/write markdown directly. This is the lowest-friction backend.
- **Notes → Notion:** use the Notion MCP or API. Model the "daily note" as a row in a **Journal** database (Date property), the CRM as a **People** database, the health log as a **Health** database. Append = add/update a row or a block.
- **Notes → OneNote:** Microsoft Graph API. Map daily note → a page in a "Daily" section; CRM → pages in a "People" section. Heavier auth (Azure app registration); warn the user.
- **Notes → Apple Notes / Google Docs:** use whatever MCP/automation exists; otherwise fall back to manual paste and be honest that write-back isn't automatic.
- **Tasks → Todoist / TickTick / Google Tasks / MS To Do:** each has an MCP or a simple REST API. Bind create/list/complete.
- **Tasks → Notion board / Apple Reminders:** Notion via API; Reminders via AppleScript/MCP on a Mac.
- **Calendar → Google / Outlook:** connectors exist for both. **Apple Calendar** → CalDAV or a Mac-local bridge.
- **Capture → any recorder:** the contract is "give me new transcripts." If their recorder syncs text files to a folder, watch the folder. If it's audio only, run Whisper (or any transcription) first. No smart recorder? They paste; you process.
- **Health → Fitbit/Withings/Oura/Garmin:** each has an API needing OAuth. **Apple Health** has no live API -- the user exports and you read the export. If they don't care about health, drop the port entirely.

**Fallback contract (for any tool without a recipe):** you have the verb list for the port above. Figure out how to satisfy it with the user's tool, or tell the user plainly what's missing (an MCP server, an API key, an app install) and give them the smallest step to get it. Never pretend a binding works when it doesn't.

## Step 3 -- Translate the concepts to their tool's native shape

The owner's structures are markdown-flavored. Don't force markdown onto a database tool -- map the *concept* to the target's native primitive:

| Concept | Obsidian (files) | Notion (databases) | OneNote (sections/pages) |
|---|---|---|---|
| Daily note | one `.md` per day | a row in a Journal DB | a page in a Daily section |
| People CRM | one note per person, YAML frontmatter | a People database with properties | a page per person |
| Health log | one `.md` per day | rows in a Health DB | a page per day |
| Project note | `.md` + wikilinks | a Projects DB with relations | linked pages |

A Notion user should end up with real Notion databases they can filter and view, not a markdown blob pasted into a Notion page. Use the destination tool the way its users actually use it.

## Step 4 -- Write a stack-profile

Record the bindings so every skill can resolve a port without re-asking. Create a small `stack-profile.md` (or `.json`) the assistant reads at the start of each session. Capture: which tool backs each port, how it's reached (MCP name / API / file path), the user's name + timezone + locale, the persona name, and the chosen tier. This file is the user's personal equivalent of the owner's `config.sh` + `CLAUDE.md` paths -- the single place bindings live.

## Step 5 -- Pick the skills to bring over (core, not everything)

This repo has ~48 skills, but roughly half are hyper-personal to the owner. Bring the **core** loop; leave the owner-specific ones.

- **Core (recommend for everyone):** capture, daily-briefing, evening-winddown, weekly-review, monthly-review, process-transcript, crm, mood, session-memory, verify, de-ai, plus the convention references for whichever note/task/calendar tools they chose.
- **Owner-specific (skip unless relevant):** job-search, resume-builder, it-analyst, the games (osrs, solo-dm, dnd-sheet, jackbox), finances, the personal watchers, and anything tied to the owner's specific devices, employer, or life. If a skill names the owner, a specific employer, or a specific city, it's personal -- adapt or drop it.

When you bring a core skill over, strip any hardcoded path/name and make it speak to the ports and the stack-profile instead.

## Step 6 -- Verify with a tiny smoke test

Prove the loop end-to-end before declaring done:

1. **Capture:** ask the user for one throwaway task ("remind me to test my exobrain") → create it via the Tasks port → confirm it appears in their tool.
2. **Notes:** append one line to today's daily note via the Notes port → confirm it's there.
3. **Briefing:** run a minimal daily briefing that reads calendar + tasks + notes and writes a summary back.

If all three round-trip, the ports are bound correctly. If one fails, fix that binding before moving on.

## Worked example -- a Notion + Todoist + Google Calendar + ChatGPT user

- **Runtime:** browser ChatGPT with Notion/Todoist/Google connectors → **Tier 1** (connected, no automation). Tell them: interactive works today; scheduled briefings would need a Tier-2 always-on setup later.
- **Notes → Notion:** create Journal, People, Health databases. Daily note = a Journal row keyed by date.
- **Tasks → Todoist:** create/list/complete via the Todoist connector; the "inbox" is Todoist's Inbox project.
- **Calendar → Google:** read/write via the Google connector.
- **Capture:** no smart recorder → they paste voice-memo text; you run the process-transcript logic on it and route results to Notion + Todoist.
- **Health:** they have an Apple Watch but don't care much → skip the port for now.
- **stack-profile:** notes=Notion(connector), tasks=Todoist(connector), calendar=Google(connector), capture=manual, health=none, tier=1, persona="Iris".
- **Smoke test:** create a Todoist task, add a Journal row, generate a one-paragraph briefing from their real calendar. Done in minutes, no filesystem, no scripts.

## Honesty and limits (say these explicitly)

- **Tier 2 automation needs an always-on computer** you can run on with a scheduler. A browser-only user cannot have unattended watchers or scheduled briefings, and you should say so instead of implying otherwise.
- **Some ports need paid services or OAuth** (Notion API, health APIs, a smart recorder). Name the cost/step before the user hits it.
- **Apple Health and Apple Notes/Reminders** are Mac/iOS-gated -- live access needs a Mac in the loop; otherwise use exports or manual entry.
- **Start small.** Bind Notes + Tasks + Calendar and get the daily briefing working first. Add Capture and Health later. A working three-port Tier-1 setup beats a half-built Tier-2 one every time.
