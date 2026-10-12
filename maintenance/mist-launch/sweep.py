#!/usr/bin/env python3
"""Declare every tracked launchd agent through mist-launch, in place.

For each plist git tracks in the given repo (default: this one) that is
installed in ~/Library/LaunchAgents, rewrite the SOURCE plist so that
ProgramArguments starts with the launcher and the job names MIST Console as its
associated app, install the copy, and re-bootstrap the job. Comments and
formatting in the plist survive: the edit is textual, then verified with
plutil and by re-parsing.

    maintenance/mist-launch/sweep.py                 # dry run: show the plan
    maintenance/mist-launch/sweep.py --apply         # do it (harness repo)
    maintenance/mist-launch/sweep.py --repo ~/Documents/mist-console --apply
    maintenance/mist-launch/sweep.py --only com.exobrain.mem-watchdog --apply

Refuses to apply until the launcher is installed, signed with the Console's
team, and holds Full Disk Access (the job's file access is the launcher's: see
mist-launch.c). Refuses a plist whose installed copy differs from the repo copy
(fix the drift first; --force-repo overrides). Skips LaunchDaemons (root jobs
have their own TCC story), jobs already declared through the launcher, and
jobs that are not loaded on this machine (installing them is not this tool's
call).

INVARIANTS: never writes a plist that fails `plutil -lint`; never leaves a job
unloaded that was loaded before (a failed bootstrap is reported and the
previous plist restored).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path.home()
LAUNCHER = Path(os.environ.get("MIST_LAUNCH_DEST", HOME / ".local/bin/mist-launch"))
AGENTS = HOME / "Library/LaunchAgents"
APP = "/Applications/MIST Console.app"
BUNDLE_ID = "com.exobrain.mist-console"
TCC_DB = "/Library/Application Support/com.apple.TCC/TCC.db"


def sh(*cmd: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def team_of(path: str) -> str:
    out = sh("codesign", "-dv", path).stderr
    m = re.search(r"^TeamIdentifier=(\S+)", out, re.M)
    return m.group(1) if m else ""


def launcher_ready() -> list[str]:
    """Why the launcher is not usable yet, as a list of problems (empty = ready)."""
    problems = []
    if not LAUNCHER.is_file() or not os.access(LAUNCHER, os.X_OK):
        return [f"{LAUNCHER} is not installed (run maintenance/mist-launch/install.sh)"]
    app_team, bin_team = team_of(APP), team_of(str(LAUNCHER))
    if not app_team or app_team != bin_team:
        problems.append(f"launcher team {bin_team!r} differs from the Console's {app_team!r}")
    try:
        con = sqlite3.connect(f"file:{TCC_DB}?mode=ro", uri=True)
        rows = con.execute(
            "select auth_value from access where service='kTCCServiceSystemPolicyAllFiles' and client=?",
            (str(LAUNCHER),)).fetchall()
        con.close()
        if not any(r[0] == 2 for r in rows):
            problems.append("launcher has no Full Disk Access grant yet (System Settings > Privacy & Security > Full Disk Access)")
    except sqlite3.Error as exc:
        problems.append(f"cannot read the TCC database to confirm the grant: {exc}")
    return problems


def plist_json(path: Path) -> dict:
    out = sh("plutil", "-convert", "json", "-o", "-", str(path), check=True).stdout
    return json.loads(out)


def loaded_labels() -> set[str]:
    out = sh("launchctl", "list").stdout
    return {line.split("\t")[-1].strip() for line in out.splitlines()[1:] if line.strip()}


def rewrite(text: str, launcher: str) -> str:
    """Prepend the launcher to ProgramArguments and add the app association."""
    m = re.search(r"(<key>ProgramArguments</key>\s*<array>)(\s*)", text)
    if not m:
        raise ValueError("no ProgramArguments array (a bare Program key is not handled)")
    indent = m.group(2)
    # indentation of the first <string> inside the array, or two levels deep
    inner = re.match(r"\n([ \t]*)", indent)
    pad = inner.group(1) if inner else "        "
    text = text[:m.end(1)] + "\n" + pad + f"<string>{launcher}</string>" + text[m.end(1):]
    if "AssociatedBundleIdentifiers" not in text:
        close = text.rfind("</dict>")
        key_pad = re.search(r"\n([ \t]*)<key>ProgramArguments</key>", text)
        kp = key_pad.group(1) if key_pad else "    "
        block = (f"{kp}<!-- Login Items shows the job under this app instead of its executable's name;\n"
                 f"{kp}     only honored because mist-launch is signed by the same team. -->\n"
                 f"{kp}<key>AssociatedBundleIdentifiers</key>\n"
                 f"{kp}<array>\n{kp}    <string>{BUNDLE_ID}</string>\n{kp}</array>\n")
        text = text[:close] + block + text[close:]
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--apply", action="store_true", help="write, install and re-bootstrap (default: plan only)")
    ap.add_argument("--only", action="append", default=[], help="label(s) to limit to")
    ap.add_argument("--skip", action="append", default=[], help="label(s) to leave alone")
    ap.add_argument("--force-repo", action="store_true", help="overwrite an installed copy that drifted from the repo")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()

    tracked = sh("git", "-C", str(repo), "ls-files", "*.plist", "**/*.plist").stdout.split()
    loaded = loaded_labels()
    launcher = str(LAUNCHER)
    plan, skipped = [], []
    for rel in sorted(set(tracked)):
        src = repo / rel
        try:
            p = plist_json(src)
        except Exception as exc:
            skipped.append((rel, f"unparseable: {exc}")); continue
        label = p.get("Label", "")
        if args.only and label not in args.only:
            continue
        if label in args.skip:
            skipped.append((rel, "skipped by request")); continue
        installed = AGENTS / src.name
        if "LaunchDaemons" in rel or "/launchd/" in rel and "Daemon" in src.name:
            skipped.append((rel, "LaunchDaemon (root): out of scope")); continue
        if not installed.is_file():
            skipped.append((rel, "not installed in ~/Library/LaunchAgents")); continue
        if label not in loaded:
            skipped.append((rel, "not loaded on this machine")); continue
        argv = p.get("ProgramArguments") or []
        if not argv:
            skipped.append((rel, "no ProgramArguments")); continue
        if argv[0] == launcher:
            skipped.append((rel, "already through mist-launch")); continue
        drift = src.read_bytes() != installed.read_bytes()
        plan.append((rel, label, argv[0], drift))

    width = max((len(x[1]) for x in plan), default=20)
    print(f"{'label':{width}}  {'declared as':28} drift  source")
    for rel, label, exe, drift in plan:
        print(f"{label:{width}}  {os.path.basename(exe):28} {'YES' if drift else '-':5}  {rel}")
    print(f"\n{len(plan)} to rewrite, {len(skipped)} skipped")
    for rel, why in skipped:
        print(f"  skip {rel}: {why}")

    if not args.apply:
        probs = launcher_ready()
        print("\nDry run. " + ("Launcher ready." if not probs else "Launcher NOT ready: " + "; ".join(probs)))
        return 0
    probs = launcher_ready()
    if probs:
        print("\nRefusing to apply: " + "; ".join(probs), file=sys.stderr)
        return 2
    drifted = [x for x in plan if x[3]]
    if drifted and not args.force_repo:
        print("\nRefusing to apply: installed copies differ from the repo for: "
              + ", ".join(x[1] for x in drifted) + " (adopt or --force-repo)", file=sys.stderr)
        return 2

    uid = os.getuid()
    ok = fail = 0
    for rel, label, _exe, _drift in plan:
        src = repo / rel
        installed = AGENTS / src.name
        original = src.read_text()
        try:
            new = rewrite(original, launcher)
        except ValueError as exc:
            print(f"FAIL {label}: {exc}"); fail += 1; continue
        with tempfile.NamedTemporaryFile("w", suffix=".plist", delete=False) as tmp:
            tmp.write(new); tmp_path = tmp.name
        lint = sh("plutil", "-lint", tmp_path)
        try:
            check = plist_json(Path(tmp_path))
        except Exception:
            check = {}
        if lint.returncode != 0 or (check.get("ProgramArguments") or [None])[0] != launcher:
            os.unlink(tmp_path)
            print(f"FAIL {label}: rewritten plist did not verify ({lint.stdout.strip()})"); fail += 1; continue
        backup = installed.with_suffix(".plist.pre-mist-launch")
        shutil.copy2(installed, backup)
        src.write_text(new)
        shutil.copy2(tmp_path, installed)
        os.unlink(tmp_path)
        sh("launchctl", "bootout", f"gui/{uid}/{label}")
        boot = sh("launchctl", "bootstrap", f"gui/{uid}", str(installed))
        if boot.returncode != 0:
            # restore the previous plist and job so nothing stays unloaded
            shutil.copy2(backup, installed)
            src.write_text(original)
            sh("launchctl", "bootstrap", f"gui/{uid}", str(installed))
            print(f"FAIL {label}: bootstrap refused ({boot.stderr.strip()[:120]}); restored"); fail += 1; continue
        backup.unlink(missing_ok=True)
        print(f"ok   {label}"); ok += 1
    print(f"\n{ok} rewritten and re-bootstrapped, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
