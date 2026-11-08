# fragrantica: a command-line reader for Fragrantica

`bin/fragrantica` reads [Fragrantica](https://www.fragrantica.com), a perfume database with community votes. It returns the community data for a perfume: rating with the love-to-hate distribution, gender votes, longevity, sillage, price value, seasons, accords, the note pyramid, perfumers, and the "this perfume reminds me of" votes. It also searches the site and makes a list of all perfumes above a vote floor.

## Why a tool is necessary

- Cloudflare blocks plain HTTP requests to the site. A request with a browser TLS fingerprint ([curl_cffi](https://github.com/lexiforest/curl_cffi)) passes.
- Each page carries its vote data as an encrypted payload (`{"ct", "iv", "s"}`), and the site's own script opens it in the browser.
- A headless Chrome that connects to the site itself stays on the Cloudflare challenge page. This tool gives the browser no network access: a route handler serves each request through curl_cffi. Then the page's own opener (`window._pd`) decrypts the payloads of all pages that curl_cffi fetched.

## Commands

```bash
fragrantica search "encre noire"                 # name search (Algolia index)
fragrantica get "terre d'hermes"                 # name, id or URL; prints a summary
fragrantica get 1834 8282 --json                 # one JSON record for each line
fragrantica list --min-votes 5000 --gender male --sort rating --limit 50
fragrantica batch --min-votes 5000 --out /tmp/records.jsonl     # records for a full list
fragrantica batch --ids-file ids.txt --out /tmp/records.jsonl   # one id or URL on each line
```

## Record fields

| Field | Content |
| --- | --- |
| `id`, `url`, `name`, `brand`, `year`, `family`, `marketed_gender`, `perfumers` | From the page and its description |
| `rating` | `avg` (1 to 5), `votes`, `dist` (love, like, ok, dislike, hate) |
| `gender_votes` | female, more_female, unisex, more_male, male, total |
| `male_share`, `female_share` | Share of gender votes for male plus more male (or female plus more female) |
| `masc_index` | Weighted mean of the gender votes: female 0, more female 0.25, unisex 0.5, more male 0.75, male 1 |
| `longevity`, `sillage`, `price_value` | `avg`, `votes`, `dist`, `scale` |
| `seasons` | Vote counts for winter, spring, summer, fall, day and night |
| `relation` | Counts of "I have it", "I had it" and "I want it" |
| `accords` | The page's "main accords", with bar strength (top accord = 100) |
| `notes` | `top`, `middle`, `base` (or `notes` when the page has no pyramid), each note with the image width that the page gives it (widths are different from note to note) |
| `similar` | "Reminds me of" perfumes with yes and no votes |

## Limits

- The public search key gives at most 30 hits for each page of results. The [Algolia default](https://www.algolia.com/doc/api-reference/api-parameters/paginationLimitedTo/) is 1000 hits for each query, so `list` splits vote ranges that contain more perfumes.
- The search key has a rate limit. On 2026-11-08 Algolia returned HTTP 429 after approximately 150 queries in 10 minutes, and the tool then waits up to 75 minutes. A list of 635 perfumes costs 22 queries. Lists are cached for 7 days in `cache/list-<floor>.json`, so a second list with a higher floor costs no queries.
- The minimum interval between page fetches is `--delay` seconds (default 1.0). On a 403 the tool starts a new session and waits. The opener tab uses its own session: in a test that shared one session, the next page fetch got 403 four times, and a new session fixed it.
- Records are cached for 30 days in `cache/perfumes/<id>.json`. `--fresh` fetches again.
- Page code changes on the site can break the parser or the opener. If the page does not define `window._pd`, the error message tells you.

## Requirements

`python3` with `curl_cffi` and `patchright`, and Google Chrome (patchright starts it with `channel="chrome"`, headless). The tool uses no account and sends no identity: only the browser impersonation headers.

The cache (`fragrantica/cache/`) is gitignored.
