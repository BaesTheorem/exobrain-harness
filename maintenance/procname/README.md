# procname

macOS names a process after its executable file. Homebrew's framework Python
runs every script as `Python`, and uv's interpreters run as `python3.X`. Thus
Activity Monitor and Stats show each Python daemon as one more "Python" row.

`procname.c` is a small binary that loads libpython in-process and starts the
interpreter. You put a copy of the binary, named for the daemon, where the
plist or MCP config had the interpreter. The process then shows under that
name. The shim sets `config.executable` to the original interpreter. Thus
`sys.executable`, `sys.prefix` and `sys.path` are the same as before, and venv
detection works the same.

## Use

```sh
bin/procname make trawl ~/Documents/trawl/.venv/bin/python   # prints the shim path
bin/procname list
bin/procname verify     # each shim against its interpreter, exit 1 on drift
bin/procname rebuild    # all shims, then verify
```

The shims are in `~/.local/libexec/procname/`, with `manifest.json` (name and
target). Thus a venv rebuild does not remove them. A name has a maximum of 15
characters (MAXCOMLEN).

## Failure modes

- If libpython is missing (a minor Python upgrade removed it), the shim execs
  the original interpreter. The daemon starts, but under the old name.
  `maintenance/post-brew-heal.sh` runs `procname verify` after each Homebrew
  change and rebuilds the shims when they drift.
- A stub such as `/usr/bin/python3` (xcrun) execs the real interpreter. `make`
  thus uses the interpreter's own `sys.executable` as the target.
- A rebuilt shim applies at the next start of the daemon.

## Users

- The always-on launchd daemons (trawl, priory-web, mist-studio, zulip-listener,
  xv-server, pennylane, pennylane-pulse, duel-brain, turn-to, ff-dash,
  overland-recv, eject-assist, mem-watchdog, traces-review).
- `mcp-lazy`: each wrapped stub runs as `mcp-<server>` (`mcp-lazy rename`).
- The `things3` MCP entry runs as `things-mcp`.
