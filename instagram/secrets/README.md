# instagram/secrets

Everything in this directory except this file is gitignored.

| File | What it is | Rebuild |
| --- | --- | --- |
| `cookies.txt` | Netscape-format cookies for a logged-in instagram.com session, filtered to instagram.com only | `ig cookies --from-chrome` (below), or a manual export |

The `sessionid` cookie is as good as the password while it lives. The file is written `0600`,
`ig status` prints only cookie *names* and expiry, and nothing here is ever logged.

## Getting cookies

**Automatic (preferred):** log in to instagram.com in Chrome, then

```sh
instagram/bin/ig cookies --from-chrome
```

This uses yt-dlp's Chrome cookie decryptor, keeps only the instagram.com lines, and zeroes the
full jar before the temp dir is removed. No other site's session ever touches disk.

**Manual:** install "Get cookies.txt LOCALLY", export from an instagram.com tab, and save as
`instagram/secrets/cookies.txt`. Needs at least `sessionid` and `csrftoken`.

Instagram rotates `sessionid` roughly yearly and on every explicit logout. If `ig status`
reports expired or a scan comes back `blocked` with a login message, re-export.
