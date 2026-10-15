# traces

Two tools for the raw record of each Claude Code session on this Mac:

1. **The archive** (`trace_archive.py`). It keeps a compressed copy of each
   transcript. Claude Code deletes a transcript after `cleanupPeriodDays`
   (60 here), and the harness backup skips `~/.claude/projects`. Thus, after
   Claude Code deletes a session, the archive has the only copy of its
   transcript file. (The MIST Console keeps a different record of its own chats.)
2. **The trace table** (`trace_db.py`, `trace_parse.py`). It loads the archive
   into one DuckDB file. Then you can count sessions, tokens, tool errors and
   prompts with SQL, and compare a time window with a baseline.

The session memories and MEMORY.md are summaries that MIST writes about MIST.
This directory keeps the source data of those summaries. With this data, you
can measure a change to the harness against the record.

## Commands

`bin/traces` uses `traces/.venv` for all commands.

| Command | Result |
| --- | --- |
| `bin/traces archive [--progress]` | Copies new and changed transcripts into `data/archive/` |
| `bin/traces build [--full] [--progress]` | Loads changed archive files into `data/traces.duckdb` |
| `bin/traces baseline --end 2026-10-15 --days 30 [--save] [--json]` | Shows the metrics for one window |
| `bin/traces sql "SELECT ..."` | Shows the result of a read-only query |
| `bin/traces nightly` | Does the archive step, then the load step (the launchd agent uses this) |
| `bin/traces sample --name sample-2 [--end DATE] [--days N]` | Makes a fixed labeling sample (see Labeling) |
| `bin/traces review [--sample sample-1]` | Starts the labeling page on `http://127.0.0.1:5019` |

Example query, the ten tools with the most errors in the last 7 days:

```sh
bin/traces sql "SELECT tool, count(*) n, count(*) FILTER (is_error) errors
                FROM tool_calls WHERE ts > now() - INTERVAL 7 DAY
                GROUP BY ALL ORDER BY errors DESC LIMIT 10"
```

## Files

| Path | Contents | In git |
| --- | --- | --- |
| `trace_archive.py` | The archive tool | yes |
| `trace_parse.py` | One transcript to flat rows (pure, no I/O) | yes |
| `trace_db.py` | DuckDB schema, incremental load, window metrics | yes |
| `traces.py` | Command-line interface | yes |
| `trace_review.py` | Labeling sample, readable trace for one session, label file | yes |
| `trace_server.py` | Local server for the labeling page | yes |
| `review/` | The labeling page (Beer CSS, no build step) | yes |
| `com.exobrain.traces.plist` | launchd agent, each night at 01:30 | yes |
| `com.exobrain.traces-review.plist` | launchd agent for the labeling page, loaded only while you label | yes |
| `data/archive/` | `<project>/<session>.jsonl.zst` and the other session files | **no** |
| `data/archive-runs.jsonl` | One line each time the archive tool operates (counts, errors) | **no** |
| `data/traces.duckdb` | The trace table, which the load step can make again from the archive | **no** |
| `data/build-runs.jsonl` | One line for each nightly operation | **no** |
| `data/baselines/` | Metric snapshots from `--save`, `<end date>-<days>d.json` | **no** |
| `data/labels/` | Labeling samples, `labels.jsonl`, and the page token (`.review-token`, mode 0600) | **no** |

`data/` is gitignored. It holds the full text of all sessions, which includes
private data and text from other persons. Do not commit it. Do not put prompt
text from it into a public file.

## Install on a new machine

1. Make the venv. The archive tool needs Python 3.14 or higher for `compression.zstd`:

   ```sh
   uv python install 3.14
   uv venv traces/.venv --python 3.14
   uv pip install --python traces/.venv/bin/python duckdb
   ```

2. Copy `traces/data/archive/` from the harness backup. You cannot make the
   archive again from `~/.claude/projects`, because Claude Code deleted the
   older sessions there.
3. Start `bin/traces archive --progress`. Then start `bin/traces build --full --progress`.
4. Copy `com.exobrain.traces.plist` into `~/Library/LaunchAgents/`. Use a copy,
   not a symlink.
5. Start `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.traces.plist`.

To read one archived transcript, use `zstd -dc <file>.jsonl.zst`.

## How the archive works

- The archive tool copies each file in `~/.claude/projects` to the same relative
  path plus `.zst` (zstd level 9). It does not follow symlinked dirs. Thus the
  `memory/` dirs that link to the one MIST memory store do not make copies.
- An archive file gets the mtime of its source. If the source mtime changes,
  the archive tool makes the copy again the next time it operates. The tool
  reads each new copy back and compares its hash before the new copy replaces
  the previous copy.
- The archive tool does not delete files. In the run log, `rescued` counts the
  archive files that have no source file now.
