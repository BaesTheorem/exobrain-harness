#!/usr/bin/python3
"""Memory watchdog for the 8GB MacBook Air.

A runaway process (usually one of the pywebview/Flask fleet apps leaking in its
WKWebView frontend over multi-day uptime) can crawl to tens of GB, exhaust the
8GB of physical RAM, thrash swap, and freeze the whole machine hard enough to
need a power-button reboot. macOS does not always jetsam-kill it in time, and a
hard freeze eats the unified log before any crash report is written, so we never
learn which process did it.

This daemon runs every CHECK_SECS, logs the top processes by resident memory,
warns when any single process crosses WARN_GB, and (if it stays high for
SUSTAINED_CHECKS consecutive reads) kills anything over KILL_GB that is not on
the protected list. The point is twofold: catch the machine before it dies, and
record the exact offender's name + command so the guessing ends.

Stdlib only, system python (3.9). No third-party deps so launchd never breaks on
a missing venv.
"""
import os
import shutil
import signal
import subprocess
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# --- tunables (override via env) -------------------------------------------
CHECK_SECS = float(os.environ.get("MEMWD_CHECK_SECS", "20"))
WARN_GB = float(os.environ.get("MEMWD_WARN_GB", "5.0"))      # notify at this footprint
KILL_GB = float(os.environ.get("MEMWD_KILL_GB", "12.0"))     # auto-kill above this
EMERGENCY_GB = float(os.environ.get("MEMWD_EMERGENCY_GB", "16.0"))  # kill on FIRST read above this
SWAP_WARN_GB = float(os.environ.get("MEMWD_SWAP_WARN_GB", "5.5"))   # notify when swap used exceeds this
SUSTAINED_CHECKS = int(os.environ.get("MEMWD_SUSTAINED", "2"))  # consecutive reads over KILL_GB before killing
TOP_N = int(os.environ.get("MEMWD_TOP_N", "5"))             # how many to log each tick
WARN_THROTTLE_SECS = float(os.environ.get("MEMWD_WARN_THROTTLE", "600"))  # re-warn per pid at most this often
AUTO_KILL = os.environ.get("MEMWD_AUTO_KILL", "1") != "0"   # set 0 to warn-only
LOG_MAX_BYTES = int(os.environ.get("MEMWD_LOG_MAX", str(5 * 1024 * 1024)))

LOG_FILE = os.path.join(HERE, "mem-watchdog.log")
EVENT_FILE = os.path.join(HERE, "events.log")

# Never kill these no matter how big (substring match on comm/command).
PROTECTED = (
    "kernel_task", "launchd", "WindowServer", "loginwindow", "logind",
    "Finder", "Dock", "SystemUIServer", "coreaudiod", "mds", "mds_stores",
    "mem-watchdog", "syspolicyd", "opendirectoryd", "configd", "powerd",
)

_own_pid = os.getpid()
_last_warn = {}          # pid -> last warn epoch
_over_kill_streak = {}   # pid -> consecutive checks over KILL_GB


def _rotate(path):
    try:
        if os.path.getsize(path) > LOG_MAX_BYTES:
            os.replace(path, path + ".1")
    except OSError:
        pass


def _log(path, line):
    _rotate(path)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(path, "a", buffering=1) as fh:
            fh.write("{} {}\n".format(stamp, line))
    except OSError:
        pass


def _notify(title, message):
    # Visual + audible alert. Prefer a CLICKABLE terminal-notifier banner that
    # opens Activity Monitor (where Alex can spot the memory hog). Fall back to
    # osascript -- dependency-free and always present -- if it's missing; a
    # memory leak about to kill the machine is worth a sound either way.
    safe_msg = message.replace('"', "'")
    safe_title = title.replace('"', "'")
    tn = shutil.which("terminal-notifier") or "/opt/homebrew/bin/terminal-notifier"
    fired = False
    try:
        if os.path.exists(tn):
            subprocess.run(
                [tn, "-title", safe_title, "-message", safe_msg,
                 "-execute", "open -a 'Activity Monitor'", "-sound", "Basso"],
                check=False, timeout=10,
            )
            fired = True
    except Exception:
        pass
    if not fired:
        try:
            subprocess.run(
                ["osascript", "-e",
                 'display notification "{}" with title "{}" sound name "Basso"'
                 .format(safe_msg, safe_title)],
                check=False, timeout=10,
            )
        except Exception:
            pass
    # Best-effort MIST voice if the harness notifier is on PATH (silent fallback baked in).
    mist = os.path.expanduser("~/Documents/Exobrain harness/mist-voice/bin/mist-notify")
    if os.path.exists(mist):
        try:
            subprocess.run([mist, message, "MIST URGENT", "Basso"], check=False, timeout=15)
        except Exception:
            pass


def _top_mem_gb():
    """Per-pid memory from `top` (tracks phys footprint incl. COMPRESSED pages).

    ps RSS only counts resident uncompressed pages, so a leaking process whose
    stale garbage gets compressed can reach tens of GB of real footprint while
    RSS stays under 1GB -- exactly how the 2026-08-14 34GB MIST Console balloon
    slid past every RSS-based tick. top's MEM column matches Activity Monitor's
    Memory column closely (validated against /usr/bin/footprint) and covers all
    processes in one unprivileged call.
    """
    out = subprocess.run(
        ["top", "-l", "1", "-o", "mem", "-n", "30", "-stats", "pid,mem,command"],
        capture_output=True, text=True, check=False, timeout=30,
    ).stdout
    mem = {}
    mult = {"K": 1.0 / (1024 * 1024), "M": 1.0 / 1024, "G": 1.0, "B": 1.0 / (1024 ** 3)}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        raw = parts[1].rstrip("+-")
        if not raw or raw[-1] not in mult:
            continue
        try:
            mem[int(parts[0])] = float(raw[:-1]) * mult[raw[-1]]
        except ValueError:
            continue
    return mem


