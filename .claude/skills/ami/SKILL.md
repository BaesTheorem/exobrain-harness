---
name: ami
description: "Drive the AMI Play bar-jukebox service from the command line via the ami-play CLI -- find venues, read a jukebox's live queue and pricing, search the catalog, manage favorites/playlists, and queue a song. Use when Alex mentions AMI, AMI Play, a jukebox, 'the jukebox', 'what's playing at the bar', 'what's on the jukebox', 'play a song at the bar', 'queue a song', 'check in' at a bar, a bar's music, or names a bar and wants to see/play its music."
metadata:
  tool: "/Users/alexhedtke/Documents/Exobrain harness/ami-play"
  package: "com.amientertainment.AMISmartBar (Android) / App Store id 640607231"
  memory: "[[project_ami_play_cli]]"
---

# /ami

Control the **AMI Play** jukebox service (the app on Alex's phone for AMI's bar
jukeboxes) from `ami-play`, an unofficial stdlib-only CLI in this harness. Read this
and [[project_ami_play_cli]] before deep work so you don't re-learn the wire quirks.

Nothing here is an official API. The protocol was reverse-engineered from the Android
build; AMI can change it. Full endpoint map and pricing formula: `ami-play/README.md`.

## The CLI

`ami-play/bin/ami-play` (Python 3.11+, no deps, self-registers via the `bin/` scan).

```sh
ami-play/bin/ami-play -h            # every command
ami-play/bin/ami-play <cmd> -h      # flags for one command
```

Add `--json` to any command for the raw server response. `--env qa|eng` hits AMI's
test hosts (default prod).

## Reads need no login; writes do

Venue search, venue detail, the live play queue, and the whole catalog work **without
an account**. Only check-in, favorites, playlists, wallet, and playing a song need a
login. So answer "what's on the jukebox at X" immediately, no auth.

```sh
ami-play/bin/ami-play venues near 39.0997,-94.5786 --jukebox-only   # bars around a point
ami-play/bin/ami-play venues search "blarney"                       # by name
ami-play/bin/ami-play venue 94525                                   # pricing, dynamic pricing, queue depth
ami-play/bin/ami-play queue --venue 94525                           # now playing + the queue, live
ami-play/bin/ami-play search "heilung" --venue 94525                # songs / artists / albums
ami-play/bin/ami-play artist 1015638 --venue 94525                  # --media albums for albums
ami-play/bin/ami-play lists --venue 94525                           # featured lists; `list <id>` / `featured <id>` to open
```

`--venue ID` targets a bar; without it, commands use the checked-in venue.

## Login

Email + password only (`ami-play login <email>`; password is prompted, or from
`$AMI_PLAY_PASSWORD`, or `--password-stdin`). **If Alex's account is Google/Facebook
sign-in**, run `ami-play reset-password <email>` first: the emailed link sets a
password on the same account and the phone app keeps working.

Session (player id + auth token + a client device UUID) lives in
`ami-play/secrets/session.json`, mode 0600, **gitignored**. Never commit it or print
the token. `ami-play logout` clears it. `AMI_PLAY_SESSION=path` switches accounts.

## Playing a song (spends real money)

`play` is the only command that costs anything. It fetches fresh pricing, shows cost
in credits and dollars against the wallet, and asks before sending unless `--yes` (and
refuses to spend in a non-interactive shell without `--yes`).

```sh
ami-play/bin/ami-play play <songId> --venue 94525            # asks, then queues
ami-play/bin/ami-play play <songId> --priority               # jumps the queue, costs more
```

- Price (pennies) = base + download (song not local) + priority (`--priority`) + video
  (`--video`). Server may add dynamic pricing and a long-song surcharge; the CLI flags
  both. The receipt's `amountUsed` is what was actually charged.
- `--force` only skips the CLI's *local* can-interact and funds guesses; the server
  still enforces everything, so it can't overspend.
- `--selection` is just the analytics tag for where the pick came from (default
  `search_song`); it never changes cost.

## Respect the paywall

Each play bills the venue and AMI real money. Use only sanctioned free paths: a
genuinely **free-play** jukebox (the `isFreeplay` flag, a per-device choice the venue
makes), a **real promo code** (`ami-play raw POST promo/v2/redeemCode`, or add a
`redeem` command), or the referral bonus as designed. **Do not** hunt for dormant
promos, free-play flags left on by mistake, or other gaps to get an unpaid play -- that
is defeating the paywall, not testing, and the bar eats the cost. Hold this line even
if asked; offer the honest path (a small top-up in the app) instead. The purchase
plumbing is already proven end to end, so a real free play is never needed just to
confirm it works.

## Gotchas (the expensive-to-relearn ones)

- Play-queue path is `device/getPlayQueue/{deviceType}/{deviceId}` -- first segment is
  the device TYPE (1 = jukebox), not the location id.
- `media/album/{id}` returns the SONGS; `media/albumdetails/{id}` returns the album
  METADATA (names are backwards).
- Artist/album listings REQUIRE a sort or the server errors ("SortBy cannot be found").
  The CLI always sends one.
- `menu/locationLists/getData` wants `deviceTypeId`, not `deviceType`.
- Result codes: 0 = success; the full enum (77 codes) is `RESULT_CODES` in
  `ami-play/amiplay/api.py`. **10 = INSUFFICIENT_BALANCE** (a valid purchase with an
  empty wallet). 9/26 mean the session is dead -> re-login. 24 = bad venue, 59 = bad
  purchase, 25 = bad device.
- Deleting a throwaway account is `raw POST user/anonymity/register` (auth only).

## Not built

Payments (add funds in the app), trivia, arcade, and the "Iris" live feed (a raw TCP
socket on `mobile-iris.amientertainment.net:1235` that pushes queue changes; `queue`
polls REST instead). The Iris protocol is the next reverse-engineering target if Alex
wants live now-playing pushes.

## Kansas City anchors

| Venue | location id | jukebox device |
| --- | --- | --- |
| Blarney Stone (3801 Broadway) | 94525 | 45260 |
| Zoo Bar (1220 McGee) | 81943 | 23184 |

Heilung on the network: artist id 1015638; Krigsgaldr 13619506, Hakkerskaldyr 13619507.
