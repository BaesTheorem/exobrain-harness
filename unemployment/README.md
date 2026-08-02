# unemployment/

Tooling for Alex's Missouri unemployment claim on
[UInteract](https://uinteract.labor.mo.gov). Conventions and the full routine
live in the `/unemployment` skill; this file covers the code and the local state.

## Files

| Path | Tracked | What it is |
|---|---|---|
| `uinteract.py` | yes | Portal driver: log in, dump claim state, print week deadlines |
| `.chrome-profile/` | **no** | Chrome profile holding the logged-in session |
| `screenshots/` | **no** | Page captures (show claim details, SSN fragments, payment info) |
| `data/` | **no** | Captured claim/wizard state |
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

## Usage

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

**Every login texts Alex.** DES sends an account-accessed SMS on each sign-in,
so don't poll the portal. Idle checking buries the notice that would signal a
genuinely unauthorized login.
