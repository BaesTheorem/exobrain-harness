# meetup/secrets

Everything in this directory except this file is gitignored.

| File | What it is | Rebuild |
| --- | --- | --- |
| `cookie.txt` | The browser's `Cookie` header for a logged-in meetup.com session, one line | `meetup auth import` (reads Chrome through yt-dlp) or `meetup auth set` (paste), see below |

The cookie is as good as the password while it lives, so the file is written `0600` and the
CLI never prints it. `meetup auth clear` deletes it. `MEETUP_COOKIE` in the environment or the
harness `.env` takes precedence over the file.

## Getting the cookie

The short way: log in at meetup.com in Chrome (Google sign-in is fine), then run
`meetup auth import`. It uses yt-dlp's browser cookie extractor, keeps only the meetup.com
lines, and confirms by printing who you are logged in as. `--browser safari` or `firefox`
for another browser. The first Chrome read may show a Keychain prompt for
"Chrome Safe Storage"; allow it.

The manual way, if yt-dlp is missing or the import finds nothing:

1. Log in at meetup.com in a browser.
2. Open DevTools > Network, reload any page, and click a request to `www.meetup.com/gql2`.
3. Under Request Headers, copy the whole value of `cookie:` (everything after the colon).
4. Run `meetup auth set`, paste, press Enter.

Logging out of that browser session invalidates the cookie; repeat either way to refresh it.
