#!/usr/bin/env python3
"""Log a script or tool into the registry, and search what is already logged.

The registry exists so automated work is never redone by hand. Two commands matter:

  search -- run this BEFORE writing a new script. If something already does the job,
            reuse it instead of building a second one.
  add    -- run this AFTER creating or adopting a reusable script/tool, so the next
            session can find it.

Only tools that auto-discovery misses need logging by hand. Already covered for free:
apps with a launcher in /Applications, launchd jobs, executables in a project's bin/
dir (tools-registry-scan.py), and anything installed via brew/npm/pip/uv (which lands
in Dependencies.base). Loose scripts and standalone downloaded binaries do not.

Usage:
  python3 tools-registry/log-tool.py search pdf
  python3 tools-registry/log-tool.py list
  python3 tools-registry/log-tool.py add --name pdf-split.py \
      --command "python3 pdf/pdf-split.py <in.pdf>" \
      --dir "~/Documents/Exobrain harness" --notes "Split a PDF by page ranges."
  python3 tools-registry/log-tool.py remove --name pdf-split.py

INVARIANTS:
  - cli-tools.json stays a name-sorted JSON array; `add` on an existing name updates
    that entry in place rather than appending a duplicate.
  - Adding or removing re-runs the vault projection so Tools.base never lags the log.
"""
import os
import re
import sys
import json
import argparse
import datetime
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "cli-tools.json")
SCAN = os.path.join(HERE, "tools-registry-scan.py")


def load():
    with open(LOG) as fh:
        return json.load(fh)


def save(entries):
    entries.sort(key=lambda e: e["name"].lower())
    with open(LOG, "w") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def reproject():
    """Rebuild the vault notes so the Base reflects the log immediately."""
    subprocess.run([sys.executable, SCAN], check=False)


def show(e):
    line = f"  {e['name']}"
    if e.get("command"):
        line += f"\n      $ {e['command']}"
    if e.get("notes"):
        line += f"\n      {e['notes']}"
    print(line)


def cmd_list(args):
    entries = load()
    print(f"{len(entries)} hand-logged tools in cli-tools.json:\n")
    for e in entries:
        show(e)
    print("\nAlso auto-discovered (no logging needed): /Applications launchers, launchd")
    print("jobs, executables in any project bin/, and brew/npm/pip/uv installs.")


def cmd_search(args):
    pat = re.compile(args.term, re.I)
    hits = [e for e in load()
            if pat.search(" ".join(str(e.get(k, "")) for k in ("name", "command", "notes")))]
    if not hits:
        print(f"No logged tool matches '{args.term}'.")
        print("Check Tools.base / Dependencies.base too before building something new.")
        return 1
    print(f"{len(hits)} match(es) for '{args.term}':\n")
    for e in hits:
        show(e)
    return 0


def cmd_add(args):
    entries = load()
    entry = {
        "name": args.name,
        "command": args.command or "",
        "repo_dir": args.dir or "",
        "source": args.source,
        "added": args.added or datetime.date.today().isoformat(),
        "notes": args.notes or "",
    }
    if args.category != "cli":
        entry["category"] = args.category
    existing = next((e for e in entries if e["name"].lower() == args.name.lower()), None)
    if existing:
        # Keep the original logged date; a re-log is an update, not a new tool.
        entry["added"] = existing.get("added", entry["added"])
        entries[entries.index(existing)] = entry
        print(f"Updated: {args.name}")
    else:
        entries.append(entry)
        print(f"Logged: {args.name}")
    save(entries)
    reproject()
    return 0


def cmd_remove(args):
    entries = load()
    kept = [e for e in entries if e["name"].lower() != args.name.lower()]
    if len(kept) == len(entries):
        print(f"Not logged: {args.name}")
        return 1
    save(kept)
    reproject()
    print(f"Removed: {args.name}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Log and search reusable scripts/tools.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="find an already-logged tool before building one")
    p.add_argument("term", help="regex or substring, matched against name/command/notes")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("list", help="print the whole hand-logged registry")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("add", help="log a new (or update an existing) tool")
    p.add_argument("--name", required=True)
    p.add_argument("--command", help="how to invoke it, with a representative example")
    p.add_argument("--dir", help="repo or install dir; ~ is fine")
    p.add_argument("--notes", help="what it does and any gotcha worth knowing")
    p.add_argument("--source", default="built", choices=["built", "installed", "vendored"])
    p.add_argument("--category", default="cli", choices=["cli", "app", "scheduled-job"])
    p.add_argument("--added", help="ISO date; defaults to today")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("remove", help="drop a tool that no longer exists")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_remove)

    args = ap.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
