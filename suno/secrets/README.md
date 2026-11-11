# suno/secrets

Everything in this directory except this file is gitignored.

| File | What it is | Rebuild |
| --- | --- | --- |
| `session.json` | The Suno login: the `__client` cookie from `auth.suno.com`, the device id, the Clerk session id, and the last API token with its time | `suno auth import` (reads Chrome) or `suno auth set` (paste) |
| `oauth.json` | The official lane: the OAuth client id that Suno registered for this tool and, after a sign-in, the access token and the refresh token | `suno connect` (registers a client when none is stored) |

The cookie is as good as the password while it lives, so the file is written `0600` and the
CLI never prints it. The API token in the file carries the account's e-mail address and phone
number in its claims, so do not paste the file anywhere. `suno auth clear` deletes it. `suno disconnect` revokes and deletes the tokens in `oauth.json`.

## Getting the login

The short way: sign in at suno.com in Chrome, then run `suno auth import`. Any command does
this by itself when no login is stored. `--browser brave`, `arc` or `edge` reads another
browser (the paths are in the code and were not tested). The first read can show a Keychain
prompt for "Chrome Safe Storage". Allow it.

The manual way, if the import finds nothing:

1. Sign in at suno.com in a browser.
2. Open DevTools > Network and reload the page.
3. Click a request to `auth.suno.com/v1/client`.
4. Under Request Headers, copy the whole value of `cookie:`. It contains `__client=...`.
5. Run `suno auth set`, paste, press Enter.

The paste route was not tested on a live account. The import route was.

A sign-out in that browser makes the cookie invalid. The next command then reads the browser
again by itself.