- First operation, 2026-10-15: 6,165 files, 4.9 GB in, 1.76 GB out, 85 seconds.
  A second operation 8 minutes later copied 252 changed files (752 MB) in 9 seconds.

## Tables

Each row has `file_id`, the archive path without `.zst`. When an archive file
changes, the load step replaces all the rows of that file in one transaction.

| Table | One row for each | Primary columns |
| --- | --- | --- |
| `sessions` | transcript file (primary session or subagent) | `kind` (`multi_turn`, `single_turn`, `subagent`), `first_ts`, `entrypoint`, `models`, `first_context_tokens`, token sums, counts, `cost_usd` (from the cost lines of Claude Code), `first_prompt` |
| `api_calls` | API response, with duplicates in the file removed | `ts`, `model`, `effort`, `skill`, token fields |
| `tool_calls` | tool use, joined to its result | `tool`, `skill`, `input` (first 400 characters), `is_error`, `latency_s` |
| `prompts` | user text message | `category`, `intent`, `text` (up to 100,000 characters) |
| `events` | system line | `subtype` (`api_error`, `compact_boundary`, `turn_duration`, and other), `detail` |
| `files` | loaded archive file | `archive_mtime_ns`, `ingested_at` |

`prompts.category` is one of `human`, `interrupt`, `task_notification`,
`slash_command`, `local_command`, `system_injected`, `meta`, `compact_summary`
and `agent_prompt`. For `human` prompts, `intent` is `status_poll`,
`approval`, `resume` or empty. These are simple pattern matches that show a
trend at low cost. They are not labels. A label comes from a person who reads
the trace.

## Metrics (version 1)

`baseline` uses the window [end - days, end). The window starts and stops at
local midnight. A session is in the window if its first timestamp is in the
window. All other rows use their own timestamp. A row that occurs in more than
one file counts one time: API calls by `(message_id, request_id)`, tool calls
by `tool_use_id`, prompts by `uuid`.

- **Main sessions**: transcripts that are not subagents. `multi_turn` means two
  or more human prompts.
- **First-turn context**: input tokens plus cache tokens on the first API call
  of a primary session. This is the fixed cost of a session before it does work.
- **Cache-read, cache-write and output tokens**: sums for all API calls. Each
  usage field is the highest value in the lines of one response, because the
  first lines can show a count that is not complete.
- **Tool errors**: tool results that have `is_error`.
- **Status polls, approvals, resumes**: `intent` counts, also for each 100 human prompts.
- **Interrupts**: user interrupts, also for each 100 human prompts.
- **Compactions, API errors**: `events` rows. One API error line is one retry.

If you change a definition, increase `METRICS_VERSION` in `trace_db.py` and
write a new baseline with `--save`. Compare a window only with a baseline that
has the same version.

## Labeling

A person reads traces from actual sessions and labels them. That is the first step of error
analysis: the labels show which failures occur and how frequently.

1. `bin/traces sample --name <name>` makes a sample from the 30 days before the
   end date: 50 chats (two or more human prompts), 40 tasks (single-turn
   sessions) and 10 session-memory-writer sessions. The sample uses a fixed seed
   (the end date). The tool does not change a sample file after it makes it.
2. Start the launchd agent `com.exobrain.traces-review`, or start
   `bin/traces review`. The page address is `http://127.0.0.1:5019/#t=` followed
   by the token in `data/labels/.review-token`. The server also writes the
   address to `~/Library/Logs/exobrain/traces-review.log` each time it starts.
3. For each session, select Pass, Fail or Skip, and write the first thing that
   went wrong. The keys are on the page.
4. Each save adds one line to `data/labels/labels.jsonl` (time, sample, file,
   verdict, note). The newest line for a session wins. You can stop and continue
   when you want.
5. When you finish labeling, start
   `launchctl bootout gui/$(id -u)/com.exobrain.traces-review`.

Protection on the page:

- The server accepts connections only from 127.0.0.1. Each data request must
  have the token and a Host of 127.0.0.1 or localhost. Thus other web pages in
  the browser cannot read traces or write labels.
- The server shows only the sessions in the sample, and serves static files
  only from fixed name lists.
- The page puts all transcript text into the page as text, not HTML. The CSP
  allows scripts only from the server, as a second barrier.

## Health

The session-start hook reads the newest line of `data/archive-runs.jsonl`. It
shows a WARN line if the archive tool did not operate in the last 36 hours or
had errors. If the nightly operation fails, `traces nightly` sends a banner and
a Discord DM through `mist-notify`. The agent writes its output to
`~/Library/Logs/exobrain/traces.log`.

## Tests

`tests/test_trace_archive.py` (copies the same as the source, a changed source gets a new copy,
a deleted source keeps its copy), `tests/test_trace_parse.py`, and
`tests/test_trace_review.py` (trace turns, labels, and the access rules of the server).
