"""Keep the newest Kiwix ZIM dumps (Wikipedia, WikiMed) on the external SSD.

For each book in config.json: read the mirror's folder listing, pick the newest
<name>_YYYY-MM.zim, and if the SSD does not hold that version yet, download it
with aria2c from the mirror's metalink (multi-mirror, resumable, piece hashes
checked as it goes). Then hash the whole file again with SHA-256 against the
metalink, move it into place, and only after that delete the older version.

launchd runs this on every mount (StartOnMount) and weekly. Without the volume
it exits 0 at once.

INVARIANTS:
- An old dump is deleted only after its replacement passed the SHA-256 check
  and sits at its final path. A reader always has one complete dump.
- Unfinished downloads live in <dest>/.partial and are never served.
- No volume, no work, exit 0. A missing disk is the normal state.
- A FAT32 (msdos) volume is refused: it cannot hold a file over 4 GB.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"
NOTIFY = HERE.parent / "mist-voice" / "bin" / "mist-notify"
LOCK = Path("/tmp/kiwix-sync.lock")
ARIA2C = shutil.which("aria2c") or "/opt/homebrew/bin/aria2c"
UA = "kiwix-sync/1.0 (personal offline mirror)"
META4_NS = {"m": "urn:ietf:params:xml:ns:metalink"}
WARN_REPEAT_S = 24 * 3600


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def versions_in_listing(html: str, name: str) -> list[str]:
    """All YYYY-MM versions of <name> in a mirror folder listing, oldest first."""
    pat = re.compile(re.escape(name) + r"_(\d{4}-\d{2})\.zim(?![.\w])")
    return sorted(set(pat.findall(html)))


def parse_meta4(xml_bytes: bytes) -> tuple[int, str]:
    """(size in bytes, sha-256 hex) from a metalink4 document."""
    root = ET.fromstring(xml_bytes)
    f = root.find("m:file", META4_NS)
    if f is None:
        raise ValueError("metalink has no <file>")
    size_el = f.find("m:size", META4_NS)
    sha = next((h.text for h in f.findall("m:hash", META4_NS) if h.get("type") == "sha-256"), None)
    if size_el is None or not size_el.text or not sha:
        raise ValueError("metalink lacks size or sha-256")
    return int(size_el.text), sha.strip().lower()


def local_versions(dest: Path, name: str) -> list[str]:
    pat = re.compile(re.escape(name) + r"_(\d{4}-\d{2})\.zim$")
    return sorted(m.group(1) for p in dest.glob(f"{name}_*.zim") if (m := pat.match(p.name)))


def fs_type(mount_point: Path) -> str | None:
    out = subprocess.run(["/sbin/mount"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if f" on {mount_point} (" in line:
            return line.split(f" on {mount_point} (", 1)[1].split(",", 1)[0]
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(8 << 20):
            h.update(chunk)
    return h.hexdigest()


class State:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("books", {})
        self.data.setdefault("warned", {})

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True))
        tmp.replace(self.path)

    def should_warn(self, key: str) -> bool:
        last = self.data["warned"].get(key, 0)
        if time.time() - last < WARN_REPEAT_S:
            return False
        self.data["warned"][key] = time.time()
        return True


def notify(msg: str, link: str = "console", context: str = "") -> None:
    if os.environ.get("KIWIX_SYNC_NO_NOTIFY"):
        log(f"(notify suppressed) {msg}")
        return
    cmd = [str(NOTIFY), msg, "Offline library", "none", link,
           "--discord", "--group", "offline-library"]
    if context:
        cmd += ["--context", context]
    subprocess.run(cmd, check=False)


def download(meta4_url: str, partial: Path) -> int:
    """aria2c from the metalink into .partial; returns aria2c's exit code."""
    cmd = [
        "/usr/bin/caffeinate", "-i", ARIA2C,
        "--follow-metalink=mem", "--metalink-preferred-protocol=https",
        f"--dir={partial}", "--continue=true", "--auto-file-renaming=false",
        "--allow-overwrite=false", "--file-allocation=none",
        "--split=8", "--max-connection-per-server=4", "--min-split-size=64M",
        "--max-tries=20", "--retry-wait=30", "--timeout=60",
        "--summary-interval=300", "--console-log-level=warn",
        f"--user-agent={UA}", meta4_url,
    ]
    log("running: " + " ".join(cmd[2:]))
    return subprocess.run(cmd).returncode


