# Fork notes

This directory started as a vendored fork of
[TheDigitalNinja/mcp-fitbit](https://github.com/TheDigitalNinja/mcp-fitbit) at
**v1.0.1**. On 2026-11-02 its backend was replaced, and no upstream code is left.

## Why the backend changed

Google turned off the legacy Fitbit Web API and its OAuth endpoints on
2026-10-30. Every call, the token refresh included, now returns HTTP 410 with
this body:

> The legacy Fitbit Web API and OAuth 2.0 endpoints were decommissioned on
> October 30, 2026. Please migrate your integration to the Google Health APIs

Re-consent cannot fix that. The successor is the
[Google Health API v4](https://developers.google.com/health)
(`https://health.googleapis.com/v4`). Its discovery document is the source of
truth for paths, filters and schemas:
`https://health.googleapis.com/$discovery/rest?version=v4`.

## What stayed the same

- The MCP server name is still `fitbit`. The tool names and arguments are the
  old ones, because the harness skills call `mcp__fitbit__<tool>` directly.
- `bin/fitbit-mcp`, `bin/fitbit-reauth` and `bin/fitbit-token-check` keep their
  names and jobs. The launchd job is still `com.exobrain.fitbit-token`.

## What changed

- **Responses are Google's raw JSON**, not Fitbit's shapes. Read the
  `dataPoints` (or `rollupDataPoints`) a tool returns. Units follow Google:
  weight in grams, distance in millimeters, temperatures in Celsius.
- **Auth** (`src/google-auth.ts`) uses the harness's existing Google OAuth web
  client (`GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`). Its Cloud
  project is published "In production", so the refresh token does not die
  after 7 days the way a "Testing" token does. The Drive backup has uploaded through
  the same client since 2026-08-28 (72 uploads by 2026-11-02).
- **The single-use refresh-token race is gone.** Fitbit burned a refresh token
  on use, so concurrent servers raced for it. Google refresh tokens are
  reusable. The server still re-reads the token file before a refresh, so a
  re-consent is adopted without a restart.
- **Time shapes.** Each data type is a sample, an interval, a daily summary or
  a session, and each shape filters on a different field
  (`src/google-health.ts` `dateFilter`). Sleep filters on its civil end time,
  so a night is filed under the morning it ended, as Fitbit's `dateOfSleep` was.
- **Roll-ups.** Daily totals come from `dataPoints:dailyRollUp`, capped at 90
  days per call (14 for heart-rate, active-minutes, total-calories and
  calories-in-heart-rate-zone). `dailyRollUp()` splits longer ranges.
- **Gone:** `get_activity_goals`. The API has no goals resource. The tool
  stays registered and returns an error that says so.
- **New:** `get_data_points` and `get_daily_rollup` give raw access to any data
  type, for example per-second `heart-rate` or `daily-vo2-max`.

## Tool map

| Tool | Google data type(s) |
| --- | --- |
| `get_profile` | `users/me/profile`, `settings`, `identity`, `pairedDevices` |
| `get_sleep_by_date_range` | `sleep` |
| `get_hrv_by_date_range` | `daily-heart-rate-variability` |
| `get_spo2_by_date_range` | `daily-oxygen-saturation` |
| `get_breathing_rate_by_date_range` | `daily-respiratory-rate` |
| `get_temp_skin_by_date_range` | `daily-sleep-temperature-derivations` |
| `get_heart_rate`, `get_heart_rate_by_date_range` | `daily-resting-heart-rate`, `daily-heart-rate-zones` |
| `get_daily_activity_summary` | roll-ups of `steps`, `distance`, `floors`, `active-zone-minutes`, `active-minutes`, `active-energy-burned`, `total-calories`; plus `daily-resting-heart-rate` |
| `get_activity_timeseries` | roll-up of `steps`, `distance`, `total-calories`, `active-energy-burned`; raw `basal-energy-burned` for `caloriesBMR` |
| `get_azm_timeseries` | roll-up of `active-zone-minutes` |
| `get_exercises` | `exercise` |
| `get_weight` | `weight`, `body-fat` |
| `get_food_log` | `nutrition-log`, `hydration-log` |
| `get_nutrition`, `get_nutrition_by_date_range` | roll-up of `nutrition-log` (or `hydration-log` for `water`) |

## Operations

- Consent: `bin/fitbit-reauth` (interactive), or `bin/fitbit-reauth url` then
  `bin/fitbit-reauth code '<redirected https://www.google.com/?code=... URL>'`.
  It writes `.google-health-token.json` (gitignored, mode 600) and prints the
  identity, which proves the account is linked to Google Health.
- `ACCOUNT_NOT_LINKED` from `users/me/identity` means the Google account has
  not signed in to the Google Health app yet.
- Token check: `scripts/token-check.mjs`, every 6 hours from launchd, run as
  `/opt/homebrew/bin/node <file>` with no shell wrapper (TCC). Exit 0 healthy,
  1 consent needed, 2 inconclusive; three inconclusive runs in a row escalate.
- Build: `npm ci && npm run build`. Tests: `npm test` (mocked fetch; no network).
