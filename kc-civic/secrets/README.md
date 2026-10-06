# kc-civic/secrets

Gitignored. Nothing here may be committed.

| File | What | Rebuild |
|---|---|---|
| `gcal-token.json` | Google OAuth refresh token, `calendar.events` scope only | `bin/kc-civic auth-calendar`, open the URL, approve, then `bin/kc-civic auth-calendar --code '<redirected URL>'` |

The OAuth client id and secret come from the harness `.env` (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`). Set `KCCIVIC_CALENDAR_ID` there to write to a calendar other than primary.
