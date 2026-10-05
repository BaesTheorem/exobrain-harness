#!/usr/bin/env python3
"""Free a busy external volume so it can eject, and watch for failed ejects.

Two modes:

    disk_eject.py free  [VOLUME] [--dry-run] [--no-eject]
    disk_eject.py watch

`free` is the one-shot worker: find what holds the volume, ask each holder to
quit the way it expects to be quit, wait for it, then eject. `watch` streams
diskarbitrationd and runs `free` whenever a Finder/diskutil eject fails with
EBUSY, so clicking the eject arrow is enough on its own.

Nothing here is ever forced. There is no `diskutil unmount force`, no SIGKILL,
and no flag that enables either: Finder already has a Force Eject button for
that, and a tool that forces behind your back is worse than the dialog it
replaces. When a holder will not quit, the volume stays mounted and the
notification names the holder.

How each holder is asked to quit depends on what it is:

  * A launchd job (the holder's pid is a job in the gui domain) is booted out,
    because KeepAlive would otherwise relaunch it the moment it exits, and the
    relaunch reopens the volume. launchd sends SIGTERM and applies the plist's
    ExitTimeOut. The job is bootstrapped again after the eject attempt, so its
    own RunAtLoad / StartOnMount / KeepAlive rules bring it back.
  * An app bundle gets an AppleScript `quit`, the same as Cmd-Q, so it can
    save state or ask about unsaved changes.
  * Anything else gets SIGTERM.

Before any of that, a per-app pre-stop hook can run (rqbit gets its torrents
paused so the session checkpoints).

Safety rails:

  * Internal and boot disks are refused outright. Only ejectable/external
    volumes mounted under /Volumes are ever touched.
  * Protected system processes (Spotlight, fseventsd, backupd, Finder) are
    never signalled; they release when diskarbitrationd asks them to.
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
LAUNCHCTL = "/bin/launchctl"
OSASCRIPT = "/usr/bin/osascript"
LSAPPINFO = "/usr/bin/lsappinfo"
PS = "/bin/ps"
LOG = "/usr/bin/log"
NOTIFY = os.path.join(os.path.dirname(HERE), "mist-voice", "bin", "mist-notify")
UID = os.getuid()
LAUNCHD_DEFAULT_EXIT_TIMEOUT = 20

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
    if not os.path.exists(NOTIFY) or os.environ.get("MIST_EJECT_NO_NOTIFY"):
        return
    try:
        subprocess.run([NOTIFY, msg, title, sound, link, "--discord"],
                       timeout=15, check=False)
    except Exception as exc:  # notification failure must never abort an eject
        say(f"notify failed: {exc}")


def run(cmd, timeout=30, merge=False):
    """Run a command, returning (rc, stdout). Never raises.

    merge=True folds stderr into the output, for tools that explain failures
    there (launchctl).
    """
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + (p.stderr if merge else "")
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
    """Processes with open files on the volume: {pid: command name}.

    Passing lsof a mount point makes it report the whole filesystem, which is
    both complete and fast. Walking the tree with +D would take minutes on a
    terabyte drive.
    """
    rc, out = run([LSOF, "-w", "-F", "pc", mount], timeout=90)
    procs = {}
    pid = None
    for line in out.splitlines():
        if not line:
            continue
        tag, val = line[0], line[1:]
        if tag == "p":
            pid = int(val)
            procs.setdefault(pid, "?")
        elif tag == "c" and pid is not None:
            procs[pid] = val
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


def is_protected(cmd, cfg):
    name = os.path.basename(cmd)
    for pat in cfg.get("protected_processes", []):
        if name == pat or name.startswith(pat):
            return True
    return False


def describe(procs):
    return ", ".join(f"{c}[{p}]" for p, c in sorted(procs.items()))


# --------------------------------------------------------------------------
# What kind of thing each holder is
# --------------------------------------------------------------------------

def launchd_jobs():
    """{pid: label} for every running job in this user's launchd domain."""
    rc, out = run([LAUNCHCTL, "list"])
    jobs = {}
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit():
            jobs[int(parts[0])] = parts[2]
    return jobs


