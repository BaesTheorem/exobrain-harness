# instagram

Read-only Instagram toolkit for the harness. Borrows the logged-in Chrome session and reads
what Kansas City venues and promoters post, so `/local-events` can see the pop-ups, one-off
shows, and flyer-only events that never reach a website or Meetup.

Built 2026-09-06. Nothing here writes to Instagram: no likes, follows, comments, or DMs.

## Why a browser and not the API

Instagram has no public read API, and every anonymous path is closed (the profile and embed
pages render an empty JS shell, `web_profile_info` returns 401 without a session). Calling the
private endpoints with a valid session still draws a 429 on the very first request, because
Instagram scores the request fingerprint, not just the cookie. So the default transport is a
real Chromium (Playwright, same install the `facebook/` toolkit uses) that loads the profile
page and captures the JSON the page itself fetches. The raw HTTP lane is kept behind
`--transport http` for the day Instagram loosens up; do not expect it to work today.

## Setup

```sh
instagram/bin/ig cookies --from-chrome     # needs Chrome logged in to instagram.com
instagram/bin/ig status                    # cookie names + expiry, cooldown, account count
```

See `secrets/README.md` for the manual cookie route and what lives in `secrets/`.

## Commands

```sh
ig accounts                          # the handles a scan will read
ig posts recordbar --days 14         # one account, human-readable (--json for records)
ig scan --days 14 [--media]          # all accounts -> data/kc-events-scan.json
ig scan --only recordbar do816       # a subset, merged into the existing snapshot
ig cooldown [--clear]                # throttle state
```

`--media` also saves the first image of every post under `data/media/<account>/<code>.jpg`
so a vision pass can read flyers. CDN URLs in the snapshot expire within days; the local copy
is the durable one.

## Accounts

The live list is `instagramAccounts` in `local-events/local-events-prefs.json` (gitignored,
edited by the local-events learning loop). `accounts.example.json` is the tracked seed for a
fresh install. Handles were pulled from each venue's own website footer, not guessed;
`ig scan` marks a handle `missing` when the profile page says it is unavailable.

## Snapshot shape

`data/kc-events-scan.json`:

```
generated_at, window_days, transport, status, posts_total, errors[]
accounts[]: username, full_name, followers, biography, status (ok|missing|throttled|error), posts[]
posts[]:    id (ig-<shortcode>), url, taken_at (local ISO), caption, alt_text, location,
            is_video, pinned, images[], likes, local_media (with --media)
```

Venue grids are mostly **collab posts**: the artist authors the post and the venue is a
coauthor, so `owner` is the artist and the venue appears in `coauthors`. Anything the grid's
own timeline query returns is kept regardless of owner; the owner/coauthor check only
applies to records from other payloads (the page also prefetches the home feed, which is
dropped outright).

`alt_text` is Instagram's own accessibility caption ("May be an image of text that says
'FRI SEPT 12 ...'"). It transcribes flyer text for free and is often the only place a date lives.

`status` follows the reddit module's convention so the skill can gate on it: `ok` (every
account read or individually marked), `partial` (throttled mid-run, keep what was read),
`blocked` (nothing read: no cookies, active cooldown, or throttled on the first account).

## Pacing and the cooldown

This is a real person's session. One page load per account, 8-15 s between accounts, 2-4 s
between scrolls, at most 6 scrolls, a 12 s grid wait, and a 14-day window that stops
pagination early. A full run of ~27 accounts takes 12-15 minutes plus about a minute of
image downloads; it is meant for the Sunday weekly review, not for interactive use. Any
login or challenge redirect, or repeated 429s, ends the run and writes `data/cooldown.json`
(90 min); later runs refuse to start until it lapses unless `--force`d. Deeper history is a
second run tomorrow, not a bigger loop today. If Instagram ever challenges the session, open
instagram.com in Chrome once to clear it, then re-export cookies.

## Layout

| Path | What |
| --- | --- |
| `bin/ig` | CLI (auto-registered in the tools registry via `bin/`) |
| `igtools/config.py` | paths, cookie parsing (Netscape + yt-dlp's WebKit stamps), Chrome UA, cooldown |
| `igtools/browser.py` | Playwright transport: page load, embedded-JSON harvest, scroll, owner filter |
| `igtools/fetch.py` | record normalizers for both payload shapes + generic tree extractors |
| `igtools/session.py` | paced raw HTTP lane (`--transport http`), shared throttle rules |
| `igtools/scan.py` | multi-account run -> snapshot, optional media download |
| `secrets/` | cookies (gitignored) |
| `data/` | snapshot, media, cooldown, debug dumps (gitignored) |
| `.profile/` | Playwright's persistent Chromium profile (gitignored) |

Set `IG_DEBUG=1` to dump every captured payload per account to `data/debug/` when the
extractor comes back empty and you need to see what the page actually delivered.
