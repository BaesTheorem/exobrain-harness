# mychart/data

This folder holds personal health data. Git ignores everything in it except this file.

| Item | Contents | How to rebuild it |
| --- | --- | --- |
| `accounts.json` | The account list: name, health system, MyChart host, username, FHIR base URL | `mychart accounts add <name> --host <host> --label <name>` for each account |
| `mychart.db` | The chart store: every sync snapshot, the item table, lab values, vital readings, FHIR resources | `mychart sync` and `mychart fhir pull`. The history of old snapshots cannot be rebuilt |
| `fhir-apps.json` | Registered FHIR apps: client ID, redirect URI, scopes | `mychart fhir app add <name> --client-id <id>` |
| `epic-endpoints.json` | A cache of Epic's public FHIR endpoint directory | Rebuilt by itself after 7 days, or with `mychart fhir find <name> --refresh` |
| `ehi/` | Imported EHI exports: the extracted files and one SQLite file for each import | `mychart ehi import <file> --account <name>` |
| `downloads/<account>/` | Files that a download capability saved (documents, statements, attachments, images) | `mychart run download_document --account <name> --arg document_id=...` |
| `logs/bridge.log` | Engine output from each run (request paths, no chart content) | Not needed |
| `alert-state.json` | The last day that a sign-in failure alert went out, for each account | Not needed |

Secrets are not in this folder. Passwords, passkeys, TOTP seeds, sessions, and FHIR tokens are in the macOS Keychain, service `mist-mychart`. A passkey cannot be copied to a second Mac, because its counter must stay in step with the server. On a new Mac, run `mychart login <name>` again for each account.
