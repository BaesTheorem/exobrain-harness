# suno

A command line for [suno.com](https://suno.com). It makes songs, reads the library, gets
timed lyrics, and downloads audio, from a terminal or a script. It uses the account's own
browser login.

```
suno status                          plan, credits, downloads left, bot-check condition
suno list -n 20 -s "rain"            the library, newest first
suno info <clip>                     one song: style, lyrics, lock condition, link
suno lyrics <clip> --lrc             line-timed lyrics (also --words, --json)
suno generate --tags "..." --lyrics-file song.txt --title "..." --yes --wait
suno describe "a slow piano piece for a rainy morning" --yes --wait
suno download <clip> --yes           audio plus lyrics and metadata
suno doctor --drift                  health checks and the request-shape check
suno connect                         sign in to Suno's official interface (see below)
```

`<clip>` is a full id, a `suno.com/song/...` link, or the short id that `suno list` prints.
Add `--json` to a command for machine-readable output.

## Read this first: Suno has an official interface

Suno has an official MCP server in beta at `https://api.suno.com/mcp`. It uses an OAuth
sign-in. Suno's FAQ says that it is open to all plans, the Free plan included
([Suno help: Suno MCP (Beta)](https://help.suno.com/en/categories/2817153-suno-mcp-beta),
three articles, each edited 2026-10-28). The scopes that the server gives in its OAuth
metadata include `credits:spend`, `download`, `library:read` and `library:write`. Suno's
page names Covers, Extends, Mashups, Speech and audio upload.

Suno opens that interface one account at a time. On 2026-11-11 the sign-in for a paid
account stopped at Suno's consent page. The page said that connecting AI apps was not
available for that account at that time. This tool does not go around that.

Thus the tool has two lanes:

| Lane | Commands | Condition |
| --- | --- | --- |
| Official | `connect`, `disconnect`, `tools`, `call` | Ready. The sign-in was tested as far as the consent page. No tool call was made, because no account that could sign in was available. |
| Web | all other commands | In use. These send requests to the endpoints that the suno.com website calls (`https://suno.com/a/api/...`). Suno does not document those endpoints and can change them without notice. |

`suno connect` opens Suno's consent page in the browser and waits four minutes for the
answer. When it succeeds, `suno tools` shows what the official interface offers, and the
paid commands (`generate`, `describe`, `download`) must then move to it. That work needs the
official tool list, which only a signed-in account can read.

The text below is about the web lane. Where a different lane applies, the text names it.

## The two things that cost something

| Command | Cost | Gate |
| --- | --- | --- |
| `generate`, `describe` | Credits. [Suno's v6 FAQ](https://help.suno.com/en/articles/13924481) gives 10 credits for one generation of two songs. Max Mode costs more. Three test generations cost 10 each. | Asks at a terminal. Needs `--yes` in a script. `--dry-run` prints the request and sends nothing. |
| `download` of a locked song | One of the plan's downloads for the period. Suno sells more downloads in packs of 1 to 10. | Asks at a terminal. Needs `--yes` in a script. Shows the number that remains first. |

A song that was unlocked before downloads again at no cost. The command tells you which
condition applies before it spends.

Each paid request gets a receipt in `state/receipts/` before it is sent:

- The same `--request-id` with the same content returns the saved songs and sends nothing.
- A request with the same content in the next 30 minutes is blocked. `--force` sends it.
- If no answer comes back, the receipt is marked `unknown` and the exit status is 6. A request
  with the same content is then blocked. Read `suno list` before you try again.
- `suno jobs` shows the receipts.
- `state/spend.jsonl` has one line for each spend, with the balance that Suno gave before
  and after.

## What you cannot do, and why

- There is no audio without a download. A clip's `audio_url` is a placeholder. The stream
  that the website plays is encoded for Suno's own player, and this tool does not decode it.
  The download flow is the only source of an audio file, and Suno counts it against the plan.
- There is no playback in the terminal. `generate` prints a `suno.com/song/...` link for
  each song. Listen there, then download the song that you want.
- There are no covers, extends, uploads, stems or personas. Suno's page names most of them
  for the official interface. No web request was captured for them, and this tool sends only
  requests that were captured.

## How it works

### Login

`suno auth import` reads the `__client` cookie for `auth.suno.com` from Chrome. The code
also has the folder paths for Brave, Arc and Edge, and those were not tested. It stores
the cookie in `secrets/session.json` with mode `0600`.
Suno's sign-in server changes that cookie into an API token with a life of one hour. The CLI
gets a new token after 20 minutes. Each command imports the login by itself when none is
stored. See `secrets/README.md`.

### Bot check

Before a generation, the website asks Suno if a check is necessary. If it is, the website
shows a Cloudflare Turnstile widget and sends the token from the widget. The CLI does the
same in a headless Chrome with no cookies and no window (approximately 2.5 s). It uses no
solver. If the widget asks for a person, or if Suno asks for hCaptcha, the command stops
with exit status 4. Then make one song on the website by hand.

After two generations on 2026-11-11, Suno stopped asking this account for the check.

### Request shapes

The Create form has an Advanced tab and a Simple tab. The bodies of `generate` and
`describe` are copies of the bodies that those tabs sent on 2026-11-11. The two are
different. The Simple tab sends one description in `gpt_description_prompt` with
`task: agentic_thinking`, and it has no title field or style field.

Suno changes the style text. In the lyrics test it stored a longer style than the one sent.

### Drift check

`suno doctor --drift` opens the Create page in a headless Chrome. It fills the two tabs with
a fixed test song, presses Create, and aborts each request in the browser. Then it compares
each captured body with the body that this tool builds, one key at a time. Nothing is
submitted and no credits are spent. The Advanced tab saves the typed lyrics as a draft, and
the check deletes that draft. Do this check when a command stops with exit status 5.

## Exit status

| Code | Meaning |
| --- | --- |
| 0 | ok |
| 1 | an error from Suno or from the network |
| 2 | bad input |
| 3 | login necessary, or login rejected |
| 4 | blocked: not confirmed, bot check, no credits or downloads, same request sent before |
| 5 | Suno rejected the shape of the request: the web API changed |
| 6 | a paid request went out and no answer came back |

## Files

| Path | In git | What |
| --- | --- | --- |
| `bin/suno` | yes | Launcher. Starts the package with `uv` (Python 3.12, `cryptography`, `patchright`). |
| `sunocli/session.py` | yes | Browser cookie reader, sign-in token |
| `sunocli/api.py` | yes | The web API client and its error types |
| `sunocli/model.py` | yes | Request bodies, clip records, timed lyrics |
| `sunocli/ledger.py` | yes | Receipts and the spend log |
| `sunocli/captcha.py` | yes | The headless Turnstile step |
| `sunocli/drift.py` | yes | The request-shape check |
| `sunocli/official.py` | yes | OAuth sign-in and the client for the official MCP endpoint |
| `sunocli/cli.py` | yes | Commands |
| `secrets/session.json` | no | The login for the web lane |
| `secrets/oauth.json` | no | The client id and tokens for the official lane |
| `state/` | no | Receipts, spend log, the ids that `list` showed |
| `library/<title>-<id>/` | no | Downloads: audio, `meta.json`, `lyrics.txt`, `lyrics.lrc` |

`SUNO_LIBRARY` sets a different download folder. `suno download --out DIR` sets it for one
command.

## What was examined, and against what

These results are from 2026-11-11. The last column names what gave the answer.

| Claim | Result | Source of the answer |
| --- | --- | --- |
| A generation costs 10 credits | Three generations (instrumental, lyrics with sliders, Simple mode) each decreased the balance by 10 | Suno's balance |
| Suno gets the sliders and the excluded styles | Suno stored them as sent | The clip record on Suno |
| A request id is sent only one time | The second send returned the saved songs and the balance did not change | Suno's balance |
| A download is a full file | The audio of an unlocked song decoded at the length that Suno gives | `ffprobe` |
| An unlocked song costs nothing | The download counter did not change | Suno's counter |
| A locked song is not opened by accident | It gave `not_authorized` and the counter did not change | Suno's counter |
| The request bodies agree with the website | The two bodies were in step with the live form | `doctor --drift` |

Not examined:

- The unlock of a locked song (`POST /download/authorize`). The code is there and its test
  uses a fake server. The first `download --yes` of a locked song is its first live use.
- WAV downloads and M4A downloads.
- The `--persona` and `--max-mode` flags. They set fields that the live form also sends.
- Each call on the official lane after the consent page: the token trade, the tool list and
  a tool call. Their tests use a fake server.

`pytest tests/test_sunocli.py` has the offline tests.

## Risk

Suno's [Terms of Service](https://suno.com/terms) (dated 2026-09-03) tell users not to
"engage in or use any data mining, robots, scraping, or similar data gathering or extraction
methods". A command line on the website's own endpoints is in that area. This tool is for
one person's own account at a human pace. Suno can close an account that it sees as
automated. The official interface is the path that Suno supplies for tools of this type.

The same terms tell users not to "circumvent" the "content protections" on content. They
also connect commercial use of a song to "a permitted download" made "through an approved
channel". For those two reasons this tool does not decode the playback stream, and
`download` uses only the download flow that Suno counts.

## Credits

The first map of the web API came from
[paperfoot/suno-cli](https://github.com/paperfoot/suno-cli), a Rust CLI with an MIT license.
This tool shares no code with it. Its notes showed the sign-in sequence, the download
endpoints and the trash endpoint. Where its notes and the live website gave different
answers, this tool follows the website. That applies to the API host, the Simple mode request
and the `token_provider` field.
