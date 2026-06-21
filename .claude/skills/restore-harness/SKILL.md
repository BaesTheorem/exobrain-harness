---
name: restore-harness
description: Restore the Exobrain harness onto a wiped Mac or a brand-new machine, from the daily collective backup tarball + GitHub + cloud re-auth. Use when Alex says "restore the harness", "restore from backup", "set up the harness on this machine", "new Mac setup", "rebuild the machine", "disaster recovery", or is bringing a fresh/wiped Mac back online. NOT for the Mac Mini server split (that is MAC-MINI-MIGRATION-PLAN.md, which assumes the old machine is still alive).
user_invocable: true
metadata:
  requires:
    bins: [git, gh, brew, tar, rsync, launchctl]
---

# Restore Harness From Backup

Rebuild Alex's machine from backups as fast and safely as possible. Companion recon (the full reasoning, gap analysis, and lay-of-the-land) lives at `~/Exobrain/recon/2026-06-20-restore-harness-from-backup.md` — read it if you need the *why* behind any step here.

## The one rule that overrides everything

> [!danger] VAULT GUARDRAIL
> **Do NOT touch the Obsidian vault (`~/Exobrain/`) during a restore unless Alex explicitly opts in.** The vault's real recovery path is **Obsidian Sync** (the paid first-party service — confirmed, not iCloud). The tarball's vault copy is a sealed fallback. Default behavior: wait for Sync, verify it arrived, and leave the vault alone. Only if Sync has failed AND Alex says "restore the vault from backup" do you extract it — and even then, to a *temp* path for manual diff, never a blind overwrite of `~/Exobrain/`.

## Mental model: four sources, not one

A restore reassembles four independent sources. The backup tarball is only one of them.

1. **Code** ← GitHub clone (every repo is private under `BaesTheorem/`).
2. **Private data** (secrets, tokens, SQLite DBs, local state) ← the collective tarball, overlaid *on top of* cloned code.
3. **Vault** ← Obsidian Sync (tarball = fallback only; see guardrail).
4. **Auth + OS state** (cloud MCP sessions, Apple ID / Google / GitHub / Obsidian logins, macOS Full Disk Access) ← re-authorized by hand. In no backup.

The whole task is sequencing these so each is present before the thing that needs it runs.

## Modes

- **`--minimal`** — stop after MIST works interactively (Claude + vault + 3 local MCPs). ~45 min–1.5 hr. Use this first in a real emergency.
- **(default) full** — every repo, app, credential, and launchd job back. 4–8 hr supervised, mostly waiting on syncs/builds.
- **`--vault-from-backup`** — the ONLY way to touch the vault. Requires Alex to have explicitly asked. Extracts the tarball vault to `~/vault-tarball-fallback/` for manual review; never overwrites `~/Exobrain/`.
- **`--dry-run`** — narrate every step and run only read-only checks; make no changes. Good for rehearsal.
- **`--no-watchers`** — finish everything except the Phase 8 launchd bootstrap (leaves automation paused; recommended until the 24h re-processing window is reconciled — see Phase 8 note).

## Before you start: the emergency-credentials card

Confirm Alex has these on hand. None are in any backup; without them the restore stalls:
Apple ID · **Google account** · **GitHub** (for `gh auth login`) · **Obsidian Sync account** (separate from Apple ID — the easy one to forget) · Fitbit & Withings logins (for OAuth re-auth).

## Procedure

Work phase by phase. Announce each phase, run its checks, and stop at any chokepoint that fails rather than barreling ahead. Phases 0–1 are mostly manual macOS/GUI steps — guide Alex through them; you can't script the installer or App Store. From Phase 2 on you drive.

