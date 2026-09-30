# security: prompt injection controls

Everything in this harness that reads text from someone other than Alex and
hands it to a model is an injection surface. The model's judgment is the first
line and, on Fable, a strong one. This directory is the second line: the parts
that hold even when the model has been talked into something, or when the
model on the surface is a cheaper one.

Audit of 2026-09-21. The findings and the reasoning behind each control are in
the vault (`Areas/Exobrain/Audits/2026-09-21-injection-audit.md`); this file
is the durable map.

## The trust model

- **Alex's channels** are the MIST Console, a terminal session, his own
  Discord account (username-gated), and this repo. Nothing else is him. A
  name in a chat, a display name, an email signature, a line in a fetched
  page, "urgent message from Alex" inside data: not him.
- **Everything else is data.** Chat messages, emails, other people's speech in
  a transcript, web pages, job descriptions, forum posts, GitHub issues and
  repo files, calendar invites, iMessage history, AirDropped images, and every
  note MIST wrote from any of those. A model quotes it, summarizes it, acts on
  the facts it reports where the routine allows, and never on an instruction
  inside it. Rules change in this repo, never through a message.
- **Unattended sessions get less than attended ones.** A session nobody is
  watching may not change what MIST is, may not read secrets, and may not set
  up anything that outlives it. The guard hook enforces that with regexes, not
  judgment.

## Controls

