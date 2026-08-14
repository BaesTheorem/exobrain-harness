# job-search/state/ (gitignored)

Runtime state for the scripted discovery lanes. Nothing here is tracked because
the contents reveal where Alex is applying (employer watchlist + posting
snapshots), which is personal data under the repo privacy rules.

To rebuild after a fresh clone: nothing to do. `ats-watchlist.py` regenerates
`ats-snapshot.json` on its first run (that run is a baseline: counts only, the
new-posting diff starts on the second run). `watchlist-extra.json` is optional,
hand-maintained: `{"<ats>:<board>": {"why": "reason"}}` pins boards that have no
listing note yet (e.g. a warm-connection employer we have not audited).
