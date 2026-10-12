# mcp-lazy

Each Claude Code session starts its own copy of all stdio MCP servers in the
config. On an 8 GB Mac, twelve servers that a chat seldom uses cost
approximately 600 MB for each open chat. `mcp-lazy` replaces each of these
servers in the config with a small Python stub (approximately 10 MB). The actual
server starts only when a session calls one of its tools.

## How it works

- The config entry for a wrapped server runs `mcp-lazy <name>`. The server name
  and the tool names do not change, so skills and `ToolSearch` find the same
  `mcp__<name>__<tool>` tools as before.
- The stub answers `initialize`, `ping` and the list requests (`tools/list`,
  `prompts/list`, `resources/list`) from a cache of the actual server's answers.
- The first request that the cache cannot answer (usually `tools/call`) starts
  the actual server. The stub replays the client's `initialize`, then pipes all
  data in the two directions.
- After 20 minutes with no request, the stub stops the actual server. The next
  call starts it again. Set `"idle": 0` on a server in `servers.local.json` to
  keep it alive for the full session (zulip, linkedin and blender keep state
  between calls).
- Each actual start writes the cache again, so a server update reaches the cache
  at its next start. If no cache exists, the stub starts the server immediately.

## Files

| Path | Content |
| --- | --- |
| `bin/mcp-lazy` | The stub and the commands that follow |
| `servers.local.json` | The initial config entry of each wrapped server, secrets included. Gitignored |
| `~/.cache/mcp-lazy/<name>.json` | The cached `initialize` and list answers |

## Commands

```sh
mcp-lazy/bin/mcp-lazy status             # wrapped servers, cache age, tool count
mcp-lazy/bin/mcp-lazy wrap <name>...     # move stdio servers behind the stub
mcp-lazy/bin/mcp-lazy unwrap <name>...   # put the initial entries back
mcp-lazy/bin/mcp-lazy refresh [name]     # start each server one time, write its cache
```

`wrap` reads `~/.claude.json` (user scope) and this repo's `.mcp.json`
(project scope). It writes user-scope entries through `claude mcp add-json`,
because the open sessions also write `~/.claude.json`. HTTP servers start no
process, thus `wrap` does not change them.

A change to the config applies to new sessions only.

## If `servers.local.json` is missing

The wrapped entries point at a stub with no spec, and
those servers do not start. To repair, put each server back into the config
with `claude mcp add-json` (or into `.mcp.json`), then run `wrap` again.
