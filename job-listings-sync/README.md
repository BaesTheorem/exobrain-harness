# job-listings-sync

Keeps the YAML frontmatter on job-listing notes internally consistent, so the
`/job-search` application tracker and any Obsidian Bases/queries over the
listings stay accurate without manual bookkeeping.

## What it does

`reconcile.py` scans every `*.md` note with `type: job-listing` in the vault's
job-listings folder and applies two idempotent rules:

1. **`applied: true` + `status: candidate`** -> set `status: applied`, and stamp
   `application_date: <today>` if it's empty. This is the "Alex just flipped the
   applied checkbox" case.
2. **`status: rejected` + no `rejection_date`** -> stamp `rejection_date: <today>`
   (captures rejection-email confirmations).

It deliberately does **not** backfill `application_date` for notes already in
`{applied, rejected, withdrawn, closed, interviewing, offer}` — those either
have a real historical date or carried an unknown date through migration that
shouldn't be overwritten with today's. Safe to run on every file change.

## External dependency (not in this repo)

The listings live in the Obsidian vault, **outside** this repo, at:

```
~/Exobrain/Projects/Get new job/Job Listings/
```

That path is hardcoded as `LISTINGS` near the top of `reconcile.py`. A cloner
must edit it to point at their own vault location. The folder is part of the
gitignored vault, so it won't be present on a fresh clone — the script logs an
error and exits 1 if the folder is missing.

## Install (launchd)

`run.sh` is the launchd wrapper (`cd`s into this dir, runs `reconcile.py`).
`com.exobrain.job-listings-sync.plist` watches the listings folder and also
fires on a 300s safety interval. Per the harness convention, copy the plist
into `~/Library/LaunchAgents/` as a **real file** (not a symlink — TCC blocks
symlinks under `~/Documents` from loading at login):

```bash
cp com.exobrain.job-listings-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.exobrain.job-listings-sync.plist
```

After editing the plist, copy it again — the LaunchAgents copy is authoritative.
Edit the `WatchPaths` and `run.sh` path in the plist to match your own layout.
