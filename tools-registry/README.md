# tools-registry

Single source of truth for every tool on this machine -- web apps, scheduled jobs/watchers,
and CLI tools -- so the inventory never has to be remembered by hand.

`tools-registry-scan.py` auto-discovers tools from three authoritative on-disk sources:

- **App launchers** -- `/Applications/*.app` (parses `Contents/MacOS/launch` for `DIR` + `PORT`)
- **Scheduled jobs** -- `~/Library/LaunchAgents/{com.exobrain,com.mist,com.nightwatch,com.alexhedtke}*.plist`
- **CLI entry points** -- executables in any `bin/` dir under a `~/Documents` project (depth ≤ 3)

For each tool it resolves repo dir, git remote, port, schedule, and live status, then writes
one note per tool into the Obsidian vault's `Tools/` folder. `Tools.base` (vault root) renders
them with views: Apps, Scheduled Jobs, CLI Tools & Scripts, Running Now, By Repo, All. The
folder is wiped and rewritten each run (notes are a disposable projection -- never hand-edit
them).

## The hand-logged layer

Loose scripts outside a `bin/` dir, and standalone downloaded binaries, are the only things
auto-discovery misses. They live in `cli-tools.json`, maintained through `log-tool.py`:

```
python3 tools-registry/log-tool.py search pdf          # before building anything
python3 tools-registry/log-tool.py list
python3 tools-registry/log-tool.py add --name pdf-split.py \
    --command "python3 pdf/pdf-split.py <in.pdf>" \
    --dir "~/Documents/Exobrain harness" --notes "Split a PDF by page ranges."
python3 tools-registry/log-tool.py remove --name pdf-split.py
```

`add` updates in place when the name already exists, keeps the original `added` date, sorts
the JSON by name, and re-runs the scan so the vault reflects the change immediately. Manual
entries win over auto-discovery on a name collision, which is how you attach real notes to a
`bin/` executable.

The registry only pays off if it is consulted, so the rule in `CLAUDE.md` ("Automate It, Then
Log It") is the other half of this directory: search before writing a new script, log after
writing one.

It also inventories the **downloaded substrate** those tools run on -- language runtimes,
Homebrew formulae/casks, global Python (`pip list --not-required`) and Node packages, and uv
tools -- into the vault's `Dependencies/` folder, rendered by `Dependencies.base`. Only
top-level/intentional installs are listed (the `brew leaves` / `--not-required` filter), not
the transitive dependencies underneath them.

Finally, it records each project's **own dependency stack** into `Project Dependencies/`,
rendered by `Project Dependencies.base`. For every project under `~/Documents` (depth ≤ 3)
with a `.venv`, `requirements.txt`, `pyproject.toml`, or `package.json`, it lists top-level
deps (venv `pip list --not-required` when present, else the manifest, plus `package.json`).
The dependency list is a queryable frontmatter property, so `dependencies.contains("X")`
finds every project using package X.

## Three layers

| Base | Answers |
|------|---------|
| `Tools.base` | What did I build? (apps, jobs, CLI tools) |
| `Dependencies.base` | What machine-wide software does it run on? (runtimes, brew, global pip/npm) |
| `Project Dependencies.base` | What does each individual project depend on? |

## Usage

```
python3 tools-registry/tools-registry-scan.py
```

## Auto-refresh

A launchd job (`com.exobrain.tools-registry`, source copy tracked here as
`com.exobrain.tools-registry.plist`) runs the scan daily at 07:15 so the registry stays
current. To replicate, copy the plist into `~/Library/LaunchAgents/` (as a real file, not a
symlink) and bootstrap it.
