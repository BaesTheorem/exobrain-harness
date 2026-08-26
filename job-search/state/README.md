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
URL implied.
