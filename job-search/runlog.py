#!/usr/bin/env python3
"""Per-lane run record and yield report.

Without a structured record, the only trace of a daily scan is the model's
prose summary, and there is no way to answer "which lane finds the jobs I
apply to?". This module keeps one JSON line per lane run in
`state/runs.jsonl` and joins it with the tracker notes for the yield report.

Three ways in:
  - a lane imports it:      run = runlog.Run("freehire"); run.count(survivor=3); run.save()
  - any command, wrapped:   runlog.py wrap dice -- python3 job-search/dice.py "IT analyst"
                            (records exit code, duration, and the survivor / lead
                            counts parsed from the lane's own summary line)
  - the report:             runlog.py yield [--days 30]

The yield report counts, per lane: runs, failed runs, rows, survivors, leads
(from runs.jsonl), and then the tracker funnel by the notes' `source:` field:
notes, applied, interviewing, offer. A lane with many runs and no applied notes
is a candidate to demote; a lane that fails often is a tooling problem, not a
dry source, and the report keeps the two apart.

INVARIANTS
- A wrapped command's output passes through unchanged, and its exit code is
  returned unchanged.
- One line per run, appended; the file is never rewritten.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import jobprofile as P

COUNT_RE = re.compile(r"(\d+)\s+(?:new\s+)?(?:verified\s+)?(survivors?|leads?|declined|title-dropped|unique|rows)\b", re.I)


def runs_file() -> Path:
    return P.state_dir() / "runs.jsonl"


class Run:
    def __init__(self, lane: str):
        self.lane = lane
        self.t0 = time.time()
        self.counts: dict[str, int] = {}
        self.notes: list[str] = []
        self.exit = 0

    def count(self, **kw: int) -> None:
        for k, v in kw.items():
            self.counts[k] = self.counts.get(k, 0) + int(v)

    def note(self, text: str) -> None:
        self.notes.append(text[:200])

    def save(self) -> None:
        if os.environ.get("RUNLOG_WRAPPED"):
            # Inside `runlog.py wrap`: hand the counts to the wrapper, which
            # writes the one record for this run.
            print("RUNLOG-COUNTS " + json.dumps({"counts": self.counts, "notes": self.notes}), flush=True)
            return
        rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "lane": self.lane,
               "exit": self.exit, "secs": round(time.time() - self.t0, 1),
               "counts": self.counts, "notes": self.notes[:20]}
        with runs_file().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")


def parse_counts(text: str) -> dict[str, int]:
    """Survivor / lead counts from a lane's summary line. The lanes print
    "N survivors | N leads | ..." in slightly different words."""
    out: dict[str, int] = {}
    for n, word in COUNT_RE.findall(text):
        key = word.lower().rstrip("s")
        key = "rows" if key == "row" else key
        out[key] = max(out.get(key, 0), int(n))
    return out


def wrap(lane: str, cmd: list[str]) -> int:
    run = Run(lane)
    env = dict(os.environ, RUNLOG_WRAPPED=lane)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
    buf = []
    own: dict | None = None
    assert proc.stdout is not None
    for line in proc.stdout:
        if line.startswith("RUNLOG-COUNTS "):
            own = json.loads(line.split(" ", 1)[1])
            continue
        sys.stdout.write(line)
        buf.append(line)
        if re.search(r"NOT RUN|DID NOT RUN|FAILED|BLOCKED|~ COVERAGE|TRUNCATED", line):
            run.note(line.strip())
    run.exit = proc.wait()
    if own:  # the lane counted itself; trust that over parsing its text
        run.count(**own["counts"])
        run.notes += own.get("notes", [])
    else:
        run.count(**parse_counts("".join(buf[-80:])))
    run.save()
    return run.exit


def tracker_funnel() -> dict[str, collections.Counter]:
    """{source: Counter(status)} over every job-listing note."""
    funnel: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for root, dirs, files in P.walk_roots():
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if not name.endswith(".md"):
                continue
            try:
                head = (Path(root) / name).read_text(encoding="utf-8", errors="replace")[:3000]
            except OSError:
                continue
            fm = head.split("\n---", 1)[0]
            if not re.search(r"^type:\s*['\"]?job-listing\b", fm, re.M):
                continue
            src = re.search(r"^source:\s*['\"]?([^'\"\n]+)", fm, re.M)
            st = re.search(r"^status:\s*['\"]?([\w-]+)", fm, re.M)
            source = src.group(1).strip().lower() if src else "unknown"
            if source.startswith("http"):
                source = "url"
            funnel[source][st.group(1).lower() if st else "unknown"] += 1
    return funnel


def report(days: int) -> None:
    since = (dt.datetime.now() - dt.timedelta(days=days)).isoformat()
    lanes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    f = runs_file()
    for line in f.read_text().splitlines() if f.exists() else []:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("ts", "") < since:
            continue
        c = lanes[r["lane"]]
        c["runs"] += 1
        c["failed"] += r.get("exit", 0) != 0
        c["secs"] += int(r.get("secs", 0))
        for k in ("rows", "survivor", "lead"):
            c[k] += r.get("counts", {}).get(k, 0)

    print(f"LANE RUNS, last {days} days ({f})")
    print(f"  {'lane':18}{'runs':>6}{'failed':>8}{'rows':>8}{'surv':>7}{'leads':>7}{'min':>6}")
    for lane, c in sorted(lanes.items(), key=lambda kv: -kv[1]["survivor"]):
        print(f"  {lane:18}{c['runs']:>6}{c['failed']:>8}{c['rows']:>8}{c['survivor']:>7}"
              f"{c['lead']:>7}{c['secs'] // 60:>6}")
    if not lanes:
        print("  (no runs recorded yet: wrap the lanes with `runlog.py wrap <lane> -- <cmd>`)")

    print("\nTRACKER FUNNEL by note `source:` (all time)")
    print(f"  {'source':22}{'notes':>7}{'skipped':>9}{'applied+':>10}{'interview':>11}{'offer':>7}")
    later = ("applied", "interviewing", "offer", "rejected", "withdrawn", "closed")
    for src, c in sorted(tracker_funnel().items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  {src[:21]:22}{sum(c.values()):>7}{c['skipped']:>9}{sum(c[s] for s in later):>10}"
              f"{c['interviewing'] + c['offer']:>11}{c['offer']:>7}")


def main() -> int:
    ap = argparse.ArgumentParser(description="per-lane run record and yield report")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wrap", help="run a lane command and record it")
    w.add_argument("lane")
    w.add_argument("command", nargs=argparse.REMAINDER)
    y = sub.add_parser("yield", help="per-lane yield and tracker funnel")
    y.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    if a.cmd == "wrap":
        cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
        if not cmd:
            ap.error("wrap needs a command after --")
        return wrap(a.lane, cmd)
    report(a.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