def swap_used_gb():
    out = subprocess.run(["sysctl", "-n", "vm.swapusage"],
                         capture_output=True, text=True, check=False).stdout
    # "total = 7168.00M  used = 6005.06M  free = 1162.94M  (encrypted)"
    try:
        used = out.split("used =")[1].split()[0]
        val = float(used.rstrip("MG"))
        return val / 1024.0 if used.endswith("M") else val
    except (IndexError, ValueError):
        return 0.0


def snapshot():
    """Return list of (pid, gb, comm, metric) sorted desc by max(rss, footprint)."""
    out = subprocess.run(
        ["ps", "-axo", "pid=,rss=,comm="],
        capture_output=True, text=True, check=False,
    ).stdout
    rss = {}
    comms = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            rss[pid] = int(parts[1]) / 1024.0 / 1024.0
        except ValueError:
            continue
        comms[pid] = parts[2]
    try:
        topmem = _top_mem_gb()
    except Exception:
        topmem = {}
    rows = []
    for pid, gb in rss.items():
        fp = topmem.get(pid, 0.0)
        if fp > gb:
            rows.append((pid, fp, comms.get(pid, "?"), "footprint"))
        else:
            rows.append((pid, gb, comms.get(pid, "?"), "rss"))
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows


def full_command(pid):
    out = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    return out[:300]


def is_protected(comm, cmd):
    blob = (comm + " " + cmd).lower()
    return any(p.lower() in blob for p in PROTECTED)


def kill(pid, label):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        _log(EVENT_FILE, "KILL-DENIED pid={} {} (not permitted)".format(pid, label))
        return
    for _ in range(10):
        time.sleep(1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            _log(EVENT_FILE, "KILLED pid={} {} (SIGTERM)".format(pid, label))
            return
    try:
        os.kill(pid, signal.SIGKILL)
        _log(EVENT_FILE, "KILLED pid={} {} (SIGKILL after grace)".format(pid, label))
    except ProcessLookupError:
        _log(EVENT_FILE, "KILLED pid={} {} (gone before SIGKILL)".format(pid, label))


_last_swap_warn = [0.0]


def tick():
    rows = snapshot()
    if not rows:
        return
    top = rows[:TOP_N]
    _log(LOG_FILE, "top: " + " | ".join(
        "{:.1f}G[{}] {}({})".format(gb, metric[0], comm, pid)
        for pid, gb, comm, metric in top))

    now = time.time()
    swap = swap_used_gb()
    if swap >= SWAP_WARN_GB and now - _last_swap_warn[0] >= 3600:
        _last_swap_warn[0] = now
        _log(EVENT_FILE, "SWAP-HIGH {:.1f}GB used; top: ".format(swap) + " | ".join(
            "{:.1f}G[{}] {}({})".format(gb, metric[0], comm, pid)
            for pid, gb, comm, metric in top))
        _notify("MIST: memory watchdog",
                "Swap is at {:.0f}GB; the machine is under memory pressure".format(swap))

    seen_pids = set()
    for pid, gb, comm, metric in rows:
        if pid == _own_pid:
            continue
        if gb < WARN_GB:
            break  # rows are sorted desc; nothing below this matters
        seen_pids.add(pid)
        cmd = full_command(pid)
        label = "{} {}={:.1f}GB cmd={}".format(comm, metric, gb, cmd)

        if gb >= KILL_GB:
            _over_kill_streak[pid] = _over_kill_streak.get(pid, 0) + 1
            streak = _over_kill_streak[pid]
            _log(EVENT_FILE, "OVER-KILL-THRESH pid={} {:.1f}GB[{}] streak={} {}"
                 .format(pid, gb, metric, streak, comm))
            # A fast balloon can hit tens of GB inside one interval and freeze
            # the machine before a sustained streak can accumulate, so past
            # EMERGENCY_GB one reading is enough.
            enough = streak >= SUSTAINED_CHECKS or gb >= EMERGENCY_GB
            if AUTO_KILL and not is_protected(comm, cmd) and enough:
                _notify("MIST: memory watchdog",
                        "Killing {} at {:.0f}GB before it freezes the machine".format(comm, gb))
                _log(EVENT_FILE, "ACTION kill {}".format(label))
                kill(pid, comm)
                _over_kill_streak.pop(pid, None)
                continue
            if is_protected(comm, cmd):
                _log(EVENT_FILE, "PROTECTED (not killing) {}".format(label))

        # warn (throttled) for anything over WARN_GB
        if now - _last_warn.get(pid, 0) >= WARN_THROTTLE_SECS:
            _last_warn[pid] = now
            _log(EVENT_FILE, "WARN {}".format(label))
            _notify("MIST: memory watchdog",
                    "{} is using {:.0f}GB RAM (8GB machine)".format(comm, gb))

    # forget pids that fell back below the kill threshold or died
    for pid in list(_over_kill_streak):
        if pid not in seen_pids:
            _over_kill_streak.pop(pid, None)


def main():
    _log(EVENT_FILE, "watchdog start v2: footprint-aware (warn={}GB kill={}GB emergency={}GB swap-warn={}GB sustained={} auto_kill={} every {}s)"
         .format(WARN_GB, KILL_GB, EMERGENCY_GB, SWAP_WARN_GB, SUSTAINED_CHECKS, AUTO_KILL, CHECK_SECS))
    while True:
        try:
            tick()
        except Exception as exc:  # never let one bad read kill the watchdog
            _log(EVENT_FILE, "ERROR {}: {}".format(type(exc).__name__, exc))
        time.sleep(CHECK_SECS)


if __name__ == "__main__":
    main()
