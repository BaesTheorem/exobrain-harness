# RESTORE -- bringing the harness back on a wiped or new Mac

This is the **bootstrap**. It's readable on github.com from a bare machine, before Claude Code or the harness exist. Follow Phases 0-1 by hand to get the machine to the point where Claude can run; then hand off to the **`/restore-harness`** skill, which drives the rest with full per-step detail and the vault guardrail.

Full reasoning, the gap analysis, and the lay-of-the-land: the recon note `recon/2026-06-20-restore-harness-from-backup.md` in the Obsidian vault (recoverable via Obsidian Sync). For the always-on Mac Mini *split* (old machine still alive), use `MAC-MINI-MIGRATION-PLAN.md` instead -- different problem.

## The one rule

**Do not touch the Obsidian vault (`~/Exobrain/`) during a restore unless Alex explicitly says to.** Obsidian Sync recovers the vault. The backup's vault copy is a fallback you only open if Sync fails.

## Four sources

Code ← GitHub · Private data/secrets/DBs ← backup tarball · Vault ← Obsidian Sync · Auth + macOS Full Disk Access ← re-authorized by hand (in no backup). The job is sequencing them.

## Credentials you must have on hand (none are in any backup)

Apple ID · Google account · GitHub · **Obsidian Sync account** (separate from Apple ID -- easy to forget) · Fitbit & Withings logins.

## Phase 0 -- Reach the tarball

1. Run macOS setup. **Use the same short username `alexhedtke`** -- 38 launchd plists hardcode `/Users/alexhedtke/`.
2. Sign into Apple ID.
3. Install **Google Drive for Desktop**, sign in, set `Exobrain backups/`, `Plaud/`, `Supernote/Note/` to **Mirror** (not Stream). Wait for `Exobrain backups/` to appear on disk.
4. Pick the newest **`exobrain-collective-*.tar.gz`** (not a legacy `exobrain-harness-*`, which lacks the vault + per-repo data) and extract:
   ```bash
   ls -lt "$HOME/My Drive/Exobrain backups/"
   mkdir -p ~/restore-staging
   tar -xzf "$HOME/My Drive/Exobrain backups/exobrain-collective-<ts>.tar.gz" -C ~/restore-staging
   ```
   If Drive won't materialize: download the tarball from drive.google.com in a browser instead.

## Phase 1 -- System foundation

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python@3.12 node git gh jq git-lfs ffmpeg   # python@3.12 REQUIRED for mist-voice
git lfs install
npm install -g @anthropic-ai/claude-code defuddle
gh auth login                                            # most sibling repos are private (the harness repo itself is public)
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/BaesTheorem/exobrain-harness.git "$HOME/Documents/Exobrain harness"
```
Install Things 3 (App Store) and Obsidian (obsidian.md). Sign into Things Cloud and **Obsidian Sync**.

## Hand off to Claude

```bash
cd "$HOME/Documents/Exobrain harness"
rsync -a ~/restore-staging/"Exobrain harness"/ .   # restores .env, .mcp.json, etc. onto the clone
claude
```
Then in the session:
```
/restore-harness            # full restore (vault left to Sync)
/restore-harness --minimal  # just get MIST working interactively, finish the rest later
```
The skill handles Phases 2-8: vault checkpoint (guardrail), out-of-tree credentials, sibling repos, TCC grants, smoke test, and launchd. Verify any time with:
```bash
bash restore-smoke-test.sh
```
