#!/usr/bin/env python3
"""Mirror Claude Code session transcripts into a zstd archive that nothing prunes.

Claude Code silently deletes a transcript once it has gone unused for
cleanupPeriodDays (60 in ~/.claude/settings.json), and the nightly backup skips
~/.claude/projects by design. This archive is the durable copy. Every file
under the source tree is compressed to <archive>/<same relative path>.zst.
Symlinked dirs are not followed, so the memory dirs that link to MIST's one
memory store are not copied twice.

INVARIANTS
- Never delete or truncate an archive file. A source file that disappears
  keeps its last archived copy: that is the purpose of the archive.
- An archive file's mtime equals the mtime its source had before the read. A
  source whose mtime differs, or that has no archive file, is archived again.
- Writes are atomic (temp file, then rename). A new copy is read back and
  hash-checked against the bytes that went in before it replaces the old one.
- Stdlib only. Needs Python 3.14+ for compression.zstd.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from compression import zstd

CHUNK = 1 << 20
DEFAULT_LEVEL = 9  # measured 2026-10-15: 3.1x at 9 and at 19, but 19 is 19x slower
HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = Path.home() / ".claude" / "projects"
DEFAULT_DEST = HERE / "data" / "archive"
DEFAULT_RUNS = HERE / "data" / "archive-runs.jsonl"


def iter_sources(src: Path):
    """Yield (path, relative path) for every file to archive."""
    for dirpath, dirnames, filenames in os.walk(src):  # followlinks=False: skip symlinked dirs
        rel_dir = Path(dirpath).relative_to(src)
        dirnames.sort()
        for name in sorted(filenames):
            if name.startswith(".") or name.endswith(".tmp"):
                continue
            yield Path(dirpath) / name, rel_dir / name


def archive_one(source: Path, dest: Path, level: int, mtime_ns: int) -> tuple[int, int]:
    """Compress source to dest atomically, verify it, stamp dest with mtime_ns."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    digest = hashlib.sha256()
    size_in = 0
    try:
        with open(source, "rb") as fin, open(tmp, "wb") as raw:
            with zstd.ZstdFile(raw, "w", level=level) as zout:
                while chunk := fin.read(CHUNK):
                    digest.update(chunk)
                    size_in += len(chunk)
                    zout.write(chunk)
        check = hashlib.sha256()
        with zstd.ZstdFile(tmp, "r") as zin:
            while chunk := zin.read(CHUNK):
                check.update(chunk)
        if check.digest() != digest.digest():
            raise OSError(f"verify failed: {source}")
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    os.utime(dest, ns=(mtime_ns, mtime_ns))
    return size_in, dest.stat().st_size


def progress(cmd: str, **kw: object) -> None:
    """Draw a MIST Console progress bar when one can be drawn; never fail."""
    if not shutil.which("mist-progress"):
        return
    args = ["mist-progress", cmd, "--id", "trace-archive"] + [f"--{k}={v}" for k, v in kw.items()]
    subprocess.run(args, capture_output=True, check=False)


def run(src: Path, dest: Path, level: int = DEFAULT_LEVEL, dry_run: bool = False,
        show_progress: bool = False) -> dict:
    started = time.time()
    todo: list[tuple[Path, Path, int, bool]] = []
    seen: set[Path] = set()
    scanned = 0
    for path, rel in iter_sources(src):
        scanned += 1
        target = dest / rel.with_name(rel.name + ".zst")
        seen.add(target)
        try:
            mtime_ns = path.stat().st_mtime_ns
        except FileNotFoundError:  # deleted between walk and stat
            continue
        try:
            current = target.stat().st_mtime_ns
        except FileNotFoundError:
            todo.append((path, target, mtime_ns, True))
            continue
        if current != mtime_ns:
            todo.append((path, target, mtime_ns, False))

    stats = {"new": 0, "updated": 0, "bytes_in": 0, "bytes_out": 0}
    errors: list[str] = []
    if show_progress and todo:
        progress("start", label="Archiving Claude Code transcripts", total=len(todo))
    for i, (path, target, mtime_ns, is_new) in enumerate(todo):
        if show_progress and i % 25 == 0:
            progress("set", current=i)
        if dry_run:
            stats["new" if is_new else "updated"] += 1
            continue
        try:
            size_in, size_out = archive_one(path, target, level, mtime_ns)
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        stats["new" if is_new else "updated"] += 1
        stats["bytes_in"] += size_in
        stats["bytes_out"] += size_out
    if show_progress and todo:
        progress("done")

    archived = rescued = 0
    total_bytes = 0
    if dest.exists():
        for p in dest.rglob("*.zst"):
            archived += 1
            total_bytes += p.stat().st_size
            if p not in seen:
                rescued += 1
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(src),
        "dest": str(dest),
        "dry_run": dry_run,
        "scanned": scanned,
        **stats,
        "archive_files": archived,
        "archive_bytes": total_bytes,
        "rescued": rescued,  # archived files whose source is gone (pruned by Claude Code)
        "errors": errors[:50],
        "error_count": len(errors),
        "seconds": round(time.time() - started, 1),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Mirror Claude Code transcripts into a zstd archive.")
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--runs-log", type=Path, default=DEFAULT_RUNS,
                    help="append one JSON line per run here ('-' to skip)")
    ap.add_argument("--level", type=int, default=DEFAULT_LEVEL)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--progress", action="store_true", help="draw a MIST Console progress bar")
    args = ap.parse_args(argv)
    if not args.source.is_dir():
        print(f"source missing: {args.source}", file=sys.stderr)
        return 2
    summary = run(args.source, args.dest, args.level, args.dry_run, args.progress)
    if str(args.runs_log) != "-" and not args.dry_run:
        args.runs_log.parent.mkdir(parents=True, exist_ok=True)
        with open(args.runs_log, "a") as fh:
            fh.write(json.dumps(summary) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "errors"}))
    for err in summary["errors"]:
        print("ERROR", err, file=sys.stderr)
    return 1 if summary["error_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
