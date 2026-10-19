# stalled-repos

Finds public GitHub projects that other people started and stopped before
AI-assisted coding (last commit before 2022-11-30), then ranks them for weird
ideas and dead-but-loved games that are worth finishing now.

## Pipeline

1. `bin/stalled-repos harvest` collects candidates from two sources:
   - Hacker News through the Algolia API: Show HN posts with 30+ points and
     stories with 150+ points that link to a GitHub repo, 2008 to the cutoff.
   - GitHub search: README keywords ("work in progress", "weird", "proof of
     concept") and topics (`esolang`, `creative-coding`, `game-remake`).
2. `bin/stalled-repos enrich [--shard i --shards n]` gets metadata and the
   README of each candidate through GraphQL, 40 repos per call. Run 4 shards
   in parallel for an 11,000-repo harvest (approximately 15 minutes).
3. `bin/stalled-repos rank` removes forks, repos with a commit after the
   cutoff, and lists or course repos. Then it scores the rest and writes
   batch files of 50 repos per lane to `data/batches/`.
4. Agents read each batch with `RUBRIC.md` and write one JSON line per repo
   to `data/judged/`.

All output is in `data/`, which is gitignored. Each step is resumable.

## Requirements

- `gh` with a valid login (the script reads `gh auth token`).
- Python 3.11 or later, standard library only.
