#!/usr/bin/env python3
"""Log a script or tool into the registry, and search what is already logged.

The registry exists so automated work is never redone by hand. Two commands matter:

  search   -- run this BEFORE writing a new script. If something already does the job,
              reuse it instead of building a second one.
  add      -- run this AFTER creating or adopting a reusable script/tool, so the next
              session can find it. Always pass --description.
  describe -- set or replace the natural-language description of ANY tool, including the
              auto-discovered ones (apps, launchd jobs, bin/ executables) that have no
              cli-tools.json entry. A description says what the tool is, what it was
              created for, and the kinds of task it fits in future, in a few sentences.
  missing  -- list every tool in the registry that still has no description.

Only tools that auto-discovery misses need logging by hand. Already covered for free:
apps with a launcher in /Applications, launchd jobs, executables in a project's bin/
dir (tools-registry-scan.py), and anything installed via brew/npm/pip/uv (which lands
in Dependencies.base). Loose scripts and standalone downloaded binaries do not.

Usage:
  python3 tools-registry/log-tool.py search pdf
  python3 tools-registry/log-tool.py list
  python3 tools-registry/log-tool.py add --name pdf-split.py \
      --command "python3 pdf/pdf-split.py <in.pdf>" \
      --dir "~/Documents/Exobrain harness" --notes "Needs pypdf; page ranges are 1-based." \
      --description "Splits a PDF into files by page range. Built to carve chapters out of \
      scanned rulebooks for the TTRPG vault. Use it whenever a PDF needs slicing before \
      OCR, upload, or printing."
  python3 tools-registry/log-tool.py describe --name com.exobrain.backup \
      --description "Nightly GFS backup of the vault to Google Drive ..."
  python3 tools-registry/log-tool.py missing
  python3 tools-registry/log-tool.py remove --name pdf-split.py

INVARIANTS:
  - cli-tools.json stays a name-sorted JSON array; `add` on an existing name updates
    that entry in place rather than appending a duplicate.
  - tool-descriptions.json stays a name-sorted JSON object of name -> description string,
    and is the ONLY place descriptions live (cli-tools.json entries carry no prose fields).
  - Adding, describing, or removing re-runs the vault projection so Tools.base never
    lags the log.
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
DESCRIPTIONS = os.path.join(HERE, "tool-descriptions.json")
SCAN = os.path.join(HERE, "tools-registry-scan.py")


def load():
    with open(LOG) as fh:
        return json.load(fh)


def save(entries):
    entries.sort(key=lambda e: e["name"].lower())
    with open(LOG, "w") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def load_descriptions():
    try:
        with open(DESCRIPTIONS) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def save_descriptions(desc):
    ordered = dict(sorted(desc.items(), key=lambda kv: kv[0].lower()))
    with open(DESCRIPTIONS, "w") as fh:
        json.dump(ordered, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def set_description(name, text):
    """Store text under the tool's name, replacing any existing key that differs only in case."""
    desc = load_descriptions()
    for existing in list(desc):
        if existing.lower() == name.lower():
            del desc[existing]
    desc[name] = text.strip()
    save_descriptions(desc)


def description_of(name):
    for k, v in load_descriptions().items():
        if k.lower() == name.lower():
            return v
    return ""


