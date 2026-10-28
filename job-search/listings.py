#!/usr/bin/env python3
"""Keep the Job Listings folder in shape: one folder per listing, no near-miss notes.

Alex 2026-10-28: every listing lives in its own folder `Job Listings/<Company> - <Role>/`,
and near-miss, skipped and unverified listings get no note at all. Those notes did one
job, dedup (tomorrow's scan must not pay for the same JD read again), so before a
near-miss note is deleted its full text goes into a ledger:

    state/near-miss-ledger.jsonl   one JSON object per retired note (gitignored)

dedup-lookup.py, ats-watchlist.py, workday.py and runlog.py read the ledger next to the
notes, so dedup, the auto-built board watchlists and the funnel report see the same
postings as before. `restore` rebuilds a note from the ledger if Alex overrules a decline.

Usage:
    listings.py tidy [--dry-run] [--min-age MINUTES]   retire near-misses, fold loose notes
    listings.py restore "<note name>"                  rebuild a retired note in its folder
    listings.py stats

INVARIANTS:
- A note is deleted only after its ledger line is written and flushed.
- Never retire a note Alex acted on: applied, interviewing, offer, rejected, withdrawn,
  reapply true, or any note whose folder holds an artifact other than posting snapshots.
- Folding never overwrites: a name clash is reported and the note is left in place.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

import jobprofile as P

LEDGER_NAME = "near-miss-ledger.jsonl"
ACTED = {"applied", "interviewing", "offer", "rejected", "withdrawn"}
KEYS = ("company", "role", "status", "verified", "declined", "fit_gate", "fit_score",
        "apply_url", "listing_url", "original_listing", "job_id", "source", "date_added")
SNAPSHOT = re.compile(r" - posting \d{4}-\d{2}-\d{2}\.png$")


def ledger_path() -> Path:
    return P.state_dir() / LEDGER_NAME


def field(txt: str, key: str) -> str:
    head = txt.split("\n---", 1)[0] if txt.startswith("---") else txt[:3000]
    m = re.search(r"^%s:\s*(.*)$" % re.escape(key), head, re.M)
    return m.group(1).strip().strip("'\"") if m else ""


def is_listing(txt: str) -> bool:
    return bool(re.search(r"^type:\s*['\"]?job-listing\b", txt[:1500], re.M))


def is_near_miss(txt: str) -> bool:
    """Skipped, declined without Alex acting on it, or an unverified candidate."""
    status = field(txt, "status").lower()
    if status in ACTED or field(txt, "reapply").lower() == "true" or field(txt, "applied") == "true":
        return False
    if status == "skipped" or field(txt, "declined") == "true":
        return True
    return status == "candidate" and field(txt, "verified") == "false"


def has_artifacts(note: Path, root: Path) -> bool:
    if note.parent == root:
        return False
    return any(p != note and not SNAPSHOT.search(p.name) and not p.name.startswith(".")
               for p in note.parent.iterdir())


def load_ledger() -> list[dict]:
    p = ledger_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").split("\n"):  # not splitlines(): JD text holds U+2028
        if line.strip():
            out.append(json.loads(line))
    return out


def retire(note: Path, root: Path) -> None:
    txt = note.read_text(encoding="utf-8", errors="replace")
    rec = {"name": note.stem, "retired": dt.date.today().isoformat(),
           **{k: field(txt, k) for k in KEYS}, "text": txt}
    with ledger_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    note.unlink()
    if note.parent != root:
        for p in note.parent.iterdir():
            if SNAPSHOT.search(p.name) or p.name == ".DS_Store":
                p.unlink()
        note.parent.rmdir()


def fold(note: Path, root: Path) -> Path | None:
    """Move a note that sits in the listings root into its own same-named folder."""
    folder = root / note.stem
    dest = folder / note.name
    if dest.exists():
        return None
    folder.mkdir(exist_ok=True)
    return note.rename(dest)


def tidy(root: Path, dry: bool, min_age: float) -> dict[str, list[str]]:
    done: dict[str, list[str]] = {"retired": [], "folded": [], "kept": [], "clash": []}
    cutoff = time.time() - min_age * 60
    for note in sorted(root.rglob("*.md")):
        try:
            txt = note.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not is_listing(txt) or note.stat().st_mtime > cutoff:
            continue
        if is_near_miss(txt):
            if has_artifacts(note, root):
                done["kept"].append(note.stem)
                continue
            done["retired"].append(note.stem)
            if not dry:
                retire(note, root)
        elif note.parent == root:
            if (root / note.stem / note.name).exists():
                done["clash"].append(note.stem)
                continue
            done["folded"].append(note.stem)
            if not dry:
                fold(note, root)
    return done


def restore(name: str, root: Path) -> Path:
    recs = load_ledger()
    hits = [i for i, r in enumerate(recs) if r["name"] == name]
    if not hits:
        raise SystemExit(f"not in the ledger: {name}")
    i = hits[-1]
    folder = root / name
    folder.mkdir(exist_ok=True)
    dest = folder / f"{name}.md"
    if dest.exists():
        raise SystemExit(f"already exists: {dest}")
    dest.write_text(recs[i]["text"], encoding="utf-8")
    keep = [r for j, r in enumerate(recs) if j != i]
    tmp = ledger_path().with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep), encoding="utf-8")
    tmp.replace(ledger_path())
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tidy")
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--min-age", type=float, default=0,
                   help="skip notes modified in the last N minutes (a session may be writing them)")
    r = sub.add_parser("restore")
    r.add_argument("name")
    sub.add_parser("stats")
    a = ap.parse_args()
    root = P.listings_dir()

    if a.cmd == "tidy":
        done = tidy(root, a.dry_run, a.min_age)
        verb = "would " if a.dry_run else ""
        print(f"{verb}retire {len(done['retired'])} near-miss note(s) to {ledger_path()}")
        print(f"{verb}fold {len(done['folded'])} loose note(s) into folders")
        for k in ("kept", "clash"):
            for n in done[k]:
                print(f"  {k.upper()}: {n}" + ("  (near-miss with artifacts, left in place)" if k == "kept"
                                               else "  (folder already holds a note of that name)"))
    elif a.cmd == "restore":
        print(f"restored -> {restore(a.name, root)}")
    else:
        recs = load_ledger()
        print(f"ledger: {len(recs)} retired near-miss note(s) in {ledger_path()}")
        loose = [p for p in root.glob("*.md")]
        print(f"loose notes in the listings root: {len(loose)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