def launchd_plist(label):
    """Path of the plist a loaded job came from, or None."""
    rc, out = run([LAUNCHCTL, "print", f"gui/{UID}/{label}"])
    m = re.search(r"^\s*path = (.+)$", out, re.M)
    return m.group(1).strip() if m else None


def launchd_exit_timeout(plist):
    """Seconds launchd waits after SIGTERM before it kills a job it is unloading."""
    if not plist:
        return LAUNCHD_DEFAULT_EXIT_TIMEOUT
    try:
        with open(plist, "rb") as fh:
            return int(plistlib.load(fh).get("ExitTimeOut", LAUNCHD_DEFAULT_EXIT_TIMEOUT))
    except Exception:
        return LAUNCHD_DEFAULT_EXIT_TIMEOUT


def bundle_id(pid):
    """CFBundleIdentifier when the process is a running GUI app, else None.

    LaunchServices is the instrument, not the executable path: Homebrew's
    python3 lives inside Python.app and still is not an app that answers Apple
    events. lsappinfo only knows processes that registered as applications.
    """
    rc, asn = run([LSAPPINFO, "find", f"pid={pid}"])
    asn = asn.strip()
    if rc != 0 or not asn:
        return None
    rc, out = run([LSAPPINFO, "info", "-only", "bundleid", asn])
    m = re.search(r'"CFBundleIdentifier"="([^"]+)"', out)
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# Asking holders to quit
# --------------------------------------------------------------------------

def ask_to_quit(pid, cmd, cfg, jobs, dry_run=False):
    """Run the pre-stop hook, then ask one holder to quit the way it expects.

    Returns (grace_seconds, launchd_job_to_restore). The job is a
    (label, plist_path) pair, or None when the holder is not a launchd job.
    """
    name = os.path.basename(cmd)
    handler = (cfg.get("graceful_handlers") or {}).get(name, {})
    wait = handler.get("wait", cfg.get("default_wait_seconds", 10))

    for pre in handler.get("pre", []):
        say(f"  {name}[{pid}]: pre-stop -> {pre}")
        if not dry_run:
            run(["/bin/sh", "-c", pre], timeout=handler.get("pre_timeout", 30))

    label = jobs.get(pid)
    if label:
        plist = launchd_plist(label)
        timeout = launchd_exit_timeout(plist)
        say(f"  {name}[{pid}]: launchd job {label}, bootout "
            f"(launchd sends SIGTERM, ExitTimeOut {timeout}s)")
        if timeout < wait:
            say(f"  {name}[{pid}]: WARNING launchd kills the job after {timeout}s, "
                f"inside the {wait}s grace period. Raise ExitTimeOut in {plist}.")
        if not dry_run:
            run([LAUNCHCTL, "bootout", f"gui/{UID}/{label}"])
        return wait, (label, plist)

    bid = bundle_id(pid)
    if bid:
        say(f"  {name}[{pid}]: app {bid}, AppleScript quit")
        if not dry_run:
            # A "save changes?" sheet blocks osascript; the timeout returns
            # control here and the app then shows up as a remaining holder.
            run([OSASCRIPT, "-e", f'tell application id "{bid}" to quit'], timeout=10)
        return wait, None

    say(f"  {name}[{pid}]: SIGTERM")
    if not dry_run:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            say(f"  {name}[{pid}]: no permission to signal")
    return wait, None