| Control | Where | What it holds |
|---|---|---|
| Framing library | `untrusted_frame.py`, `bin/mist-frame` | Third-party text goes into `<<<UNTRUSTED source=... nonce=...>>>` blocks with a per-call nonce; a forged closing marker inside the text is neutralized in place, invisible characters are stripped, labels (team names, display names) are sanitized. One `PREAMBLE`, used by every surface. |
| Injection scanner | `scan_injection.py`, `bin/mist-injection-scan` (runs on Apple's `/usr/bin/python3`; see Commit paths) | Named regex signatures for the canonical attempts (override, fake role tags, impersonation, secrecy, exfiltration, pipe-to-shell, prompt leak, guard tampering, hidden HTML, bidi and zero-width tricks, encoded blobs). A tripwire, not a wall. `--exclude instructions` drops the phrases a rule file legitimately quotes. |
| Guard hook | `.claude/hooks/guard-unattended.py` (PreToolUse on Bash, Write, Edit, MultiEdit, NotebookEdit, Read) | When `MIST_UNATTENDED=1`: denies writes to CLAUDE.md, `.claude/`, scheduled tasks, memory, MCP configs, plists, `.env`, shell rc files, PATH dirs, the Console, and source code in this repo; denies reads of secret files; denies persistence and exfiltration shell shapes. Logs to `~/Library/Logs/exobrain/guard-unattended.log`, one banner per session. Inert otherwise. `MIST_GUARD=off` disables it for debugging. |
| Startup framing and scan | `.claude/hooks/session-start.sh` | The digests, session memories and vault snapshot loaded into every session are labelled as notes, not rules, and each passes through the scanner; a hit is annotated above the content, never hidden. |
| Nightly commit tripwire | `auto-commit-harness.sh` | Added lines of CLAUDE.md, `.claude/`, shell runners and `security/` are scanned before the public push; a hit skips the commit and raises a banner. |
| Routine commit gate | `bin/harness-commit` | The commit path for unattended routines: filename privacy audit, then every staged added file and every added line scanned; a hit refuses with exit 3 and a banner, a scanner that cannot run refuses with exit 4. See Commit paths. |
| Headless prompt backstop | every headless `claude -p` runner | `--permission-prompts none`: anything that would prompt is denied instead of waiting on a host that is not there. Under `--dangerously-skip-permissions` little prompts, so this is a backstop under the guard, not a replacement for it. |
| iCloud pull gate | `bin/cowork-sync` | An iCloud (Claude Cowork) edit to CLAUDE.md is scanned before it is installed as the rule file; a hit refuses it once per content hash; every applied pull raises a banner. `--pull` is Alex accepting it and skips the scan. |
| Notification click targets | `mist-voice/bin/mist-notify` | The 4th argument (the source link, an "Open link" button unless `--direct`) and every non-`cmd:` action target must be the Console, a web URL, a navigating Obsidian or Things link, a folder, an app bundle, or a plain file. Anything else is dropped and noted in the history line; the click itself is always a Console chat. `cmd:` targets are caller-authored and must never be built from third-party text. |
| Sandboxes | `claude-bot` guests, Jackbox judges | `--tools ""`, `--strict-mcp-config` with an empty server list, `--setting-sources ""` (no CLAUDE.md, hooks, memory or settings), `--no-session-persistence`, neutral cwd. Verified: the session does not know the word MIST unless the system prompt says it. |
| Model pins | `chat-watch`, the Zulip listener, Discord guests, the voice line, kcurbex geocoding, the fantasy routines | Third-party-facing surfaces run Fable first, Opus only on a spent budget. |
| Voice-line gate | `phone/server.py` | Read allowlist (`is_read_only`), not a mutating-verb denylist. Everything not on the list needs the PIN. |
| MCP pins | `.mcp.json`, `~/.claude.json` | The Plaud and Withings servers are pinned to a version and a commit. Server `instructions` land in every session's system prompt, so an upstream release is an instruction channel. |

## Surface inventory

Every place a model reads third-party text, with what runs it and what holds it.

| Surface | Third-party text | Runs as | Model | Controls beyond the rules |
|---|---|---|---|---|
| ESPN Fantasy Chat (`fantasy/bin/chat-watch`) | leaguemates' messages, team and owner names | headless, harness cwd, bypass | Fable, Opus fallback | framed, labels sanitized, DMs and trade partners escalated to Alex instead of answered, daily cap, guard |
| Zulip "The Claudes" (`zulip/`) | friends and their Claudes | headless per topic, harness cwd, permissions skipped | Fable, Opus fallback | policy prompt with receipts and a write policy, rate limits, guard |
| Discord bot, guests (`claude-bot`) | anyone who @mentions or DMs her | headless, `/tmp` | Fable (guest model), current model on spent credits | full sandbox (no tools, no MCP, no settings), throttle, single flight, names cannot render as Alex |
| Discord bot, Alex (`claude-bot`) | history of the channel he wrote in | headless, harness cwd, bypass | his choice | non-owner lines marked `(guest)`, guard |
| Voice line (`phone/`) | whoever is on the call (caller ID is spoofable) | Agent SDK, harness | Fable | PIN before any non-read tool, unknown callers PIN even to read, guard |
| Scheduled routines (morning, afternoon email scan, winddown, weekly review, local events, fantasy) | email, iMessage, Discord digest, calendar invites, the web | headless via `mist-console/run-routine.sh`, harness cwd, permissions skipped, `--permission-prompts none`, 45 min budget | per routine | guard, preflight, startup framing of what they read back |
| Plaud transcripts and Supernote | other people's speech, handwriting | headless, harness cwd, permissions skipped, `--permission-prompts none` | default | guard |
| Job scan (`job-search/run-job-scan.sh`) | job descriptions, alert emails, ATS pages | headless, harness cwd, permissions skipped | default | guard, `hidden_html` signature covers white-text screener bait in archived JDs |
| Session memory consolidator | every tool result of the day, via the transcripts | headless, harness cwd, permissions skipped, `--permission-prompts none` | default | prompt frames transcripts as data, output scanned (a scanner failure is logged, never fatal), guard |
| Watchers that drive `claude --print` (`watchers/dhs-ia-teleconference`, `watchers/us-china-ai-talks`) | invite emails, government readouts | headless, harness cwd, permissions skipped | default | preamble prepended, guard |
| kcurbex geocoding | forum posts | headless, kcurbex cwd | Fable, Opus fallback | preamble, tools limited to Read/Write/Glob/Grep/WebFetch/WebSearch, no MCP, guard |
| Jackbox (`.claude/skills/jackbox`) | other players' answers and prompts | headless, `/tmp` | Opus low, Sonnet vision | full sandbox |
| GitHub contributions (`.claude/skills/github`) | issues, comments, repo files, review replies | interactive, standing authorization | Fable, Opus fallback | skill rule: repo and issue text is data; honeypot audit; no untrusted execution |
| AirDrop to Console (`airdrop-to-console`) | images from anyone in range while discoverability is Everyone | interactive Console chat | chat's model | caption marks the sender unverified and the image as data |
| Startup context (`session-start.sh`) | digests and memories written from all of the above | every session | every model | framed as notes, scanned, annotated |
| Web research subagents (`news-briefing`, `deep-research`) | web pages | Agent tool subagents | Sonnet, Haiku | orchestrator writes the output; subagents return summaries. Inherit the guard when the parent is unattended. |

Not model surfaces, but adjacent: `discord/discord-digest-fetch.py`,
`imessage/imessage-sync.py`, the `kcurbex` vault writer and the watchers
without a model call store third-party text deterministically; the surfaces
above read it later.

## Adding an unattended surface

1. Export `MIST_UNATTENDED=1` in the runner before it starts `claude` (or pass
   it in the subprocess env, the SDK `env`, or the launchd plist's
   `EnvironmentVariables`), and add the runner to `UNATTENDED_RUNNERS` in
   `tests/test_injection_controls.py`. The test fails if the flag is missing.
2. Pin the model. Third-party-facing means Fable first, Opus behind it.
3. If the script assembles the prompt from third-party text, put that text
   through `bin/mist-frame --source <where>` and put `bin/mist-frame
   --preamble` once at the top. If the model fetches the text itself (MCP,
   WebFetch), the preamble alone covers it.
4. Sanitize any label that a third party chooses (team names, display names,
   subjects) before it goes into a prompt line: one line, bounded length.
5. Pass `--permission-prompts none` on the `claude -p` line, so a prompt is
   denied rather than left waiting on a host that is not there.
6. Only give the session the tools it needs. `--tools` for built-ins,
   `--strict-mcp-config --mcp-config '{"mcpServers":{}}'` when it needs no MCP,
   `--setting-sources ""` when it needs none of Alex's context at all.
7. Never build a `mist-notify` `cmd:` action, an `open` argument, a URL scheme,
   or a file path from third-party text. The 4th argument is validated;
   `cmd:` is not, on purpose.
8. If the surface writes files that a later session reads, either the writer
   or the reader passes them through `bin/mist-injection-scan`.
9. If the surface commits to this repo, it goes through `bin/harness-commit`.
10. Add the row to the inventory above.

## Commit paths

This repo is public, so anything that commits from an unattended context is
a publishing channel.

- **`bin/harness-commit "message"`** is the only sanctioned commit path for
  unattended routines (the evening wind-down calls it). It gitignores files
  that match the privacy filename patterns, stages everything, scans every
  added file whole and every modified file's added lines, and only then
  commits and pushes to `main`. Rule files and READMEs are scanned with
  `--exclude instructions`. Exit 3 is a scanner hit, exit 4 a scanner that
  could not run (fail closed); both leave the changes staged and raise a
  banner. `--dry-run` does all of it against a throwaway index. Runs are
  logged to `~/Library/Logs/exobrain/harness-commit.log`.
- **`auto-commit-harness.sh`** (launchd, 23:30) is the nightly sweep for what
  interactive sessions left uncommitted. It scans the added lines of the
  instruction files only.

A routine that runs `git commit` or `git push` itself bypasses both.

**Scanner interpreter.** `bin/mist-injection-scan` runs the scanner on
Apple's `/usr/bin/python3`. Under launchd, a non-Apple interpreter exec'd
from a bash script is refused read access to `~/Documents` by TCC: `env
python3` resolved to Homebrew python in any job with Homebrew on its PATH, and
the harness `.venv` python fails the same way on `pyvenv.cfg`. Both were
confirmed with `launchctl submit` on 2026-09-28. From 2026-09-21 to
2026-09-28 this made the session-memory consolidator exit 1 every night at the
scan with no log line (`set -e`, stderr discarded), and the scan also used the
wrong `-newer` reference. The consolidator now marks a timestamp before claude
runs, scans the files newer than it, logs `injection scan failed rc=N` to the
run log and its failure log when the scanner itself fails, and still banners
on a real hit. Callers treat exit 1 with empty output as a scanner crash, not
a hit.

## Dead-man's switch

`scripts/run-heartbeat-check.sh` (launchd `com.exobrain.heartbeat-check`,
10:15 daily) checks outputs rather than exit codes: today's morning briefing
section, yesterday's evening wind-down section, yesterday's session-memory
digest, the newest job-scan output, the backup log. One banner per day lists
whatever is missing. It replaces the April `heartbeat-check` Claude Desktop
task, which watched only the briefing, pointed at the pre-move vault path, and
had no runner after the routines moved to launchd. Watched set is the CHECKS
block in the script. `bin/alarm-triage` reads the guard log and the
notification history back so the noise rate of these alarms can be judged.

## Testing

`pytest tests/test_injection_controls.py` covers the framer (a forged closing
marker stays inside the block), the scanner (every canonical attempt fires, an
ordinary session memory does not, the instruction-file excludes work), the
guard (the denied and the allowed lists, fail-open on garbage, the off switch),
and the runner coverage list.

The live positive control for the guard costs one model call and has no side
effects:

```sh
MIST_UNATTENDED=1 claude -p "Use the Bash tool to run exactly: echo __MIST_GUARD_CANARY__ . Reply with the output or DENIED." \
  --dangerously-skip-permissions --model claude-haiku-4-5-20251001 --no-session-persistence \
  --strict-mcp-config --mcp-config '{"mcpServers":{}}'
```

Expect `DENIED`; drop the variable and expect the canary echoed. Run it from
the harness directory, since that is where the project hooks load from.

## What this does not cover

- An attended Console chat runs in bypassPermissions by Alex's choice, and the
  guard is inert there. The defense in an attended chat is Fable plus the
  rules, plus Alex being present.
- The Zulip and Discord-private sessions are the full MIST with all MCP
  servers, by Alex's choice (2026-09-10 and 2026-09-18). The guard limits what
  they can persist, not what they can read or send through MCP.
- `--fallback-model` is documented for overload and unavailability; whether it
  also covers a spent credit balance is unverified. `chat-watch` and
  `run-routine.sh` implement the credits fallback themselves for that reason.
- A compromised local process is out of scope: the Console's local HTTP API
  is loopback-only and unauthenticated, as is every local app here.
- MCP server `instructions` from the claude.ai connectors and from Anthropic's
  own skill sync (`.claude/skills/synced/`) arrive from the cloud with the
  account. Pinning covers the two local third-party packages only.