def registry_names():
    """Every tool name the scan would project, discovered and hand-logged alike."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("tools_registry_scan", SCAN)
    assert spec is not None and spec.loader is not None, SCAN
    scan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan)
    items = scan.merge(scan.load_manual(), scan.scan_apps(), scan.scan_jobs(set()), scan.scan_cli())
    return [(i["name"], i["category"]) for i in items]


def reproject():
    """Rebuild the vault notes so the Base reflects the log immediately."""
    subprocess.run([sys.executable, SCAN], check=False)


def show(e, desc):
    """Print one tool: name, invocation, description, then operational notes."""
    line = f"  {e['name']}"
    if e.get("command"):
        line += f"\n      $ {e['command']}"
    text = desc.get(e["name"].lower(), "")
    if text:
        line += f"\n      {text}"
    if e.get("notes"):
        line += f"\n      Notes: {e['notes']}"
    print(line)


def cmd_list(args):
    entries = load()
    desc = {k.lower(): v for k, v in load_descriptions().items()}
    print(f"{len(entries)} hand-logged tools in cli-tools.json:\n")
    for e in entries:
        show(e, desc)
    print("\nAlso auto-discovered (no logging needed): /Applications launchers, launchd")
    print("jobs, executables in any project bin/, and brew/npm/pip/uv installs.")


def cmd_search(args):
    """Match against every registered tool: hand-logged fields plus all descriptions."""
    pat = re.compile(args.term, re.I)
    desc = {k.lower(): v for k, v in load_descriptions().items()}
    entries = {e["name"].lower(): e for e in load()}
    for name, category in registry_names():
        entries.setdefault(name.lower(), {"name": name, "category": category})
    hits = []
    for key, e in entries.items():
        hay = " ".join(str(e.get(k, "")) for k in ("name", "command", "notes"))
        if pat.search(hay + " " + desc.get(key, "")):
            hits.append(e)
    if not hits:
        print(f"No registered tool matches '{args.term}'.")
        print("Check Dependencies.base too before building something new.")
        return 1
    hits.sort(key=lambda e: e["name"].lower())
    print(f"{len(hits)} match(es) for '{args.term}':\n")
    for e in hits:
        show(e, desc)
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
    if args.description:
        set_description(args.name, args.description)
    elif not description_of(args.name):
        print(f"WARN: {args.name} has no description; add one with "
              f"`log-tool.py describe --name '{args.name}' --description ...`")
    reproject()
    return 0


def cmd_describe(args):
    if not args.description.strip():
        print("Description must not be empty.")
        return 1
    known = {n.lower() for n, _ in registry_names()}
    if args.name.lower() not in known:
        print(f"WARN: {args.name} is not in the registry (no launcher, job, bin/ entry, or "
              f"cli-tools.json record). Storing the description anyway; it will attach once "
              f"the tool exists, or `add` it now.")
    set_description(args.name, args.description)
    print(f"Described: {args.name}")
    reproject()
    return 0


def cmd_missing(args):
    desc = {k.lower() for k, v in load_descriptions().items() if v.strip()}
    gaps = [(n, c) for n, c in registry_names() if n.lower() not in desc]
    if not gaps:
        print("Every registered tool has a description.")
        return 0
    print(f"{len(gaps)} tool(s) without a description:\n")
    for name, category in sorted(gaps, key=lambda t: (t[1], t[0].lower())):
        print(f"  [{category}] {name}")
    print("\nFill each with: log-tool.py describe --name <name> --description \"...\"")
    return 1


def cmd_remove(args):
    entries = load()
    kept = [e for e in entries if e["name"].lower() != args.name.lower()]
    if len(kept) == len(entries):
        print(f"Not logged: {args.name}")
        return 1
    save(kept)
    desc = load_descriptions()
    for existing in list(desc):
        if existing.lower() == args.name.lower():
            del desc[existing]
    save_descriptions(desc)
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
    p.add_argument("--notes", help="invocation gotchas and operational details")
    p.add_argument("--description", help="a few sentences: what it is, what it was created "
                   "for, and the kinds of task it fits in future")
    p.add_argument("--source", default="built", choices=["built", "installed", "vendored"])
    p.add_argument("--category", default="cli", choices=["cli", "app", "scheduled-job"])
    p.add_argument("--added", help="ISO date; defaults to today")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("describe", help="set the description of any registered tool")
    p.add_argument("--name", required=True, help="exact tool name as shown in Tools.base")
    p.add_argument("--description", required=True, help="what it is, what it was created "
                   "for, and the kinds of task it fits in future")
    p.set_defaults(func=cmd_describe)

    p = sub.add_parser("missing", help="list registered tools with no description")
    p.set_defaults(func=cmd_missing)

    p = sub.add_parser("remove", help="drop a tool that no longer exists")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_remove)

    args = ap.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