def sync_book(book: dict, cfg: dict, dest: Path, state: State, dry_run: bool) -> str:
    """Returns 'current', 'updated', 'skipped' or 'failed'."""
    name, folder = book["name"], book["dir"]
    base = f"{cfg['mirror'].rstrip('/')}/{folder}/"
    remote = versions_in_listing(fetch(base).decode("utf-8", "replace"), name)
    if not remote:
        log(f"{name}: no versions on the mirror at {base}")
        if state.should_warn(f"missing:{name}"):
            notify(f"Kiwix sync found no {name} files on the mirror. Check the name in offline-library/config.json.", base)
        return "failed"
    newest = remote[-1]
    have = local_versions(dest, name)
    filename = f"{name}_{newest}.zim"
    if newest in have:
        log(f"{name}: {newest} is current")
        return "current"

    size, sha = parse_meta4(fetch(base + filename + ".meta4"))
    partial = dest / ".partial"
    part_file = partial / filename
    have_bytes = part_file.stat().st_size if part_file.exists() else 0
    need = size - have_bytes + cfg.get("min_free_margin_gb", 5) * 2**30
    free = shutil.disk_usage(dest).free
    log(f"{name}: newest {newest} ({size / 2**30:.1f} GiB), local {have or 'none'}, "
        f"free {free / 2**30:.1f} GiB, need {need / 2**30:.1f} GiB")
    if free < need:
        if state.should_warn(f"space:{filename}"):
            notify(f"Kiwix sync cannot get {filename}: it needs {need / 2**30:.0f} GiB and "
                   f"{cfg['volume']} has {free / 2**30:.0f} GiB free. Free some space or remove "
                   f"the book from offline-library/config.json.",
                   context=f"local versions: {have}; dest: {dest}")
        return "skipped"
    if dry_run:
        log(f"{name}: would download {filename}")
        return "skipped"

    partial.mkdir(exist_ok=True)
    rc = download(base + filename + ".meta4", partial)
    if rc != 0 or not part_file.exists():
        log(f"{name}: aria2c exit {rc}; the next run resumes")
        if rc != 7 and state.should_warn(f"aria2:{filename}"):  # 7 = stopped by signal
            notify(f"Kiwix sync: the download of {filename} failed (aria2c exit {rc}). It resumes on the next run.",
                   context="log: ~/Library/Logs/exobrain/kiwix-sync.log")
        return "failed"

    log(f"{name}: verifying SHA-256 of {part_file.stat().st_size} bytes")
    got = sha256_file(part_file)
    if got != sha or part_file.stat().st_size != size:
        log(f"{name}: HASH MISMATCH got {got} want {sha}; deleting the partial file")
        part_file.unlink(missing_ok=True)
        (partial / (filename + ".aria2")).unlink(missing_ok=True)
        notify(f"Kiwix sync: {filename} failed its SHA-256 check and was deleted. The next run downloads it again.")
        return "failed"

    final = dest / filename
    part_file.replace(final)
    (partial / (filename + ".aria2")).unlink(missing_ok=True)
    log(f"{name}: {filename} verified and in place")
    for old in have:
        (dest / f"{name}_{old}.zim").unlink(missing_ok=True)
        log(f"{name}: removed old version {old}")
    state.data["books"][name] = {"version": newest, "sha256": sha, "size": size,
                                 "verified_at": datetime.now().isoformat(timespec="seconds")}
    notify(f"Kiwix sync: {filename} ({size / 2**30:.0f} GiB) is on {cfg['volume']} and passed its SHA-256 check.",
           str(dest))
    return "updated"


def main() -> int:
    ap = argparse.ArgumentParser(description="Keep the newest Kiwix ZIM dumps on the external SSD.")
    ap.add_argument("--dry-run", action="store_true", help="check the mirror and space, download nothing")
    ap.add_argument("--force", action="store_true", help="ignore the check_every_hours limit")
    ap.add_argument("--status", action="store_true", help="print the local state and exit")
    args = ap.parse_args()

    cfg = json.loads(CONFIG.read_text())
    vol = Path("/Volumes") / cfg["volume"]
    if not vol.is_dir():
        if args.status or args.dry_run:
            log(f"{vol} is not mounted")
        return 0
    if os.path.ismount(vol) is False:
        log(f"{vol} exists but is not a mount point; refusing")
        return 0
    if fs_type(vol) == "msdos":
        log(f"{vol} is FAT32; a ZIM file over 4 GB cannot go there")
        return 1

    dest = vol / cfg["dest_dir"]
    dest.mkdir(exist_ok=True)
    state = State(dest / ".kiwix-sync.json")

    if args.status:
        for book in cfg["books"]:
            log(f"{book['name']}: local {local_versions(dest, book['name']) or 'none'}")
        for p in sorted((dest / ".partial").glob("*.zim")):
            log(f"partial: {p.name} {p.stat().st_size / 2**30:.1f} GiB")
        return 0

    lock_fh = LOCK.open("w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another kiwix-sync is running")
        return 0

    unfinished = any((dest / ".partial").glob("*.aria2"))
    age_h = (time.time() - state.data.get("last_check", 0)) / 3600
    if not (args.force or args.dry_run or unfinished) and age_h < cfg.get("check_every_hours", 20):
        log(f"checked {age_h:.1f} h ago; next check after {cfg.get('check_every_hours', 20)} h")
        return 0

    results = {}
    for book in cfg["books"]:
        try:
            results[book["name"]] = sync_book(book, cfg, dest, state, args.dry_run)
        except Exception as exc:  # noqa: BLE001 - one bad book must not stop the next
            log(f"{book['name']}: error {exc!r}")
            results[book["name"]] = "failed"
            if state.should_warn(f"error:{book['name']}"):
                notify(f"Kiwix sync error on {book['name']}: {exc}",
                       context="log: ~/Library/Logs/exobrain/kiwix-sync.log")
    if not args.dry_run:
        if "failed" not in results.values():
            state.data["last_check"] = time.time()
        state.save()
    log(f"done: {results}")
    return 0 if "failed" not in results.values() else 1


if __name__ == "__main__":
    sys.exit(main())
