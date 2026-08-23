# myKCMO MCP Server

MCP server (stdio) for Kansas City, MO 311 city services, built on the city's
open-data portal. myKCMO is KC's 311 system (it replaced PeopleSoft CRM in
March 2021); its request data publishes to Socrata dataset
[`d4px-6rwg`](https://data.kcmo.org/resource/d4px-6rwg) on data.kcmo.org,
updated daily with a 2-7 day lag behind real time.

## Tools

| Tool | What it does |
| --- | --- |
| `search_311_requests` | Filtered/full-text search: issue type, status (`open`/`closed`/literal), address substring, council district, date range |
| `get_311_request` | Track a request by 311 case number or work-order number |
| `nearby_311_requests` | Requests within N meters of a point (`within_circle`) |
| `kc_311_stats` | Grouped counts (by issue type, status, department, district, source) |
| `list_311_issue_types` | Distinct issue types/sub-types with counts, for building filters |
| `report_issue_info` | Official filing channels (web form, apps, 816-513-1313) |

## What it deliberately does not do

Submit new requests. The myKCMO web form (`webrai.mycivicapps.com`, Rock
Solid's MyCivic platform) is gated behind reCAPTCHA v3 plus an icon captcha.
That is an intentional bot gate, so this server hands back deep links instead
of automating around it. There is also no public Open311 GeoReport v2
endpoint for KC (checked 2026-08-23).

## Setup

```sh
uv venv .venv
uv pip install --python .venv/bin/python mcp
claude mcp add --scope user mykcmo -- "$(pwd)/bin/mykcmo-mcp"
```

No credentials required. Optional env vars (put them in the harness `.env`,
which the launcher sources; both are gitignored personal data):

- `MYKCMO_SOCRATA_APP_TOKEN`: a free Socrata app token, only needed if
  anonymous rate limits ever bite.
- `MYKCMO_HOME_LAT` / `MYKCMO_HOME_LON`: default center for
  `nearby_311_requests` so "what's reported near me" works without passing
  coordinates.

## Dataset notes

- Case number lives in `reported_issue`; `workorder_` (trailing underscore is
  real) is the work-order id. `get_311_request` matches either.
- `current_status` is mixed-case in the data (`resolved` and `Resolved`);
  all status filtering here lowercases both sides.
- Pre-March-2021 history is a separate dataset (`7at3-sxhp`) with a different
  schema; not wired up.
