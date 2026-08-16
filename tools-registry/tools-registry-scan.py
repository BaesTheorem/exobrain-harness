#!/usr/bin/env python3
"""Scan the machine for every tool Alex has built and project them into Obsidian notes.

Single source of truth for "what have I made / installed." Auto-discovers from the two
authoritative on-disk sources, so it never drifts:

  1. App launchers  -> /Applications/*.app  (parses Contents/MacOS/launch for DIR + PORT)
  2. Scheduled jobs -> ~/Library/LaunchAgents/{com.exobrain,com.mist,com.nightwatch,com.alexhedtke}*.plist
  3. CLI entry points -> executables in any ~/Documents/*/bin (and */*/bin) directory

For each item it records repo dir, git remote, port, launcher/script, schedule, and LIVE
status (port listening / job loaded). Emits one note per tool into the vault "Tools/" folder,
which "Tools.base" renders. Idempotent: the folder is wiped and rewritten each run.

Loose scripts that live outside a bin/ dir, plus third-party CLIs worth remembering, are
logged by hand in cli-tools.json. Add to it with log-tool.py rather than editing the JSON
directly, and search it before writing a new script -- the point of the registry is that
work already automated once never gets redone by hand.

Usage:  python3 tools-registry-scan.py
"""
import os
import re
import glob
import json
import socket
import plistlib
import subprocess

HOME = os.path.expanduser("~")
APPS_DIR = "/Applications"
LAUNCHAGENTS = os.path.join(HOME, "Library", "LaunchAgents")
JOB_PREFIXES = ("com.exobrain.", "com.mist.", "com.nightwatch.", "com.alexhedtke.")
VAULT_FOLDER = os.path.join(HOME, "Exobrain", "Tools")
VAULT_DEPS = os.path.join(HOME, "Exobrain", "Dependencies")
VAULT_PROJDEPS = os.path.join(HOME, "Exobrain", "Project Dependencies")
PROJECTS_ROOT = os.path.join(HOME, "Documents")
PRUNE = {"node_modules", ".venv", "site-packages", ".git", "__pycache__"}
BREW = "/opt/homebrew/bin/brew"
HB_PY = "/opt/homebrew/bin/python3"

ILLEGAL = re.compile(r'[\\/:#^\[\]|*?"<>]')

# Hand-logged CLI tools and scripts: the ones with no launcher, no launchd job, and no
# bin/ entry point, plus third-party CLIs worth remembering. Written by log-tool.py.
MANUAL_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli-tools.json")


