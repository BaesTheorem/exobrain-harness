# reddit — subreddit anecdote miner

Pulls public posts + comment threads from a subreddit into an anonymized JSON corpus
for pattern mining. Built for the ankylosing-spondylitis evidence project (Part B), but
the `--sub` flag makes it general.

## What it does

`reddit-anecdote-fetch.py` hits Reddit's public `.json` endpoints (no API key, no login,
read-only) with a browser User-Agent, paginates a listing, fetches each post's comment
thread, **anonymizes every author at ingest** (one-way hash — no reverse map is stored),
and writes `data/<sub>-corpus.json`.

```bash
# default: r/ankylosingspondylitis, top of the past year, 6 pages
python3 reddit-anecdote-fetch.py

# sanity check — listing only, no comment threads
python3 reddit-anecdote-fetch.py --dry-run --pages 1

# broaden coverage: top/year AND top/all
python3 reddit-anecdote-fetch.py --also-all --pages 6
```

Key flags: `--sub`, `--sort {top,hot,new,controversial}`, `--time {week,month,year,all}`,
`--pages`, `--comments N`, `--pause SECONDS` (rate limit, default 1.2s).

## Privacy

- **Usernames are hashed at ingest** (`anon_<hash>`); the raw handle is never written.
- `data/` is **gitignored** — the corpus is public post text but is not committed, per the
  repo privacy rules (no third-party personal data in the repo).
- Deleted/removed authors and bodies are skipped.
- To rebuild the corpus, just re-run the fetcher; nothing here depends on committed data.

## Downstream

The corpus feeds the Part B extraction agents (theme tagging, intervention mentions,
claimed direction) that produce
`~/Exobrain/Research/Ankylosing Spondylitis — Reddit Anecdote Patterns.md`. Anecdote is
hypothesis-generation only and is never upgraded to evidence.
