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
| `list_report_categories` | The 41 report types KC accepts |
| `get_report_subtypes` | A type's sub-types, template kind, location/description rules |
| `prepare_311_report` | Stage a real request + fetch its captcha image to read |
| `submit_311_report` | File the staged request (needs `confirm=True` + captcha answer) |

## Filing a request (the write side)

The city web form (`webrai.mycivicapps.com`, Rock Solid's MyCivic platform)
posts to `report_submit.php`. Its anti-spam gate is *soft*: reCAPTCHA v3 is
optional, and with no v3 token the server falls back to a classic
distorted-text image captcha (`get_captcha.php`, a 140×60 JPEG bound to the
PHP session). So filing here is a three-step, **agent-in-the-loop** flow:

1. `list_report_categories()` → pick a type (e.g. "A Pothole").
2. `get_report_subtypes(type)` → pick a `sub_type`, see if a location is
   required. Only `Standard`-template types auto-file; custom `form_type`
   types (Discrimination Report, etc.) still need the app/web form.
3. `prepare_311_report(...)` → geocodes the address, opens a session,
   downloads the captcha, returns a `pending_id`, a `captcha_image_path`,
   and a `review` of exactly what will be filed. **MIST reads the captcha
   image with vision** and confirms the review with Alex.
4. `submit_311_report(pending_id, captcha_answer, confirm=True)` → creates
   the real 311 case, returns the work-order id (track it with
   `get_311_request` after the 2-7 day feed lag). A wrong captcha re-fetches
   a fresh image to read and retry.

### Why this is in bounds, and the guardrails

This automates **Alex's own** civic reports: one real request at a time,
carrying his real contact info, at human pace, with an explicit confirmation
before each submission, and with MIST (not a solver farm) reading the
human-intended captcha. That is a resident filing legitimate 311 requests,
which is exactly the traffic the city wants; the captcha is collateral
friction. It deliberately does **not** bulk-submit, auto-fire without
`confirm=True`, forge a reCAPTCHA score, or run any unattended solve loop.
It is not a captcha-solving service and must not be repurposed as one.

There is no public Open311 GeoReport v2 endpoint for KC (checked 2026-08-23);
this web path is the only programmatic way to file.

## Setup

```sh
uv venv .venv
uv pip install --python .venv/bin/python mcp
claude mcp add --scope user mykcmo -- "$(pwd)/bin/mykcmo-mcp"
```

No credentials required. Optional env vars (put them in the harness `.env`,
which the launcher sources; all are gitignored personal data):

- `MYKCMO_SOCRATA_APP_TOKEN`: a free Socrata app token, only needed if
  anonymous rate limits ever bite.
- `MYKCMO_HOME_LAT` / `MYKCMO_HOME_LON`: default center for
  `nearby_311_requests` so "what's reported near me" works without passing
  coordinates.
- `MYKCMO_CONTACT_FIRST` / `MYKCMO_CONTACT_LAST` / `MYKCMO_CONTACT_EMAIL` /
  `MYKCMO_CONTACT_PHONE`: Alex's real contact info, used as the default
  reporter on filed requests (KC emails the case confirmation there). Email
  is required to file; the rest are optional. Never hardcode these.
- `MYKCMO_CAPTCHA_DIR`: where captcha images are written for MIST to read
  (defaults to the harness `tmp/images/`).

## Dataset notes

- Case number lives in `reported_issue`; `workorder_` (trailing underscore is
  real) is the work-order id. `get_311_request` matches either.
- `current_status` is mixed-case in the data (`resolved` and `Resolved`);
  all status filtering here lowercases both sides.
- Pre-March-2021 history is a separate dataset (`7at3-sxhp`) with a different
  schema; not wired up.