def port_live(port):
    if not port:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def git_remote(repo_dir):
    if not repo_dir or not os.path.isdir(repo_dir):
        return ""
    try:
        out = subprocess.run(["git", "-C", repo_dir, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def loaded_labels():
    """Labels currently loaded in launchd (from `launchctl list`)."""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
        labels = set()
        for line in out.stdout.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 3:
                labels.add(parts[2].strip())
        return labels
    except Exception:
        return set()


def find_repo_root(path):
    d = path if os.path.isdir(path) else os.path.dirname(path)
    while d and d != "/":
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return ""


def script_launcher(app):
    """Path to the app's shell-script launcher, or "" if it has none.

    Our own bundles wrap a shell script (named launch, launcher, or after the
    app) that runs something out of Alex's home dir; third-party apps ship a
    compiled Mach-O, or a wrapper pointing at another app in /Applications
    (the Google Docs/Sheets/Slides PWA shims, LibreOffice). Requiring both a
    shebang and a home-dir reference is what keeps scanning all of
    /Applications from dragging those into the registry.
    """
    macos = os.path.join(app, "Contents", "MacOS")
    if not os.path.isdir(macos):
        return ""
    for entry in sorted(os.listdir(macos)):
        path = os.path.join(macos, entry)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                if fh.read(2) != b"#!":
                    continue
            txt = open(path, errors="ignore").read()
        except OSError:
            continue
        if "$HOME" in txt or HOME in txt:
            return path
    return ""


def scan_apps():
    items = []
    for app in sorted(glob.glob(os.path.join(APPS_DIR, "*.app"))):
        name = os.path.basename(app)[:-4]
        launcher = script_launcher(app)
        if not launcher:
            continue
        port, repo_dir = "", ""
        txt = open(launcher, errors="ignore").read()
        m = re.search(r'^PORT=(\d+)', txt, re.M)
        if m:
            port = m.group(1)
        m = re.search(r'^DIR="?([^"\n]+)"?', txt, re.M)
        if m:
            repo_dir = m.group(1)
        items.append({
            "name": name, "category": "app", "port": port,
            "repo_dir": repo_dir, "launcher": launcher,
            "live": port_live(port),
        })
    return items


def schedule_str(plist):
    if "StartInterval" in plist:
        secs = plist["StartInterval"]
        return f"every {secs//3600}h" if secs >= 3600 else f"every {secs//60}m"
    cal = plist.get("StartCalendarInterval")
    if cal:
        cal = cal if isinstance(cal, list) else [cal]
        parts = []
        for c in cal:
            h, m = c.get("Hour"), c.get("Minute", 0)
            if h is not None:
                parts.append(f"{h:02d}:{m:02d}")
            elif "Weekday" in c:
                parts.append(f"wd{c['Weekday']}")
        return "daily " + ", ".join(parts) if parts else "calendar"
    if plist.get("RunAtLoad"):
        return "at load / KeepAlive"
    return "watch/triggered"


def scan_jobs(loaded):
    items = []
    for f in sorted(os.listdir(LAUNCHAGENTS)):
        if not f.endswith(".plist") or not f.startswith(JOB_PREFIXES):
            continue
        path = os.path.join(LAUNCHAGENTS, f)
        try:
            pl = plistlib.load(open(path, "rb"))
        except Exception:
            continue
        label = pl.get("Label", f[:-6])
        args = pl.get("ProgramArguments", [])
        script = next((a for a in args if a.startswith("/") and a.endswith((".py", ".sh"))), "")
        if not script and len(args) >= 2:
            script = args[-1]
        repo = find_repo_root(script) if script else ""
        items.append({
            "name": label, "category": "scheduled-job", "port": "",
            "repo_dir": repo, "launcher": script,
            "schedule": schedule_str(pl), "live": label in loaded,
        })
    return items


def scan_cli():
    """Executables in any ~/Documents project's bin/ dir -- our CLI entry points.

    Every MIST CLI (mist-say, mist-image, mist-progress, mist-eject, ...) ships as an
    executable in a repo's bin/, so this catches them without anyone maintaining a list.
    """
    items = []
    for dirpath, dirnames, _ in os.walk(PROJECTS_ROOT):
        depth = dirpath[len(PROJECTS_ROOT):].count(os.sep)
        if depth >= 3:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames
                       if d not in PRUNE and not d.startswith(".") and "venv" not in d]
        if os.path.basename(dirpath) != "bin":
            continue
        repo = find_repo_root(dirpath) or os.path.dirname(dirpath)
        for entry in sorted(os.listdir(dirpath)):
            path = os.path.join(dirpath, entry)
            if entry.startswith(".") or not os.path.isfile(path) or not os.access(path, os.X_OK):
                continue
            items.append({
                "name": entry, "category": "cli", "port": "",
                "repo_dir": repo, "launcher": path, "source": "built",
                "command": path.replace(HOME, "~"),
            })
    return items


def load_manual():
    """Hand-logged tools from cli-tools.json (see log-tool.py)."""
    try:
        entries = json.load(open(MANUAL_LOG))
    except Exception as e:
        print(f"WARN: could not read {MANUAL_LOG}: {e}")
        return []
    items = []
    for e in entries:
        repo = os.path.expanduser(e.get("repo_dir", "") or "")
        items.append({
            "name": e["name"], "category": e.get("category", "cli"), "port": "",
            "repo_dir": repo, "launcher": "", "command": e.get("command", ""),
            "source": e.get("source", "built"), "added": e.get("added", ""),
            "notes": e.get("notes", ""),
        })
    return items


def merge(*groups):
    """Concatenate scan results, first occurrence of a name wins."""
    out, seen = [], set()
    for group in groups:
        for item in group:
            key = item["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=90).stdout
    except Exception:
        return ""


def scan_dependencies():
    """Auto-discover the downloaded substrate: runtimes, brew, npm, pip, uv tools."""
    deps = []

    # Language runtimes
    for name, path, args in [
        ("Python (Homebrew)", HB_PY, ["--version"]),
        ("Node.js", "/opt/homebrew/bin/node", ["--version"]),
        ("npm", "/opt/homebrew/bin/npm", ["--version"]),
        ("OpenJDK 17", "/opt/homebrew/opt/openjdk@17/bin/java", ["--version"]),
        ("Ruby (system)", "/usr/bin/ruby", ["--version"]),
    ]:
        if os.path.exists(path):
            ver = run([path] + args).strip().splitlines()
            deps.append({"name": name, "kind": "runtime", "source": "homebrew/system",
                         "version": (ver[0] if ver else ""), "path": path})

    # Homebrew formulae (leaves only -- intentionally installed, not transitive deps)
    versions = {}
    for line in run([BREW, "list", "--versions"]).splitlines():
        parts = line.split()
        if parts:
            versions[parts[0]] = " ".join(parts[1:])
    for leaf in run([BREW, "leaves"]).split():
        deps.append({"name": leaf, "kind": "brew-formula", "source": "homebrew",
                     "version": versions.get(leaf, ""), "path": ""})

    # Homebrew casks
    for cask in run([BREW, "list", "--cask"]).split():
        deps.append({"name": cask, "kind": "brew-cask", "source": "homebrew",
                     "version": versions.get(cask, ""), "path": ""})

    # npm globals
    for line in run(["/opt/homebrew/bin/npm", "ls", "-g", "--depth=0"]).splitlines():
        m = re.search(r"([@\w/.-]+)@([\d.]+)\s*$", line.strip())
        if m and "node_modules" not in line:
            deps.append({"name": m.group(1), "kind": "npm-global", "source": "npm",
                         "version": m.group(2), "path": ""})

    # Global pip packages on the Homebrew python (where --break-system-packages installs land).
    # --not-required = top-level intentional installs only (the pip analog of `brew leaves`),
    # so transitive dependencies don't flood the registry.
    skip = {"pip", "setuptools", "wheel"}
    for line in run([HB_PY, "-m", "pip", "list", "--not-required"]).splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 2 and parts[0].lower() not in skip:
            note = ""
            if parts[0].lower() == "playwright":
                browsers = os.path.join(HOME, "Library", "Caches", "ms-playwright")
                if os.path.isdir(browsers):
                    note = "Browsers: " + ", ".join(sorted(os.listdir(browsers)))
            deps.append({"name": parts[0], "kind": "pip-global", "source": "pip (homebrew py)",
                         "version": parts[1], "path": "", "notes": note})

    # uv tools
    for line in run(["uv", "tool", "list"]).splitlines():
        m = re.match(r"^(\S+)\s+v([\d.]+)", line.strip())
        if m:
            deps.append({"name": m.group(1), "kind": "uv-tool", "source": "uv",
                         "version": m.group(2), "path": ""})

    return deps


def write_dep_note(item):
    fm = [
        "---",
        "type: dependency",
        f"kind: {item.get('kind')}",
        f"source: {yaml_str(item.get('source'))}",
        f"version: {yaml_str(item.get('version'))}",
        f"dep_path: {yaml_str(item.get('path'))}",
        "---",
    ]
    body = [item["notes"]] if item.get("notes") else []
    note = "\n".join(fm) + "\n" + "\n".join(body) + "\n"
    fn = ILLEGAL.sub(" ", item["name"]).strip()[:90] + ".md"
    open(os.path.join(VAULT_DEPS, fn), "w").write(note)


def yaml_str(v):
    if v is None or v == "":
        return '""'
    return '"' + str(v).replace('"', "'") + '"'


def write_note(item):
    name = item["name"]
    fm = [
        "---",
        "type: tool",
        f"category: {item.get('category')}",
        f"port: {item.get('port') or ''}",
        f"live: {str(item.get('live', False)).lower()}",
        f"repo_dir: {yaml_str(item.get('repo_dir'))}",
        f"repo_remote: {yaml_str(git_remote(item.get('repo_dir', '')))}",
        f"launcher: {yaml_str(item.get('launcher'))}",
        f"schedule: {yaml_str(item.get('schedule'))}",
        f"command: {yaml_str(item.get('command'))}",
        f"source: {yaml_str(item.get('source') or 'built')}",
        f"added: {yaml_str(item.get('added'))}",
        "---",
    ]
    body = []
    if item.get("notes"):
        body.append(item["notes"])
        body.append("")
    if item.get("command"):
        body.append(f"```\n{item['command']}\n```")
        body.append("")
    if item.get("port"):
        body.append(f"Local URL: http://localhost:{item['port']}/")
    note = "\n".join(fm) + "\n" + "\n".join(body) + "\n"
    fn = ILLEGAL.sub(" ", name).strip()[:90] + ".md"
    open(os.path.join(VAULT_FOLDER, fn), "w").write(note)


def parse_requirements(path):
    names = []
    for line in open(path, errors="ignore"):
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        name = re.split(r"[=<>!~;\[\s]", line, maxsplit=1)[0].strip()
        if name:
            names.append(name)
    return names


def parse_pyproject(path):
    try:
        import tomllib
        data = tomllib.load(open(path, "rb"))
    except Exception:
        return []
    deps = data.get("project", {}).get("dependencies", []) or []
    out = []
    for d in deps:
        m = re.match(r"[A-Za-z0-9_.-]+", d)
        if m:
            out.append(m.group(0))
    return out


def parse_package_json(path):
    try:
        data = json.load(open(path))
    except Exception:
        return []
    names = list((data.get("dependencies") or {}).keys())
    names += list((data.get("devDependencies") or {}).keys())
    return names


def venv_top_level(venv_python):
    out = run([venv_python, "-m", "pip", "list", "--not-required"])
    names = []
    for line in out.splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 2 and parts[0].lower() not in {"pip", "setuptools", "wheel"}:
            names.append(parts[0])
    return names


def find_project_roots():
    """Dirs under ~/Documents that declare dependencies (manifest or .venv), depth<=3."""
    roots = set()
    for dirpath, dirnames, filenames in os.walk(PROJECTS_ROOT):
        depth = dirpath[len(PROJECTS_ROOT):].count(os.sep)
        if depth >= 3:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if d not in PRUNE and not d.startswith(".")]
        if os.path.isdir(os.path.join(dirpath, ".venv")) or any(
            f in filenames for f in ("requirements.txt", "pyproject.toml", "package.json")
        ):
            roots.add(dirpath)
    return sorted(roots)


def scan_project_deps():
    projects = []
    for root in find_project_roots():
        deps, langs = [], set()
        venv_py = os.path.join(root, ".venv", "bin", "python")
        if os.path.exists(venv_py):
            deps += venv_top_level(venv_py)
            langs.add("python")
        elif os.path.isfile(os.path.join(root, "requirements.txt")):
            deps += parse_requirements(os.path.join(root, "requirements.txt"))
            langs.add("python")
        elif os.path.isfile(os.path.join(root, "pyproject.toml")):
            deps += parse_pyproject(os.path.join(root, "pyproject.toml"))
            langs.add("python")
        if os.path.isfile(os.path.join(root, "package.json")):
            deps += parse_package_json(os.path.join(root, "package.json"))
            langs.add("node")
        deps = sorted(set(deps), key=str.lower)
        if not deps:
            continue
        rel = os.path.relpath(root, PROJECTS_ROOT)
        projects.append({
            "name": rel.replace(os.sep, " -- "),
            "repo_remote": git_remote(root),
            "venv": ".venv" if os.path.exists(venv_py) else "",
            "language": "+".join(sorted(langs)),
            "dependencies": deps,
            "path": root,
        })
    return projects


def write_projdep_note(p):
    fm = [
        "---",
        "type: project-deps",
        f"project: {yaml_str(p['name'])}",
        f"language: {yaml_str(p['language'])}",
        f"dep_count: {len(p['dependencies'])}",
        f"venv: {yaml_str(p['venv'])}",
        f"repo_remote: {yaml_str(p.get('repo_remote'))}",
        f"proj_path: {yaml_str(p['path'])}",
        "dependencies:",
    ]
    fm += [f"  - {yaml_str(d)}" for d in p["dependencies"]]
    fm.append("---")
    body = ["Top-level dependencies: " + ", ".join(p["dependencies"])]
    note = "\n".join(fm) + "\n" + "\n".join(body) + "\n"
    fn = ILLEGAL.sub(" ", p["name"]).strip()[:90] + ".md"
    open(os.path.join(VAULT_PROJDEPS, fn), "w").write(note)


def wipe(folder):
    os.makedirs(folder, exist_ok=True)
    for fn in os.listdir(folder):
        if fn.endswith(".md"):
            os.remove(os.path.join(folder, fn))


def main():
    # Built tools (apps + scheduled jobs + cli)
    wipe(VAULT_FOLDER)
    loaded = loaded_labels()
    # Manual entries come first so a hand-written note wins over the bare bin/ discovery.
    items = merge(load_manual(), scan_apps(), scan_jobs(loaded), scan_cli())
    for it in items:
        write_note(it)
    apps = sum(1 for i in items if i["category"] == "app")
    jobs = sum(1 for i in items if i["category"] == "scheduled-job")
    clis = sum(1 for i in items if i["category"] == "cli")
    live = sum(1 for i in items if i.get("live"))
    print(f"Synced {len(items)} tools ({apps} apps, {jobs} jobs, {clis} cli) -> {VAULT_FOLDER}")
    print(f"Live right now: {live}")

    # Downloaded substrate (runtimes, brew, npm, pip, uv)
    wipe(VAULT_DEPS)
    deps = scan_dependencies()
    for d in deps:
        write_dep_note(d)
    by_kind = {}
    for d in deps:
        by_kind[d["kind"]] = by_kind.get(d["kind"], 0) + 1
    print(f"Synced {len(deps)} dependencies -> {VAULT_DEPS}")
    print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(by_kind.items())))

    # Per-project dependency stacks
    wipe(VAULT_PROJDEPS)
    projects = scan_project_deps()
    for p in projects:
        write_projdep_note(p)
    total_deps = sum(len(p["dependencies"]) for p in projects)
    print(f"Synced {len(projects)} project dependency stacks ({total_deps} deps) -> {VAULT_PROJDEPS}")


if __name__ == "__main__":
    main()
