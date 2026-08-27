# facebook

General-purpose, **read-only** Facebook toolkit. Drives a real logged-in browser
via exported session cookies and reads the feed's own GraphQL, because Facebook
killed the Groups API and CrowdTangle and the UI has no "sort by reactions".
Works on any group / page / profile feed via named **targets**.

Built originally to rank a private meme group by all-time reactions, but nothing
here is meme-specific: point it at any feed you can see while logged in.

## Install / invoke

`bin/fb` is a self-contained CLI (auto-registers via the tools registry's `bin/`
scan). Run it directly:

```sh
"facebook/bin/fb" status
```

Or add `facebook/bin` to PATH and just call `fb`.

## What's gitignored (and how to rebuild it)

Nothing personal is committed. Only code + this README are tracked.

| Path | What it is | Rebuild |
| --- | --- | --- |
| `secrets/cookies.txt` or `.json` | Live facebook.com session cookies | Re-export from the browser (below) |
| `secrets/targets.json` | name -> feed URL map | `fb crawl <name> --url <url>` |
| `.profile/` | Playwright browser profile (persisted session) | Regenerates on next run |
| `data/<target>/raw/*.jsonl` | Raw GraphQL responses | Re-run `fb crawl` |
| `data/<target>/posts.jsonl` | Parsed, ranked posts | Re-run `fb parse` |
| `report/<target>/` | Reports + downloaded images | Re-run `fb report` |

## Handing over cookies

1. Log in to facebook.com in a browser.
2. Install **"Get cookies.txt LOCALLY"** (runs locally, exports nothing).
3. On a facebook.com tab, **Export** -> save as `facebook/secrets/cookies.txt`.
   (JSON exports also work as `secrets/cookies.json`.)
4. Needs at least `c_user` and `xs`. `fb status` verifies. Cookies expire; if a
   crawl bails with a login/checkpoint message, re-export.

## Workflow

```sh
fb status                                   # cookies + targets + data health
fb find-group "dank ea"                     # find a group's URL from your joined groups
fb crawl dank-ea-memes --url <group URL>    # first run registers the target
fb crawl dank-ea-memes                      # resume, walking further back (default 25 min)
fb crawl dank-ea-memes --minutes 15         # a shorter burst
fb parse dank-ea-memes                      # offline: raw -> ranked posts (safe to re-run)
fb report dank-ea-memes --top 25 --per-year 10
fb authors dank-ea-memes --top 5            # author leaderboards: peak + cumulative, per year
```

`fb authors` scores each author two ways in every year and all time: **peak**
(their single most-reacted meme) and **cumulative** (total reactions across all
their memes). Anonymous group posts are excluded. Writes `authors.md` +
`authors.json` to `report/<target>/`.

`crawl` -> `parse` -> `report`. Re-crawl adds history; re-parse and re-report any
time without touching the browser. Reports land in `report/<target>/`:
`top-memes.md` (overall top-N + a year-by-year summary table) and `by-year.md`
(each year's top posts), plus downloaded images and a `report.json`.

## Guardrails

- **Read-only.** Never reacts, comments, posts, joins, or clicks into a post.
  It navigates and scrolls the chronological feed and records the GraphQL the
  page fetches. The `session.py` module enforces this by only ever scrolling.
- **Paced.** Randomized human-ish scroll delays, a per-session time cap, and a
  persistent profile so the fingerprint stays stable. Automated cookie use is
  against Facebook's ToS; the realistic worst case is an identity checkpoint,
  not a ban, but it's your account, so keep sessions modest and spaced out.
- **Local.** All output stays on this machine. Private groups are full of real
  people; none of it goes to a repo or any external service.

## How the parser survives Facebook's obfuscation

FB's feed GraphQL is deeply nested and the field paths drift. Rather than
hardcode paths, `parse.py` walks the JSON structurally: it finds every dict that
owns a `feedback` object (a post), reads the shallowest reaction/comment/share
counts inside that feedback (breadth-first, so a preview comment's counts never
masquerade as the post's), and scrapes caption text + fbcdn image URLs from the
post's subtree. Dedup is by post id, keeping the max reactions ever seen. If
extraction misses fields against real data, fix `parse.py` and re-run it on the
saved raw dumps. No re-crawl needed.

## Reusing the session elsewhere

```python
from fbtools.session import FacebookSession, RawWriter

with FacebookSession(headless=True) as fb:
    for g in fb.discover_groups():
        print(g["name"], g["url"])
```
