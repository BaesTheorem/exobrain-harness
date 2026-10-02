# expert-panel

An isolated panel of expert agents that researches a question through a shared message board.

Each panelist is a different headless `claude -p` process. A panelist loads none of the settings, CLAUDE.md files, hooks, memory or MCP servers of this machine. Its system prompt is built from a template, its persona and the brief for the run, its working directory is in `/tmp`, and its only tools are `WebSearch`, `WebFetch` and the board server. The panel works in rounds. You are the client liaison: the panel asks questions on the board, and you answer them from the command line.

## Files

| File | Purpose |
|---|---|
| `panel.py` | The orchestrator and the liaison CLI. |
| `board_server.py` | A stdio MCP server, one copy for each panelist. No dependencies. |
| `board.py` | Board storage: an append-only JSONL file with a lock. |
| `system-prompt.md` | The system prompt template for all panelists. |
| `example/` | Six panelists (four analysts, two advisors), a chair, eight rounds, and a brief template. |
| `bin/expert-panel` | Wrapper for `panel.py`. |
| `runs/` | One directory for each run. Gitignored, because a run contains the answers of the liaison about a person. |

## Start a run

1. Make a run directory, `runs/<name>`, and copy `example/panel.json` into it.
2. Write `runs/<name>/brief.md` from `example/brief.md`. Give the panel only the data that it must have at the start.
3. Examine the sandbox with `bin/expert-panel check runs/<name>`. The verdict must be PASS. For a positive control, add `--control`: that session loads your settings, and its verdict must be FAIL.
4. Start the run: `nohup caffeinate -i bin/expert-panel run runs/<name> > runs/<name>/orchestrator.log 2>&1 &`
5. Monitor the run with `bin/expert-panel watch runs/<name>`. Each line is a question, a round change, a wait for answers or an error.
6. Answer each question with `bin/expert-panel answer runs/<name> <id> "text"`. To read the text from stdin, use `-` as the text.
7. When the run is complete, make the markdown with `bin/expert-panel render runs/<name> <out-dir>`. The result is the full board, the notebooks of the panelists, and the research trail (each search and fetch).

`pending` shows the unanswered questions. `say` sends a note to all panelists. `status` shows the round and the cost.

## The board

Each post has a number, a round, an author, a type, a title and a body. The board tools of a panelist are `read_board`, `post`, `ask_client`, `submit_scores`, `score_table`, `notebook_read` and `notebook_write`. A notebook is private to its panelist and stays between rounds. Each round starts a new session, thus the board and the notebook are the only memory of a panelist.

A round can be gated. In a gated round, a panelist sees only the liaison Q&A and its own posts, thus the first ideas of the panelists do not influence each other.

## How the panel is isolated

- `--setting-sources ""` keeps out CLAUDE.md, hooks, memory and settings. `--strict-mcp-config` keeps out all MCP servers other than the board.
- `--tools "WebSearch,WebFetch"` with `--permission-mode dontAsk` and `--permission-prompts none`. A panelist has no shell and no file tools.
- The environment of a panelist has no `CLAUDE*` or `MIST_*` variables, other than `MIST_UNATTENDED=1`.
- `check` tests the sandbox with one model call. It records the tool list and the MCP servers, and it asks the session if its context mentions this machine.

## Resume and failure

`run` records in `state.json` each panelist that completes a round. If a run stops, start `run` again: it skips the completed rounds and reruns only the panelists that did not complete the interrupted round. A failed panelist gets one more attempt, but not when the account is at its usage limit. If no panelist in a round completes, the run stops with `FATAL`, and you can resume it later.

## Cost

Each panelist round is a full session with web research on the configured model. `status` shows the API-equivalent cost, and `render` records it. On a subscription, the same use counts against the usage limit.
