#!/usr/bin/env python3
"""Scan the machine for every tool Alex has built and project them into Obsidian notes.

Single source of truth for "what have I made / installed." Auto-discovers from the two
authoritative on-disk sources, so it never drifts:

  1. App launchers  -> ~/Desktop/Apps/*.app  (parses Contents/MacOS/launch for DIR + PORT)
  2. Scheduled jobs -> ~/Library/LaunchAgents/{com.exobrain,com.mist,com.nightwatch,com.alexhedtke}*.plist

For each item it records repo dir, git remote, port, launcher/script, schedule, and LIVE
status (port listening / job loaded). Emits one note per tool into the vault "Tools/" folder,
which "Tools.base" renders. Idempotent: the folder is wiped and rewritten each run.

Known gap: CLI-only tools with no .app launcher and no launchd job (e.g. tv/tv,
imessage-reader) are not auto-discovered yet. Extend SUPPLEMENTAL below to include them.

Usage:  python3 tools-registry-scan.py
"""
import os
import re
import glob
import socket
import plistlib
import subprocess

HOME = os.path.expanduser("~")
APPS_DIR = os.path.join(HOME, "Desktop", "Apps")
LAUNCHAGENTS = os.path.join(HOME, "Library", "LaunchAgents")
JOB_PREFIXES = ("com.exobrain.", "com.mist.", "com.nightwatch.", "com.alexhedtke.")
VAULT_FOLDER = os.path.join(HOME, "Exobrain", "Tools")

ILLEGAL = re.compile(r'[\\/:#^\[\]|*?"<>]')

# CLI/other tools with no launcher and no launchd job — maintained by hand.
SUPPLEMENTAL = [
    {"name": "Samsung TV control (tv)", "category": "cli", "repo_dir": os.path.join(HOME, "Documents", "Exobrain harness", "tv"), "notes": "Local WSS control CLI for the living-room Samsung TV (tv/tv)."},
]


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


def scan_apps():
    items = []
    for app in sorted(glob.glob(os.path.join(APPS_DIR, "*.app"))):
        name = os.path.basename(app)[:-4]
        launcher = os.path.join(app, "Contents", "MacOS", "launch")
        port, repo_dir = "", ""
        if os.path.isfile(launcher):
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
        "---",
    ]
    body = []
    if item.get("notes"):
        body.append(item["notes"])
        body.append("")
    if item.get("port"):
        body.append(f"Local URL: http://localhost:{item['port']}/")
    note = "\n".join(fm) + "\n" + "\n".join(body) + "\n"
    fn = ILLEGAL.sub(" ", name).strip()[:90] + ".md"
    open(os.path.join(VAULT_FOLDER, fn), "w").write(note)


def main():
    os.makedirs(VAULT_FOLDER, exist_ok=True)
    for fn in os.listdir(VAULT_FOLDER):
        if fn.endswith(".md"):
            os.remove(os.path.join(VAULT_FOLDER, fn))

    loaded = loaded_labels()
    items = scan_apps() + scan_jobs(loaded) + SUPPLEMENTAL
    for it in items:
        write_note(it)

    apps = sum(1 for i in items if i["category"] == "app")
    jobs = sum(1 for i in items if i["category"] == "scheduled-job")
    live = sum(1 for i in items if i.get("live"))
    print(f"Synced {len(items)} tools ({apps} apps, {jobs} jobs, {len(SUPPLEMENTAL)} cli) -> {VAULT_FOLDER}")
    print(f"Live right now: {live}")


if __name__ == "__main__":
    main()
