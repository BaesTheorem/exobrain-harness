# kcurbex/secrets

Gitignored. Nothing in this directory may ever be committed.

| File | What it is | How to rebuild |
|---|---|---|
| `credentials.json` | `{"username": ..., "password": ...}` for kcurbex.org | Chrome has the saved login under `https://www.kcurbex.org/ucp.php`; or set `KCURBEX_USERNAME` / `KCURBEX_PASSWORD` in the harness `.env` instead. |
| `cookies.json` | The live phpBB session, so a run does not log in again | Deleted safely at any time; the next run logs back in. |
| `gcal-token.json` | Google OAuth refresh token, `calendar.events` scope only | `bin/kcurbex auth-calendar` |

The Google client id/secret come from the harness `.env`
(`GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`), not from here.

The calendar token is deliberately separate from the backup job's Drive token: a
calendar sync has no business holding a credential that can rewrite Drive.
