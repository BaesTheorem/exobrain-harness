# mychart

One command line for all MyChart accounts. `mychart` signs in to each Epic MyChart portal and copies all categories of the chart into a local store. Then it finds the changes and sends one digest when a new item arrives. Claude can use the same accounts and store through a local MCP server. Two more channels read the official record: SMART on FHIR (the Cures Act patient API) and the EHI export (the complete record as Epic's tables).

All work occurs on this Mac. Credentials are in the macOS Keychain. Chart data is in `data/`, which git ignores.

## First steps

```bash
mychart accounts find "health system name"          # find the MyChart host (no sign-in)
mychart accounts add clinic --host mychart.example.org --label "Example Health"
mychart login clinic                                 # password and 2FA code one time; registers a passkey
mychart sync                                         # pull every account into the store
mychart new                                          # what changed
```

To add an account in the future, use `accounts add` and `login` again. Nothing else changes.

## Commands

| Command | What it does |
| --- | --- |
| `mychart accounts` | Shows each account, its saved sign-in methods, its FHIR status, and its last sync |
| `mychart accounts add NAME --host HOST [--label] [--fhir-base]` | Adds an account. `accounts set` changes an account, and `accounts set NAME --skip referrals` removes a category that the portal does not have from the sync. `accounts remove NAME --yes` removes the account |
| `mychart accounts find TEXT` | Searches Epic's MyChart directory for a host |
| `mychart login NAME [--method passkey\|totp\|password]` | Signs in one time. The default adds a passkey, so subsequent syncs do not use a password or a code |
| `mychart sync [NAME\|all] [--notify]` | Copies approximately 30 categories for each account into the store |
| `mychart new [--days N] [--all]` | Shows the changes that recent syncs found |
| `mychart show WHAT [--live] [--json]` | Reads one category from the store: `labs`, `imaging`, `meds`, `messages`, `appointments`, `visits`, `bills`, `letters`, `documents`, `allergies`, `problems`, `immunizations`, `referrals`, `orders`, `vitals`, `profile`, `insurance`, or any `get_*` capability |
| `mychart labs [--test NAME]` | Shows the lab components of all accounts, or the values of one component in date sequence |
| `mychart search TEXT` | Finds text in all stored items |
| `mychart run CAPABILITY [--account NAME] [--arg k=v]` | Does one engine capability live. A write must have `--yes` |
| `mychart capabilities [--all]` | Shows all capabilities of the engine |
| `mychart sql "SELECT ..."` | Does a read-only query on the store |
| `mychart status` | Shows the engine, the store, the accounts, and each category that failed on its last 3 reads |
| `mychart doctor` | Examines the saved secrets, removes a damaged one, and moves a rescued passkey into the Keychain |
| `mychart fhir ...` | The FHIR lane (see below) |
| `mychart ehi ...` | The EHI lane (see below) |

For output that a script can read, put `--json` before the command.

## How a sync works

1. The CLI reads the passkey of the account from the Keychain and starts `bridge/bridge.mjs` in Node.
2. The bridge signs in and does each read capability of the engine. For each capability, it gives the standard object and the raw envelope (all requests and responses).
3. The store records a snapshot for each capability. The CLI compresses each payload and stores it by its hash. It keeps the raw envelope only when the data changed.
4. Extractors make one item for each lab result, message, statement, bill, appointment, letter, document, medication, problem, allergy, immunization, referral, and medical order. The item table is the source for change detection, `show`, and `search`.
5. The first read of a category is a baseline. The store records its items, but they do not cause a notification.

MyChart sends no out-of-range flag for lab values (the labs README of the engine records this). Thus `mychart` compares each value with its reference range and marks the values that are out of range.

When two health systems hold the same lab result (for example through Care Everywhere), the result appears in the two accounts. The `lab_values_merged` view groups the copies by component, value, unit, and day. It also records the source accounts.

## Notifications

`mychart sync --notify` sends one digest for each sync: one banner and one Discord DM. The text has counts only, for example "New in MyChart. Example Health: 2 lab results, 1 message." Test names, values, and message text do not go to Discord. A click on the banner opens a Console chat with the item summaries as context.

If a sign-in fails, the CLI sends a maximum of one alert for each account on each day. If the network is not available, the CLI stops the sync with no alert, because the next sync tries again.

## Scheduled sync

`com.exobrain.mychart-sync.plist` starts `mychart sync --notify --fhir` at 07:30, 13:30, and 19:30 through `mist-launch`. The 07:30 sync occurs before the morning briefing. The task sets `MIST_UNATTENDED=1`, thus it cannot write to a chart or wait for an answer from a person. The sync does not include accounts that have no saved sign-in. The log file is `~/Library/Logs/exobrain/mychart-sync.log`.

To install it or load it again:

```bash
cp mychart/com.exobrain.mychart-sync.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.mychart-sync.plist
```

## MCP server

`bin/mychart-mcp` is a stdio MCP server with 13 tools: `mychart_accounts`, `mychart_get`, `mychart_items`, `mychart_changes`, `mychart_lab_trend`, `mychart_search`, `mychart_capabilities`, `mychart_run`, `mychart_sync`, `mychart_prepare_message`, `mychart_prepare_reply`, `mychart_send`, and `mychart_fhir_resources`. It is registered at user scope and starts through `mcp-lazy`:

```bash
claude mcp add-json --scope user mychart '{"type":"stdio","command":"<harness>/mychart/bin/mychart-mcp"}'
mcp-lazy/bin/mcp-lazy wrap mychart
```

`security/bin/mist-frame` puts each result that contains chart text in an UNTRUSTED block, because care teams, labs, and billing offices wrote that text. `mychart_run` only reads. To send a message, the model uses `mychart_prepare_message` or `mychart_prepare_reply`, shows the preview, and then uses `mychart_send` with `confirm=True`. In an unattended session, `mychart_send` refuses.

## FHIR lane

SMART on FHIR is the standard patient API that the 21st Century Cures Act requires. It gives coded data (LOINC, RxNorm, SNOMED) that the portal does not show. It must have a registered app.

1. Make a patient-facing app at https://fhir.epic.com (Build Apps): audience Patients, auto-download on, the USCDI R4 read and search APIs, R4, SMART v1 scopes, a confidential client, and "Requires Persistent Access". Use the redirect URI `https://localhost:8443/callback`. Epic requires https in production and compares the URI character by character.
2. Make the certificate for that callback one time: `mychart fhir tls`. The browser warns one time when Epic sends it back to localhost, unless you trust the certificate with the command that `tls` shows.
3. Give the client IDs to the CLI. Use the non-production ID for the Epic sandbox and the production ID for real accounts: `mychart fhir app add epic --client-id <ID>`.
4. Epic issues a client secret for each health system ("Review & Manage Downloads", then "Get Secrets"). Give each secret to its account: `mychart fhir secret NAME < secret.txt`.
5. Find the FHIR base URL of each organization with `mychart fhir find "health system name"`. Then use `mychart accounts set NAME --fhir-base <URL>`.
6. Sign in one time in the browser: `mychart fhir login NAME --consent-days N`, where N is the access period that you select on the consent screen. `mychart fhir status` warns 14 days before that period ends.
7. Copy the data: `mychart fhir pull`. Read it: `mychart fhir show NAME Observation --code <LOINC>` or `mychart fhir status`. The scheduled sync also pulls FHIR data, a maximum of one time each week for each account.

To test with the Epic sandbox, add an account with the FHIR base `https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4`. Then sign in as the Epic test patient `fhircamila` (password `epicepic1`).

A test of the FHIR lane against the SMART Health IT sandbox passed from start to end: PKCE sign-in, refresh-token renewal, and a pull of 315 resources. If a sandbox has no login page, `--follow` signs in to it with no browser.

## EHI lane

An EHI export (ONC criterion b(10)) is the most complete record that a patient can get: the tables of Epic as tab-separated files, plus notes as RTF files and media. Each health system makes one when the patient sends a request.

```bash
mychart ehi import ~/Downloads/export.zip --account clinic    # one SQLite file per import
mychart ehi tables clinic --grep ORDER
mychart ehi verify clinic                                     # compares the export with the sync store
```

The import refuses an archive member if its path goes out of the target folder. Epic gives the documentation for each table at https://open.epic.com/EHITables. For a full conversion of an export to FHIR, refer to `jmandel/ehi-to-fhir` (MIT).

## Engine

The engine is the `mychart-cli` library from [OpenRecord](https://github.com/Fan-Pier-Labs/openrecord) by Fan Pier Labs. Its license lets a person use it for personal, non-commercial work, but it does not let a person distribute it. Thus this repo does not contain the engine. The engine is a local checkout at `~/Documents/openrecord`, at the commit in `ENGINE_PIN`. The npm release is older than the repository, thus Bun builds the engine from source.

```bash
mychart/bin/mychart-engine install     # clone, check out the pin, build
mychart/bin/mychart-engine status
mychart/bin/mychart-engine update      # move to origin/main, build, smoke-test, then move the pin
```

Before `update` moves the pin, it tests the new build against the public fake MyChart (`fake-mychart.fanpierlabs.com`). If the test fails, it goes back to the previous commit. The telemetry and the update check of the engine are off (`MYCHART_CLI_TELEMETRY_DISABLED=1`).

## Security

- Passwords, passkeys, TOTP seeds, sessions, FHIR tokens, and app secrets are Keychain items of the service `mist-mychart`. `security -i` cuts a command line at 4,096 bytes, thus the CLI keeps a long value (a session is approximately 4,000 characters) as numbered parts. They go to the bridge on stdin. They do not go in argv, env, or a file. The CLI writes them through `security -i` on stdin, thus the value does not show in a process list.
- A passkey has a counter that must stay in step with the server. The CLI saves each new counter immediately. If the counter falls behind, the bridge tries again one step at a time, a maximum of 10 times. Do not copy a passkey to a second Mac. Use `mychart login` on that Mac.
- `mychart login` adds a passkey to the MyChart account. MyChart shows it in its security settings. `--method totp` starts authenticator-app 2FA for the account. This changes how the person signs in on all devices. Use it only if the portal refuses passkeys.
- When `MIST_UNATTENDED=1`, no write occurs and the CLI shows no prompt.

## Tests

```bash
pytest tests/test_mychart.py
```

The tests use a temporary data folder, an in-memory Keychain, and a stub engine for the bridge. They do not use the network.

## Files

| File | Purpose |
| --- | --- |
| `mychart_cli.py` | The CLI, sync, and notifications |
| `mychart_core.py` | Accounts, the Keychain, and the bridge client |
| `mychart_store.py` | The SQLite store, extractors, and change detection |
| `mychart_server.py` | The MCP server |
| `mychart_fhir.py` | The FHIR lane |
| `mychart_ehi.py` | The EHI lane |
| `bridge/bridge.mjs` | The Node bridge to the engine |
| `bin/mychart`, `bin/mychart-mcp`, `bin/mychart-engine` | Launchers |
| `ENGINE_PIN` | The engine commit |
| `data/` | Personal data (git ignores it; see `data/README.md`) |
