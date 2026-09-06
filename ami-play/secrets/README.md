# ami-play/secrets

Everything in this directory except this file is gitignored.

| File | What it is | Rebuild |
| --- | --- | --- |
| `session.json` | AMI Play login (`playerId` + `authentication` token), the client-generated `deviceUUID`, the checked-in venue, and the last geocode used | `ami-play login`, then `ami-play checkin <venue id>` |

The token is as good as the password while it lives, so the file is written `0600`.
`ami-play logout` clears it server-side and locally. Point `AMI_PLAY_SESSION` at another
path to keep several accounts.
