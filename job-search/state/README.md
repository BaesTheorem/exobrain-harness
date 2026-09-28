# job-search/state/ (gitignored)

Runtime state for the scripted discovery lanes. Nothing here is tracked because
the contents reveal where Alex is applying (employer watchlist + posting
snapshots), which is personal data under the repo privacy rules.

To rebuild after a fresh clone: nothing to do. `ats-watchlist.py` regenerates
`ats-snapshot.json` on its first run (that run is a baseline: counts only, the
new-posting diff starts on the second run). `watchlist-extra.json` is optional,
hand-maintained: `{"<ats>:<board>": {"why": "reason"}}` pins boards that have no
listing note yet (e.g. a warm-connection employer we have not audited).

`workday.py` keeps two files here: `workday-snapshot.json` (posting diff, rebuilds
itself on the next run -- that run is a baseline) and `workday-boards.json`, the
hand-pinned board list. The board list is NOT self-rebuilding: tenants already in
the tracker are auto-discovered from `type: job-listing` notes on every run, but a
board pinned with specific filters is only in this file. Re-pin after a fresh clone
with `python3 workday.py --add "<board URL with its filters>" --why "reason"`, then
read back the resolved facet labels it prints to confirm the filters mean what the
URL implied. Schema, one entry per board keyed `"<tenant>/<site>"`:

```json
{"<tenant>/<site>": {"host": "<tenant>.wd1.myworkdayjobs.com", "tenant": "<tenant>",
  "site": "<site>", "facets": {"<facetName>": ["<opaque id>"]}, "search": "",
  "why": "reason", "added": "YYYY-MM-DD", "warm": false}}
```

`ats-blocklist.json` (optional, hand-maintained) holds Greenhouse/Lever/Ashby boards
`ats-watchlist.py` must skip, usually because the employer retired the board and it
404s on every poll. Aggregator boards are blocked in code; this file is only for
employer boards, which is why it is not tracked. Schema:
`{"<ats>:<board>": {"why": "reason"}}`. Missing file = aggregators only.

The two `*.example.json` files here are tracked, with fake entries, to show the
shapes. Copy one without the `.example` infix to start a real list.
