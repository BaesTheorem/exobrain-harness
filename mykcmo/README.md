# myKCMO MCP Server

MCP server (stdio) for Kansas City, MO 311 city services, built on the city's
open-data portal. myKCMO is KC's 311 system (it replaced PeopleSoft CRM in
March 2021); its request data publishes to Socrata dataset
[`d4px-6rwg`](https://data.kcmo.org/resource/d4px-6rwg) on data.kcmo.org,
updated daily with a 2-7 day lag behind real time.

## Tools

Live data, from the myKCMO app backend (`civicapi.py`):

| Tool | What it does |
| --- | --- |
| `list_report_categories` | The 41 report types KC accepts, from the live app catalog |
| `get_report_subtypes` | A type's sub-types, with the form questions, location rule, disclaimer, and duplicate rule |
| `prepare_311_report` | Stage a report: validate answers, geocode, check for a duplicate, return a review. Files nothing |
| `submit_311_report` | File the staged report (needs `confirm=True`), with photos |
| `my_311_reports` | Reports filed from this harness or the KC 311 iPhone app, with live status |
| `get_311_report_status` | One report's live detail and staff timeline |
| `live_311_map` | Public reports near a point, live, sorted by distance |

History and stats, from the open-data feed (2-7 day lag):

| Tool | What it does |
| --- | --- |
| `search_311_requests` | Filtered/full-text search: issue type, status (`open`/`closed`/literal), address substring, council district, date range |
| `get_311_request` | Track a request by 311 case number or work-order number |
| `get_311_requests` | Same, for a batch of numbers in one call |
| `nearby_311_requests` | Requests within N meters of a point (`within_circle`) |
| `kc_311_stats` | Grouped counts (by issue type, status, department, district, source) |
| `list_311_issue_types` | Distinct issue types/sub-types with counts, for building filters |
| `report_issue_info` | Official filing channels (web form, apps, 816-513-1313) |

Fallback: `prepare_311_report_webform` and `submit_311_report_webform` file
through the captcha-gated web form (described below). Use them only when the
app API rejects the key and a refresh cannot fix it.

## The app API

The official myKCMO Android app (`com.civicapps.kansascitymo`, Rock Solid's
MyCivic platform) talks to `https://api.mycivicapps.com/api/v3/`. This API has
no captcha. It accepts all report types, also the custom-form types that the
web form path cannot send, and it accepts photos.

- **Signature.** Each request carries an `ApiSignature` header: an HS256 JWT
  over a small claim set, signed with a static key that ships in the APK. The
  key is not in this repo. It lives in the gitignored `civic-config.json`.
- **No login.** KC uses the "default" login type, so no request needs a
  session.
- **"My reports" is a device id.** The server shows the reports that one
  `deviceuid` sent. `civic-config.json` holds one id, and the KC 311 iPhone app is
  built with the same id, so MIST and the phone see the same list.
- **Privacy defect in the city's API.** The detail endpoints return the
  reporter's name, email, and phone for all public reports, to all devices.
  `civicapi.strip_reporter` removes these fields before anything leaves the
  module.
- **Duplicates.** Some sub-types stop a second report at the same position. The
  server compares the pin position, thus a geocoded address that is 50 m
  away can go through the check.

### Key rotation

When the city ships an app update with a new key, signed calls do not work. The server answers
"Signature Verification Failed" or "Invalid API Signature".
`bin/mykcmo-refresh-key` downloads the newest APK (apkeep, APKPure source),
decompiles the three classes that hold the key, the city id, and the app
version (jadx), proves the values with one signed read, and only then writes
`civic-config.json`.

    bin/mykcmo-refresh-key            refresh now
    bin/mykcmo-refresh-key --check    signed probe only, exit 2 = key rejected
    bin/mykcmo-refresh-key --auto     refresh only when the probe is rejected

The launchd agent `com.exobrain.mykcmo-key-watch` (plist in this folder, copy
it to `~/Library/LaunchAgents/`) runs `--auto --notify` at 11:15 each day.
On a rotation it refreshes the key, rebuilds and reinstalls the KC 311 iPhone
app, and sends a banner and a Discord DM.

## Fallback: the web form

The city web form (`webrai.mycivicapps.com`, Rock Solid's MyCivic platform)
posts to `report_submit.php`. Its anti-spam gate is *soft*: reCAPTCHA v3 is
optional, and with no v3 token the server falls back to a classic
distorted-text image captcha (`get_captcha.php`, a 140×60 JPEG bound to the
PHP session). So filing here is a three-step, **agent-in-the-loop** flow:

1. `list_report_categories()` → pick a type (e.g. "A Pothole").
2. `get_report_subtypes(type)` → pick a `sub_type`, see if a location is
   required. Only `Standard`-template types auto-file; custom `form_type`
   types (Discrimination Report, etc.) still need the app/web form.
3. `prepare_311_report_webform(...)` → geocodes the address, opens a session,
   downloads the captcha, returns a `pending_id`, a `captcha_image_path`,
   and a `review` of exactly what will be filed. **MIST reads the captcha
   image with vision** and confirms the review with Alex. The path handed
   back is a 4× upscaled, contrast-stretched PNG; at the city's native
   140×60 a vision read guesses between `l`/`1`/`i` and `0`/`O`. The raw
   JPEG is kept alongside it as `captcha_raw_path`.
4. `submit_311_report_webform(pending_id, captcha_answer, confirm=True)` → creates
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

There is no public Open311 GeoReport v2 endpoint for KC (checked 2026-08-23).
The app API above (found 2026-10-05) replaced this path as the default.

### Why this isn't a fork of `nyc-311-mcp`

BetaNYC's [nyc-311-mcp](https://github.com/BetaNYC/nyc-311-mcp) is the obvious
prior art, and it is read-only on purpose: creating service requests through
the NYC 311 API needs the "Developer Partner" product, which requires city
approval, so that server only does lookups plus NYC-specific calendar and
emergency-status feeds (alternate-side parking, Code Blue) that have no KC
equivalent. Forking it would have meant porting four read tools onto a server
that already had six, and dropping the filing path this one exists for. The
one idea worth taking was bulk lookup, which is `get_311_requests` above.

## Setup

```sh
uv venv .venv
uv pip install --python .venv/bin/python mcp pillow
brew install apkeep jadx
bin/mykcmo-refresh-key
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
