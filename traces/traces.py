#!/usr/bin/env python3
"""traces: a durable archive and a DuckDB log table of Claude Code transcripts.

    traces archive [--progress]                 mirror ~/.claude/projects into data/archive
    traces build [--full] [--progress]          load changed archive files into data/traces.duckdb
    traces baseline [--end DATE] [--days N] [--save] [--json]
                                                metrics for [END - N days, END), local midnight
    traces sql "SELECT ..."                     read-only query, printed as a table
    traces nightly                              archive + build; banner and Discord DM on failure

Read README.md in this directory first. bin/traces runs this with traces/.venv.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import trace_archive
import trace_db

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent
BASELINES = HERE / "data" / "baselines"
BUILD_RUNS = HERE / "data" / "build-runs.jsonl"
LOG = Path.home() / "Library" / "Logs" / "exobrain" / "traces.log"


def git_state() -> dict:
    def git(*args: str) -> str:
        out = subprocess.run(["git", "-C", str(HARNESS), *args], capture_output=True, text=True, check=False)
        return out.stdout.strip()
    return {"commit": git("rev-parse", "--short", "HEAD"),
            "traces_dirty": bool(git("status", "--porcelain", "--", "traces"))}


def cmd_baseline(args: argparse.Namespace) -> int:
    start, end = trace_db.window(args.end, args.days)
    con = trace_db.connect(read_only=True)
    m = trace_db.baseline(con, start, end)
    con.close()
    m["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    m["code"] = git_state()
    if args.save:
        spend = subprocess.run([str(HARNESS / "bin" / "claude-spend"), "--json"], capture_output=True, text=True,
                               check=False)
        try:
            m["claude_spend_by_month"] = json.loads(spend.stdout)
        except ValueError:
            m["claude_spend_by_month"] = None
        BASELINES.mkdir(parents=True, exist_ok=True)
        out = BASELINES / f"{end.date().isoformat()}-{args.days}d.json"
        out.write_text(json.dumps(m, indent=2, default=str) + "\n")
        print(f"saved {out}", file=sys.stderr)
    print(json.dumps(m, indent=2, default=str) if args.json else trace_db.render(m))
    return 0


def cmd_sql(args: argparse.Namespace) -> int:
    con = trace_db.connect(read_only=True)
    con.sql(args.query).show(max_rows=args.rows, max_width=200)
    return 0


def notify_failure(summary: dict) -> None:
    text = f"Transcript archive or trace build failed: {summary.get('error')}"
    subprocess.run([str(HARNESS / "mist-voice" / "bin" / "mist-notify"), text, "Transcript archive", "none",
                    str(LOG), "--discord", "--context", json.dumps(summary, default=str)[:4000]],
                   capture_output=True, check=False)


def cmd_nightly(_: argparse.Namespace) -> int:
    summary: dict = {"ts": datetime.now(UTC).isoformat(timespec="seconds")}
    code = trace_archive.main([])
    summary["archive_exit"] = code
    if code != 0:
        summary["error"] = f"archive exited {code}; see {LOG}"
    try:
        summary["build"] = trace_db.build()
    except Exception as exc:  # noqa: BLE001 -- any failure must reach the banner, not just the log
        summary["error"] = f"build: {exc!r}"
    BUILD_RUNS.parent.mkdir(parents=True, exist_ok=True)
    with open(BUILD_RUNS, "a") as fh:
        fh.write(json.dumps(summary, default=str) + "\n")
    print(json.dumps(summary, default=str))
    if "error" in summary:
        notify_failure(summary)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="traces", description="Claude Code transcript archive and trace table.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("archive", help="mirror transcripts into the zstd archive")
    p.add_argument("--progress", action="store_true")
    p = sub.add_parser("build", help="load changed archive files into DuckDB")
    p.add_argument("--full", action="store_true", help="reload every file")
    p.add_argument("--progress", action="store_true")
    p = sub.add_parser("baseline", help="metrics for a time window")
    p.add_argument("--end", help="window end date YYYY-MM-DD, exclusive (default: today)")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--save", action="store_true", help="write data/baselines/<end>-<days>d.json")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("sql", help="read-only query")
    p.add_argument("query")
    p.add_argument("--rows", type=int, default=40)
    sub.add_parser("nightly", help="archive + build, alert on failure")
    args = ap.parse_args(argv)

    if args.cmd == "archive":
        return trace_archive.main(["--progress"] if args.progress else [])
    if args.cmd == "build":
        print(json.dumps(trace_db.build(full=args.full, show_progress=args.progress)))
        return 0
    if args.cmd == "baseline":
        return cmd_baseline(args)
    if args.cmd == "sql":
        return cmd_sql(args)
    return cmd_nightly(args)


if __name__ == "__main__":
    sys.exit(main())
