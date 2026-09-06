# meetup/secrets

Everything in this directory except this file is gitignored.

| File | What it is | Rebuild |
| --- | --- | --- |
| `cookie.txt` | The browser's `Cookie` header for a logged-in meetup.com session, one line | `meetup auth set` (paste the header), see below |

The cookie is as good as the password while it lives, so the file is written `0600` and the
CLI never prints it. `meetup auth clear` deletes it. `MEETUP_COOKIE` in the environment or the
harness `.env` takes precedence over the file.

## Getting the header

1. Log in at meetup.com in a browser.
2. Open DevTools > Network, reload any page, and click a request to `www.meetup.com/gql2`.
3. Under Request Headers, copy the whole value of `cookie:` (everything after the colon).
4. Run `meetup auth set`, paste, press Enter. It confirms by printing who you are logged in as.

Logging out of that browser session invalidates the cookie; repeat the steps to refresh it.