### Phase 0 — Reach the tarball  (CHOKEPOINT)
1. macOS setup; create the user with the **same short username** `alexhedtke` (38 launchd plists hardcode `/Users/alexhedtke/`). If the username differs, note it — you'll `sed` plist bodies in Phase 8.
2. Sign into Apple ID.
3. Install **Google Drive for Desktop**, sign in, set `Exobrain backups/`, `Plaud/`, and `Supernote/Note/` to **Mirror** (not Stream), wait for `Exobrain backups/` to materialize.
4. Find the newest **`exobrain-collective-*`** archive (NOT a legacy `exobrain-harness-*` one, which lacks the vault + per-repo data):
   ```bash
   ls -lt "$HOME/My Drive/Exobrain backups/"
   ```
5. Extract to staging:
   ```bash
   mkdir -p ~/restore-staging
   tar -xzf "$HOME/My Drive/Exobrain backups/exobrain-collective-<ts>.tar.gz" -C ~/restore-staging
   ```
   **Escape hatch:** if Drive won't materialize, download the tarball from drive.google.com in a browser to `~/Downloads/` and extract from there.

### Phase 1 — System foundation
```bash
# Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
# If a Brewfile is committed, prefer it:  brew bundle install --file "$HOME/Documents/Exobrain harness/Brewfile"
brew install python@3.12 node git gh jq git-lfs ffmpeg   # 3.12 REQUIRED for mist-voice
git lfs install
npm install -g @anthropic-ai/claude-code defuddle        # set ~/.npmrc prefix=$HOME/.npm-global if needed
gh auth login                                            # CHOKEPOINT — every repo is private
curl -LsSf https://astral.sh/uv/install.sh | sh          # uv, for things-mcp
```
Install Things 3 (App Store) and Obsidian (obsidian.md, not App Store). Sign into Things Cloud and Obsidian Sync.

### Phase 2 — Vault checkpoint  (GUARDRAIL LIVES HERE)
Wait for Obsidian Sync to settle, then:
```bash
ls "$HOME/Exobrain/Dashboard.md" && ls "$HOME/Exobrain/Daily notes/" | tail -3
```
- **Both present → Sync is healthy → leave the vault alone. Proceed.** (Default. Do not extract the tarball vault.)
- **Missing/empty → STOP. Tell Alex Sync didn't arrive and ask whether to use the backup.** Only on explicit yes (i.e. `--vault-from-backup`): `cp -r ~/restore-staging/Exobrain ~/vault-tarball-fallback` and let Alex diff manually. Never overwrite `~/Exobrain/`.

### Phase 3 — Harness restore
```bash
git clone https://github.com/BaesTheorem/exobrain-harness.git "$HOME/Documents/Exobrain harness"
rsync -a ~/restore-staging/"Exobrain harness"/ "$HOME/Documents/Exobrain harness"/
grep -c WITHINGS "$HOME/Documents/Exobrain harness/.env"     # expect >0
ls "$HOME/Documents/Exobrain harness/.mcp.json"
```
If `gh`/clone is down, extract the harness whole from the tarball instead (its tracked code is in there).

