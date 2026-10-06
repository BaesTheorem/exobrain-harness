# kc-civic/data

Gitignored runtime data. Safe to delete except `lens.md`.

| Path | What | Rebuild |
|---|---|---|
| `state.json` | Calendar sync hashes, event ids, prep records, EDC cache | Delete it and the next sync re-matches calendar events by their `kccivicId` key; nothing duplicates. |
| `packets/` | Per-meeting agenda packets (agenda text, attachments, page snapshots, `summary.json`, `claude.log`) | Rebuilt by `kc-civic prep KEY --force`. |
| `lens.md` | Alex's policy lens that the prep run reads to rank agenda items | Personal; not in git. Without it, `prep.py` writes a neutral default lens into each packet. |
