# bugcrowd

`bin/bc-rank` ranks the public Bugcrowd bug bounty programs. The first sort
key is how fast the vendor accepts a report. The second sort key is how
probable it is that a new researcher gets a valid finding. The script reads
only public, logged-out endpoints and needs no account.

## Data sources

| Endpoint | Gives |
| --- | --- |
| `/engagements-us?category=bug_bounty&...` | The program list, 24 programs on each page |
| `/engagements/<code>` | The brief page, which contains the changelog id |
| `/engagements/<code>/changelog/<id>.json` | Scope: targets, categories, P1 to P5 reward ranges, safe harbor |
| `/engagements/<code>/statistics` | Rewarded count, average payout, the "validation within" label |
| `/engagements/<code>/crowdstream.json?page=N` | Accepted submissions in the last 6 months, with submit and accept dates and priority |

## Speed

Speed is the median number of days from `created_at` to `accepted_at` over a
program's accepted submissions in the crowdstream. A program with less than 3
accepted submissions uses its published "validation within" label. The label
measures validation and the crowdstream measures acceptance, so the two
sources do not measure the same step.

## Feasibility

The script calculates the feasibility score from these items:

- the share of accepted submissions that are P4 or P5
- if P4 pays cash
- the number of wildcard targets
- if web or API targets are in scope
- the number of accepted submissions
- if there is an accepted submission in the last 30 days

A program with only hardware, IoT, or blockchain targets loses points. The
weights are a judgment, and the script writes them at the top of the report.

## How to use it

```bash
bugcrowd/bin/bc-rank                 # all programs, output in ~/Documents/bounty-work/bugcrowd
bugcrowd/bin/bc-rank --limit 5       # test on 5 programs
bugcrowd/bin/bc-rank --refresh       # fetch again, do not use the cache
```

The script caches every response under `<out>/raw/<code>/`. The next run
fetches only the data that is missing. The output is `ranked-<date>.csv` and
`ranked-<date>.md`.