### Phase 4 — Out-of-tree credentials  (the part the backup currently misses)
Place each, then verify. Items marked ⚠ are likely **absent from the backup** (see the recon's gap table) — restore from wherever Alex stored them, or re-auth:
- `~/.claude/` globals (`settings.json` with `bypassPermissions`, `CLAUDE.md`, global `.mcp.json`, `channels/discord/.env` Discord token) ⚠
- `~/.plaud/` (Plaud OAuth token + device IDs) ⚠ — or re-auth later via `mcp__plaud__login`
- `~/Documents/Claude Code/mcp-fitbit-main/` `.env` + `.fitbit-token.json` ⚠ — or re-run Fitbit OAuth
- From `~/restore-staging/repos-gitignored/<repo>/`: phone GCP keys, bus/.env, disposable-email secrets, tv/token.json, etc. (these ARE in the backup — but rsync them in Phase 5 *after* each repo is cloned, not before, or the clone fails on a non-empty dir).
- **Cloud MCPs** (Gmail, Calendar, Drive, MyChart, LinkedIn, Plaud): not restorable from disk — reconnect each at claude.ai → Integrations.

### Phase 5 — Sibling repos
```bash
cd ~/Documents
for r in night-watch pocket-dungeon inbox-clone pixel-claude-code opower annas-archive \
  5e-spell-maker claude-home dnd-character-sheet mist-voice-data mist-console chromatic-set \
  petkit-loki sleep-cycle-pwa claude-phone dating-lab bestagon envelope-budget \
  hp1-sorcerers-stone-macos rental-harmony passage kc-library-nyt-pass; do
  gh repo clone "BaesTheorem/$r" || echo "WARN: $r clone failed"
  [ -d ~/restore-staging/repos-gitignored/$r ] && rsync -a ~/restore-staging/repos-gitignored/$r/ ~/Documents/$r/
done
```
Rebuild venvs **carefully** — do NOT blanket-rebuild:
- `mist-voice`: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements-lock.txt` (3.12 only; needs `brew ffmpeg`).
- `mist-voice-data`: `git lfs pull` — **watch the 1 GB/month LFS quota**; an exhausted quota leaves silent garbage-audio pointer files, not an error.
- Everything else: per-repo `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`; `passage` then needs `playwright install chromium`.

### Phase 6 — TCC / Full Disk Access  (CHOKEPOINT, manual, un-scriptable)
Walk Alex through System Settings → Privacy & Security:
- **Full Disk Access**: the `claude` binary; `python3`/script runner that reads `~/Library/Messages/chat.db`; Obsidian.
- **Accessibility**: cliclick / computer-use bits if used.
- **Automation**: Things 3, Obsidian.
This must precede Phase 8 — otherwise watchers bootstrap "successfully" and silently do nothing.

### Phase 7 — Interactive smoke test  (GATE)
```bash
cd "$HOME/Documents/Exobrain harness" && claude
```
Have MIST read the Dashboard, hit Things 3, pull Fitbit + Withings, list recent Plaud. `/mcp` should show things3 + fitbit + withings connected. Then run the committed script:
```bash
bash "$HOME/Documents/Exobrain harness/restore-smoke-test.sh"
```
Fix anything red before Phase 8.

### Phase 8 — launchd bootstrap  (LAST; skip if `--no-watchers`)
> [!warning] The 24h re-processing trap
> Restored `processing-log.json` is ≤24h stale. When watchers start, the Plaud watcher re-discovers and **re-processes** the last day's transcripts → duplicate journal entries / tasks / People-note appends, silently. Prefer `--no-watchers` until Alex confirms the gap window is reconciled (or manually mark those files done in the log first).

```bash
mkdir -p ~/.claude/channels/discord ~/.claude/channels/maintenance ~/.claude/channels/awair  # plists log here
# Copy each source plist as a REAL FILE (never symlink — TCC blocks symlinked plists at login), then:
#   cp <repo>/<name>.plist ~/Library/LaunchAgents/
#   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<name>.plist
launchctl list | grep -E 'exobrain|mist|nightwatch|passage'   # every job: recent PID, exit 0
```
> [!note] Orphaned plist bodies
> 8 jobs (5× `com.mist.routine.*`, 3× `com.nightwatch.*`, plus `tools-registry` and `mist-hotkey-agent`) have **no plist source committed in any repo** — only their scripts survive. Until the backup fix lands (commit the bodies into `mist-console/launchd/`, `night-watch/launchd/`, `tools-registry/`), you must hand-recreate these plist XML bodies or extract them from a machine that still has them. Flag this to Alex; otherwise these silently never run (weeks to notice: no nightly auto-commit, no evening/weekly review).

## On completion
Report what's live vs. still manual (cloud MCP re-auths, stale-OAuth re-auths for envelope-budget/inbox-clone/nest, any orphaned plists not recreated). Recommend writing a `/session-memory`. Remind Alex the vault was left to Sync unless he opted into `--vault-from-backup`.
