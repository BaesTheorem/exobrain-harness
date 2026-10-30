# reddit -- subreddit anecdote miner

Pulls public posts + comment threads from a subreddit into an anonymized JSON corpus
for pattern mining. Generic anecdote-mining tool: point `--sub` at any topic community
(a chronic-illness sub, a hobby sub, a product sub) to build a corpus for downstream
theme extraction.

## What it does

`reddit-anecdote-fetch.py` hits Reddit's public `.json` endpoints (no API key, no login,
read-only) with a browser User-Agent, paginates a listing, fetches each post's comment
thread, **anonymizes every author at ingest** (one-way hash -- no reverse map is stored),
and writes `data/<sub>-corpus.json`.

```bash
# top of the past year, 6 pages
python3 reddit-anecdote-fetch.py --sub <subreddit>

# sanity check -- listing only, no comment threads
python3 reddit-anecdote-fetch.py --sub <subreddit> --dry-run --pages 1

# broaden coverage: top/year AND top/all
python3 reddit-anecdote-fetch.py --sub <subreddit> --also-all --pages 6
```

Key flags: `--sub`, `--sort {top,hot,new,controversial}`, `--time {week,month,year,all}`,
`--pages`, `--comments N`, `--pause SECONDS` (rate limit, default 1.2s).

## Keyword search: `bin/reddit-search`

Reddit's `.json` endpoints are gone (403 since 2026-05), so the anecdote fetcher
above no longer runs. The archive lane that still works is the Arctic Shift API
(see `arctic-shift-scan.py` and `~/Exobrain/recon/2026-08-23-reddit-access-paths.md`).
`bin/reddit-search` is the ad-hoc question tool on that lane:

```bash
reddit/bin/reddit-search kansascity chai --since 2023-01-01   # posts + comment trees
reddit/bin/reddit-search kansascity "chai latte" --no-trees   # titles only
reddit/bin/reddit-search HPfanfiction "diary riddle" --title --top 10   # big sub
```

It searches post titles and bodies one time window at a time, pulls the
comment tree of the `--top` hits with the most comments (default 15), and writes `data/search-<sub>-<query>.json` plus a
summary ranked by comment score. Comment keyword search (`body=`) is refused
with 422 on active subreddits, so comments only come through the trees.

The archive is one volunteer's server. A burst of keyword searches makes it
answer every request with `422 "Timeout. Maybe slow down a bit"` for several
minutes, so the tool paces at 4 s (30 s before a search request), backs off
30 s doubling on that reply or on a 429, prints each backoff to stderr, and
must never run in parallel with itself.

On a large subreddit (r/HPfanfiction), a full-text search times out in all
windows. Use `--title` there: it searches titles in one window from the start
date to now. A run then takes 2 to 10 minutes, because the pages after the
first frequently need some backoff retries. Before `--top`, a search with
hundreds of hits fetched all trees and ran for more than 30 minutes. No author field is written.

## Privacy

- **Usernames are hashed at ingest** (`anon_<hash>`); the raw handle is never written.
- `data/` is **gitignored** -- the corpus is public post text but is not committed, per the
  repo privacy rules (no third-party personal data in the repo).
- Deleted/removed authors and bodies are skipped.
- To rebuild the corpus, just re-run the fetcher; nothing here depends on committed data.

## Downstream

The corpus feeds extraction agents (theme tagging, intervention mentions, claimed
direction) that produce a patterns note in the vault, e.g.
`~/Exobrain/Research/<Topic> Reddit Anecdote Patterns.md`. Anecdote is
hypothesis-generation only and is never upgraded to evidence.
