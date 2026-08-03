# unemployment/

Tooling for Alex's Missouri unemployment claim on
[UInteract](https://uinteract.labor.mo.gov). Conventions and the full routine
live in the `/unemployment` skill; this file covers the code and the local state.

## Files

| Path | Tracked | What it is |
|---|---|---|
| `uinteract_mcp.py` | yes | MCP server: week deadlines, work-search evidence, filing ledger, correspondence |
| `uinteract.py` | yes | Portal driver: log in, dump claim state, print week deadlines |
| `.chrome-profile/` | **no** | Chrome profile holding the logged-in session |
| `screenshots/` | **no** | Page captures (show claim details, SSN fragments, payment info) |
| `data/` | **no** | Filing ledger, work-search activities, correspondence queue |
| `answers*.json` | **no** | Draft answers to certification questions |

Everything untracked is personal claim data. Nothing in this directory should
ever carry a name, SSN, dollar figure, or claim number into git.

## Credentials

Read from the gitignored harness `.env` at the repo root:

```
UINTERACT_USERNAME=<the UInteract user ID>
UINTERACT_PASSWORD=<the password>
```

To rebuild on a fresh machine: add those two lines to `.env`, then run
`python3 unemployment/uinteract.py open`. The Chrome profile regenerates itself
on first login. Nothing else is needed.

## The MCP server

`uinteract_mcp.py` is a stdio MCP server, zero dependencies, stdlib only. It
covers everything about the claim that is *not* the portal: which weeks are open
and when their money expires, the work-search evidence behind each week, the
filing ledger, and the correspondence queue.

| Tool | What it does |
|---|---|
| `uinteract_weeks` | Benefit weeks with 14-day deadlines and filed/open/expired state |
| `uinteract_work_search` | Assembles a week's evidence from the ledger, job-listing notes, and daily notes; flags a shortfall against the 3/week minimum |
| `uinteract_log_activity` | Records an activity that actually happened, with a date |
| `uinteract_certification_questions` | The questions only Alex can answer, with the trap on each |
| `uinteract_record_filing` | Marks a week filed *after* the portal confirms it |
| `uinteract_correspondence` | Notice queue with deadlines (add / list / resolve) |
| `uinteract_claim_facts` | Portal URLs, DES phone, dates, MoJobs and waiver rules |
| `uinteract_open_login` | Opens the login page for Alex; `confirm: true` required |

Registered in `.mcp.json`, which is **gitignored** -- on a fresh machine, add it
back by hand:

```json
"uinteract": {
  "command": "python3",
  "args": ["/Users/alexhedtke/Documents/Exobrain harness/unemployment/uinteract_mcp.py"]
}
```

Two things it deliberately does not have. There is **no submit tool** (see below),
and **no tool that reads the portal**. The portal half is unreachable by design,
not unfinished -- DES blocks automated login, and that boundary is respected
rather than routed around.

The ledger is local, not a mirror of DES. It only knows what it has been told,
so `uinteract_record_filing` gets called after seeing a week read as filed on the
portal, never optimistically. An unseeded ledger will report a genuinely filed
week as open.

## The portal driver

```bash
python3 unemployment/uinteract.py weeks    # week-endings + 14-day deadlines
python3 unemployment/uinteract.py open     # launch Chrome, log in, leave it open
python3 unemployment/uinteract.py status   # same, plus dump the homepage text
```

Requires Playwright (`pip install playwright`) and Google Chrome at the standard
`/Applications` path.

## It does not submit anything

There is deliberately no "file the weekly claim" command. The weekly request is
a sworn statement under RSMo 288.380, and its questions about earnings,
self-employment, severance, and availability have answers only Alex has. The
tool logs in and parks a browser on the form; Alex answers and submits.

## Two gotchas worth knowing before you touch this

**The site blanks automated pages.** UInteract's Angular app renders only in a
page Chrome opened itself. A `launch_persistent_context` page or a CDP
`new_page()` both go straight to `about:blank`. The working pattern is to spawn
real Chrome with the URL in argv and then `connect_over_cdp` onto the existing
page. Reattaching a second time tends to fail with "Browser context management
is not supported" -- relaunch instead.

**Automated login does not work anyway.** Credentials fill correctly, but
clicking LOG IN reliably closes the Chrome window (reproduced several times,
2026-08-02). `open` still launches Chrome and fills the form, which is useful
for inspecting the page, but expect to sign in by hand:

```bash
open "https://uinteract.labor.mo.gov/benefits/#/benefits/login"
```

**Every login texts Alex.** DES sends an account-accessed SMS on each sign-in,
so don't poll the portal. Idle checking buries the notice that would signal a
genuinely unauthorized login.