def restore_jobs(jobs, patience=90):
    """Load each booted-out launchd job again so its own rules take over.

    bootstrap answers EIO while launchd is still tearing down the previous
    instance (a slow quitter can take a while), so retry until the job loads
    or patience runs out. On the abort path the old process may still be alive
    for the whole of its ExitTimeOut; the reload command is printed then.
    """
    for label, plist in jobs:
        if not plist:
            say(f"  {label}: plist path unknown, not reloaded")
            continue
        end = time.time() + patience
        while True:
            rc, out = run([LAUNCHCTL, "bootstrap", f"gui/{UID}", plist], merge=True)
            if rc == 0:
                say(f"  {label}: bootstrapped again")
                break
            if time.time() >= end:
                say(f"  {label}: bootstrap failed ({out.strip().splitlines()[0][:80]}). "
                    f"Reload with: launchctl bootstrap gui/{UID} {plist}")
                break
            time.sleep(2)


# --------------------------------------------------------------------------
# Free, then eject
# --------------------------------------------------------------------------

def free_and_eject(target, dry_run=False, do_eject=True):
    """Free `target` and eject it. Returns (ok, summary)."""
    cfg = load_config()
    mount, whole, refusal = resolve_volume(target)
    if refusal:
        say(f"REFUSED: {refusal}")
        return False, refusal
    assert mount is not None
    name = os.path.basename(mount)

    say(f"Volume: {mount}  (whole disk {whole})")

    procs = holders(mount)
    if not procs:
        say("No holders.")
    else:
        say(f"{len(procs)} holder(s): {describe(procs)}")

    targets = []
    for pid, cmd in sorted(procs.items()):
        if is_protected(cmd, cfg):
            say(f"  {cmd}[{pid}]: protected, leaving alone")
        else:
            targets.append((pid, cmd))

    # Ask everything at once, then wait once. Waiting per process in sequence
    # would cost grace-period x holders, and a media drive can easily have
    # rqbit, Plex and a player on it at the same time.
    jobs = launchd_jobs()
    restore, deadline = [], 0
    for pid, cmd in targets:
        wait, job = ask_to_quit(pid, cmd, cfg, jobs, dry_run)
        deadline = max(deadline, wait)
        if job:
            restore.append(job)
    if targets and not dry_run and deadline:
        say(f"  waiting up to {deadline}s for {len(targets)} holder(s)")
        end = time.time() + deadline
        while time.time() < end:
            if not any(alive(p) for p, _ in targets):
                break
            time.sleep(0.5)

    if dry_run:
        return True, "dry run; nothing changed"

    # Look at the volume again rather than at the pids we asked: a relaunched
    # or newly started process is just as much a holder.
    remaining = {p: c for p, c in holders(mount).items() if not is_protected(c, cfg)}
    if remaining:
        who = describe(remaining)
        say(f"ABORT: still held by {who}. Leaving the volume mounted.")
        restore_jobs(restore)
        notify(f"{name} is still held by {who}. Quit it, then eject again.",
               "MIST", "Basso", "console")
        return False, f"still held by {who}"

    stopped = ", ".join(f"{c}[{p}]" for p, c in targets)
    if not do_eject:
        if restore:
            say("launchd jobs left unloaded (they would reopen the volume): "
                + ", ".join(label for label, _ in restore))
            for _label, plist in restore:
                say(f"  reload with: launchctl bootstrap gui/{UID} {plist}")
        return True, "holders released (eject skipped)"

    rc, out = run([DISKUTIL, "eject", whole], timeout=90)
    ok = rc == 0
    say(out.strip() or ("ejected" if ok else "eject failed"))
    restore_jobs(restore)

    if ok:
        detail = f" Stopped {stopped}." if stopped else ""
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
    assert proc.stdout is not None
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
            # Our own eject attempt can fail EBUSY too and log the same line;
            # count the debounce from the end of the run, not its start.
            last[dev] = time.time()
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
        if "--force" in rest:
            print("There is no --force. This tool never forces an unmount or kills "
                  "a process; use Finder's Force Eject if that is what you want.")
            return 2
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
            good, _ = free_and_eject(t, dry_run=dry, do_eject=not no_eject)
            ok = ok and good
        return 0 if ok else 1

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
