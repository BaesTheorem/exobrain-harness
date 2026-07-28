#!/usr/bin/env python3
"""Free a busy external volume so it can eject, and watch for failed ejects.

Two modes:

    disk_eject.py free  [VOLUME] [--force] [--dry-run] [--no-eject]
    disk_eject.py watch

`free` is the one-shot worker: find what holds the volume, stop it by the
gentlest means that works, then eject. `watch` streams diskarbitrationd and
runs `free` whenever a Finder/diskutil eject fails with EBUSY, so clicking the
eject arrow is enough on its own.

Safety rails, in order of how much they matter:

  * Internal and boot disks are refused outright. Only ejectable/external
    volumes mounted under /Volumes are ever touched.
  * Protected system processes (Spotlight, fseventsd, backupd, Finder) are
    never signalled. They release on their own once a forced unmount lands.
  * Nothing is ever SIGKILLed unless you ask for it with --force. A holder that
    ignores SIGTERM is handled with `diskutil unmount force`, which flushes the
    filesystem and revokes the handles without destroying whatever the app was
    holding in memory.

A note on what is deliberately absent: an earlier version tried to detect
"is this process mid-write?" so it could force-kill only idle holders. Two
instruments were tried and both failed -- open-file offset deltas miss
in-place/random-offset writes (exactly how rqbit writes torrent pieces), and
proc_pid_rusage disk counters stay flat because buffered writes are accounted
to writeback, not the process. Rather than ship a guard that silently fails
open, the escalation simply stops short of SIGKILL.
"""

import json
import os
import plistlib
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

LSOF = "/usr/sbin/lsof"
DISKUTIL = "/usr/sbin/diskutil"
LOG = "/usr/bin/log"
NOTIFY = os.path.join(os.path.dirname(HERE), "mist-voice", "bin", "mist-notify")

# `unable to unmount /dev/disk5s1 (status code 0x00000010).`
UNMOUNT_FAIL = re.compile(
    r"unable to unmount (/dev/disk\S+?) \(status code (0x[0-9a-fA-F]+)\)"
)
EBUSY = 0x10


def load_config():
    with open(CONFIG_PATH) as fh:
        return json.load(fh)


