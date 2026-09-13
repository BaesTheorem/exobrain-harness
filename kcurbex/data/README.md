# kcurbex/data

Gitignored. This is scraped content from a members-only forum that tier-gates
locations on purpose, plus an index of where those locations are. It does not belong
in a public repo, and it should not be republished anywhere.

| File | What it is |
|---|---|
| `reports.json` | The source of truth: one record per site-report thread, plus its geocode. |
| `to_geocode.json` | Hand-off file for the geocoding pass (reports not yet located). |
| `geocoded.json` | Geocoder output, folded back in by `kcurbex geocode-apply`. |

The Obsidian notes under `Areas/Adventure & Creativity/Urbex/Sites/` are a projection
of `reports.json` and are safe to delete and regenerate with `kcurbex vault`.
