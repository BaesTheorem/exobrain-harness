# tools-registry

Single source of truth for every tool on this machine -- web apps, scheduled jobs/watchers,
and CLI tools -- so the inventory never has to be remembered by hand.

`tools-registry-scan.py` auto-discovers tools from two authoritative on-disk sources:

- **App launchers** -- `~/Desktop/Apps/*.app` (parses `Contents/MacOS/launch` for `DIR` + `PORT`)
- **Scheduled jobs** -- `~/Library/LaunchAgents/{com.exobrain,com.mist,com.nightwatch,com.alexhedtke}*.plist`

For each tool it resolves repo dir, git remote, port, schedule, and live status, then writes
one note per tool into the Obsidian vault's `Tools/` folder. `Tools.base` (vault root) renders
them with views: Apps, Scheduled Jobs, Running Now, By Repo, All. The folder is wiped and
rewritten each run (notes are a disposable projection -- never hand-edit them).

CLI-only tools with no launcher and no launchd job are added by hand via the `SUPPLEMENTAL`
list in the scanner.

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