def say(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def notify(msg, title="MIST", sound="Purr", link="console"):
    if not os.path.exists(NOTIFY):
        return
    try:
        subprocess.run([NOTIFY, msg, title, sound, link], timeout=15, check=False)
    except Exception as exc:  # notification failure must never abort an eject
        say(f"notify failed: {exc}")


def run(cmd, timeout=30):
    """Run a command, returning (rc, stdout). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except Exception as exc:
        return 1, str(exc)


# --------------------------------------------------------------------------
# Volume identification and safety gate
# --------------------------------------------------------------------------

def disk_info(dev):
    """diskutil info for a device or mount point, as a dict (empty on failure)."""
    rc, out = run([DISKUTIL, "info", "-plist", dev])
    if rc != 0 or not out:
        return {}
    try:
        return plistlib.loads(out.encode())
    except Exception:
        return {}


def parent_disk(dev):
    """/dev/disk5s1 -> disk5 (the whole device you actually eject).

    Strips every trailing slice, not just one: the boot volume is a nested APFS
    snapshot (disk3s1s1) and must reduce to disk3 for the boot-disk check.
    """
    base = dev.rsplit("/", 1)[-1]
    while re.search(r"s\d+$", base):
        base = re.sub(r"s\d+$", "", base)
    return base


def boot_whole_disk():
    """Whole device backing /. Nothing on it may ever be touched."""
    info = disk_info("/")
    return parent_disk(info.get("DeviceIdentifier", "")) if info else ""


def resolve_volume(target):
    """Map a device node, mount point, or volume name to a vetted volume.

    Returns (mount_point, whole_disk, reason_refused). Refuses anything that is
    not an external, ejectable volume under /Volumes.
    """
    info = disk_info(target)
    if not info:
        return None, None, f"diskutil does not recognize {target!r}"

    mount = info.get("MountPoint") or ""
    whole = parent_disk(info.get("DeviceIdentifier", target))

    # Checked before anything else: the boot device is off limits whatever its
    # volumes claim about themselves or wherever they appear to be mounted.
    boot = boot_whole_disk()
    if boot and whole == boot:
        return None, whole, f"refusing {target!r}: lives on the boot disk ({boot})"

    if not mount:
        return None, whole, f"{target} is not mounted"
    if mount == "/" or mount.startswith("/System") or not mount.startswith("/Volumes/"):
        return None, whole, f"refusing {mount!r}: not an external volume"
    if info.get("Internal") is True and not info.get("Ejectable"):
        return None, whole, f"refusing {mount!r}: internal, non-ejectable disk"
    if info.get("Ejectable") is False and info.get("Removable") is False:
        return None, whole, f"refusing {mount!r}: not ejectable"

    cfg = load_config()
    allow = cfg.get("volume_allowlist") or []
    if allow and os.path.basename(mount) not in allow:
        return None, whole, f"{mount!r} is not in volume_allowlist"

    return mount, whole, None


# --------------------------------------------------------------------------
# Who is holding the volume
# --------------------------------------------------------------------------

def holders(mount):
    """Processes with open files on the volume: {pid: {"cmd", "fds"}}.

    Passing lsof a mount point makes it report the whole filesystem, which is
    both complete and fast. Walking the tree with +D would take minutes on a
    terabyte drive.
    """
    rc, out = run([LSOF, "-w", "-o", "-F", "pcfo", mount], timeout=90)
    procs = {}
    pid = cmd = fd = None
    for line in out.splitlines():
        if not line:
            continue
        tag, val = line[0], line[1:]
        if tag == "p":
            pid, cmd = int(val), None
            procs.setdefault(pid, {"cmd": "?", "fds": {}})
        elif tag == "c" and pid is not None:
            cmd = val
            procs[pid]["cmd"] = cmd
        elif tag == "f" and pid is not None:
            fd = val
        elif tag == "o" and pid is not None and fd is not None:
            procs[pid]["fds"][fd] = val  # file offset, e.g. "0t12345"
    procs.pop(os.getpid(), None)
    return procs


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


# --------------------------------------------------------------------------
# Stopping holders
# --------------------------------------------------------------------------

def is_protected(cmd, cfg):
    name = os.path.basename(cmd)
    for pat in cfg.get("protected_processes", []):
        if name == pat or name.startswith(pat):
            return True
    return False


def send_term(pid, cmd, cfg, dry_run=False):
    """Run any pre-stop hook and SIGTERM one holder. Returns its grace period."""
    name = os.path.basename(cmd)
    handler = (cfg.get("graceful_handlers") or {}).get(name, {})
    wait = handler.get("wait", cfg.get("default_wait_seconds", 10))

    for pre in handler.get("pre", []):
        say(f"  {name}[{pid}]: pre-stop -> {pre}")
        if not dry_run:
            run(["/bin/sh", "-c", pre], timeout=handler.get("pre_timeout", 30))

    say(f"  {name}[{pid}]: SIGTERM")
    if dry_run:
        return wait
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        say(f"  {name}[{pid}]: no permission to signal")
    return wait


def force_stop(pid, cmd, dry_run=False):
    name = os.path.basename(cmd)
    say(f"  {name}[{pid}]: SIGKILL")
    if dry_run:
        return True
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    for _ in range(20):
        if not alive(pid):
            return True
        time.sleep(0.25)
    return not alive(pid)


# --------------------------------------------------------------------------
# The release ladder
# --------------------------------------------------------------------------

def free_and_eject(target, force=False, dry_run=False, do_eject=True):
    """Free `target` and eject it. Returns (ok, summary)."""
    cfg = load_config()
    mount, whole, refusal = resolve_volume(target)
    if refusal:
        say(f"REFUSED: {refusal}")
        return False, refusal

    say(f"Volume: {mount}  (whole disk {whole})")

    procs = holders(mount)
    if not procs:
        say("No holders.")
    else:
        say(f"{len(procs)} holder(s): " + ", ".join(
            f"{i['cmd']}[{p}]" for p, i in sorted(procs.items())))

    # Signal everything first, then wait once. Waiting per-process in sequence
    # would cost grace-period x holders, and a media drive can easily have
    # rqbit, Plex and a player on it at the same time.
    targets, skipped = [], []
    for pid, info in sorted(procs.items()):
        cmd = info["cmd"]
        if is_protected(cmd, cfg):
            say(f"  {cmd}[{pid}]: protected, leaving alone")
            skipped.append(f"{cmd}[{pid}]")
        else:
            targets.append((pid, cmd))

    stopped, stubborn = [], []
    if targets:
        deadline = 0
        for pid, cmd in targets:
            wait = send_term(pid, cmd, cfg, dry_run)
            deadline = max(deadline, wait)
        if not dry_run and deadline:
            say(f"  waiting up to {deadline}s for {len(targets)} holder(s)")
            end = time.time() + deadline
            while time.time() < end:
                if not any(alive(p) for p, _ in targets):
                    break
                time.sleep(0.5)

        for pid, cmd in targets:
            if dry_run or not alive(pid):
                stopped.append(f"{cmd}[{pid}]")
                continue
            # Ignored SIGTERM. We do NOT reach for SIGKILL here: a forced
            # unmount gets the disk off just as well, flushes the filesystem,
            # and leaves the app alive to report an error instead of losing
            # its in-flight state. SIGKILL stays behind --force.
            if force:
                if force_stop(pid, cmd, dry_run):
                    stopped.append(f"{cmd}[{pid}] (SIGKILL)")
                else:
                    stubborn.append(f"{cmd}[{pid}]")
            else:
                say(f"  {cmd}[{pid}]: ignored SIGTERM, leaving it to forced unmount")
                stubborn.append(f"{cmd}[{pid}]")

    if dry_run:
        return True, "dry run; nothing changed"
    if not do_eject:
        return True, "holders released (eject skipped)"

    # Forced unmount is the OS's own way to take a volume from a process that
    # won't let go. It flushes and invalidates cleanly, so it is the right rung
    # between "asked nicely" and "killed it".
    if holders(mount):
        say("Holders remain; forcing the unmount.")
        run([DISKUTIL, "unmount", "force", mount], timeout=60)

    rc, out = run([DISKUTIL, "eject", whole], timeout=90)
    if rc != 0:
        run([DISKUTIL, "unmount", "force", mount], timeout=60)
        rc, out = run([DISKUTIL, "eject", whole], timeout=90)
    ok = rc == 0
    say(out.strip() or ("ejected" if ok else "eject failed"))

    if not ok and stubborn:
        msg = ("could not release: " + ", ".join(stubborn)
               + " (re-run with --force to SIGKILL)")
        say(f"ABORT: {msg}")
        notify(f"Eject blocked by {', '.join(stubborn)}. Ask MIST to force it.",
               "MIST", "Basso", "console")
        return False, msg

    name = os.path.basename(mount)
    if ok:
        detail = f" Stopped {', '.join(stopped)}." if stopped else ""
        notify(f"{name} ejected, safe to unplug.{detail}", "MIST", "Purr", "console")
        return True, f"ejected {name}"
    notify(f"{name} still won't eject: {out.strip()[:120]}", "MIST", "Basso", "console")
    return False, out.strip()


# --------------------------------------------------------------------------
# Watch mode
# --------------------------------------------------------------------------

def watch():
    cfg = load_config()
    debounce = cfg.get("debounce_seconds", 30)
    last = {}

    cmd = [
        LOG, "stream", "--style", "compact",
        "--predicate",
        'process == "diskarbitrationd" AND eventMessage CONTAINS "unable to unmount"',
    ]
    say("watching diskarbitrationd for failed ejects")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    try:
        for line in proc.stdout:
            m = UNMOUNT_FAIL.search(line)
            if not m:
                continue
            dev, code = m.group(1), int(m.group(2), 16)
            if code != EBUSY:
                say(f"{dev}: unmount failed with {hex(code)}, not busy -- ignoring")
                continue

            now = time.time()
            if now - last.get(dev, 0) < debounce:
                continue  # Finder retries several times per click
            last[dev] = now

            say(f"{dev} is busy; releasing")
            mount, whole, refusal = resolve_volume(dev)
            if refusal:
                say(f"skip: {refusal}")
                continue
            ok, summary = free_and_eject(dev)
            say(f"result: {summary}")
    finally:
        proc.terminate()


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    mode, rest = args[0], args[1:]

    if mode == "watch":
        watch()
        return 0

    if mode == "free":
        force = "--force" in rest
        dry = "--dry-run" in rest
        no_eject = "--no-eject" in rest
        targets = [a for a in rest if not a.startswith("--")]
        if not targets:
            cfg = load_config()
            targets = [os.path.join("/Volumes", v)
                       for v in (cfg.get("volume_allowlist") or [])
                       if os.path.ismount(os.path.join("/Volumes", v))]
            if not targets:
                targets = [os.path.join("/Volumes", d)
                           for d in sorted(os.listdir("/Volumes"))
                           if os.path.ismount(os.path.join("/Volumes", d))
                           and d != "Macintosh HD"]
        if not targets:
            print("No external volume mounted.")
            return 1
        ok = True
        for t in targets:
            good, _ = free_and_eject(t, force=force, dry_run=dry,
                                     do_eject=not no_eject)
            ok = ok and good
        return 0 if ok else 1

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
