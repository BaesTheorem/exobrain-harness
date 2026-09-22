# shopping/secrets

Gitignored. Nothing in here is committed except this file.

## `amazon-cookies.json`

The live amazon.com session, exported from Chrome by `amz auth --from-chrome`.
Playwright-shaped cookie dicts, `chmod 600`.

**Rebuild it:** sign in to amazon.com in Chrome, then run `amz auth --from-chrome`.
Reading Chrome's cookie store requires the "Chrome Safe Storage" key from the
login Keychain, so macOS may prompt for approval on the first run.

**No password is stored, read, or required anywhere in this tool.** The login
is always performed by hand in a real browser. Automating an Amazon sign-in is
what trips anomaly detection and locks accounts, so the tool deliberately
cannot do it.

**Treat the file as a credential.** It is equivalent to a signed-in browser.
Amazon re-authenticates for payment and address changes, so it is not enough on
its own to move money, but it does expose order history, addresses and lists.

Sessions expire. `amz auth --status` prints the expiry of each auth cookie;
re-export when it lapses. A lapsed session renders signed-out pages, which is
why every account-level command raises on a sign-in wall instead of returning
an empty list.
