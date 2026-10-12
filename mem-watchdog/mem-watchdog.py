#!/usr/bin/python3
"""Memory watchdog for the 8GB MacBook Air (v4).

Two failure modes, two kinds of response.

1. A runaway process. One of the pywebview/Flask fleet apps leaking in its
   WKWebView frontend, a grep with an unbounded regex, a printer driver: a
   single process climbs to tens of GB, swap thrashes, and the machine freezes
   hard enough to need a power-button reboot. A hard freeze eats the unified
   log, so nothing records who did it. The kill logic here is unchanged from v3:
   warn at WARN_GB, kill after SUSTAINED_CHECKS reads over KILL_GB, kill on the
   FIRST read over EMERGENCY_GB, and kill stateless search tools (EXPENDABLE)
   on sight over EXPENDABLE_KILL_GB. Every warn and kill is logged with the
   offender's full command.

2. Diffuse pressure. No single process is huge, but a handful of medium
   residents (the Console's web view, browsers, MCP server fleets, a model
   loaded by a batch job) hold the machine at 7 GB of swap with the compressor
   moving >100 MB/s. v3 alerted on swap USED, a stock, and fired once an hour
   for weeks (692 banners). v4 reads what the kernel itself uses to decide
   pressure (kern.memorystatus_vm_pressure_level: 1 normal, 2 warning,
   4 critical) plus the FLOW (compressions + decompressions per second from
   vm_stat) and alerts on state transitions with hysteresis and a daily cap.

v4 also alerts on GROWTH, not just level: a process over SLOPE_MIN_GB that
adds SLOPE_GB_10MIN in ten minutes gets one alert naming the rate and the
time to physical RAM, so a leak is reported at 1-2 GB instead of 5.

Alerts go through the harness notifier (mist-voice/bin/mist-notify): clickable
banner that opens a seeded MIST chat, Discord DM, bell-panel history, and an
action button that carries the remedy when one exists. The Console's web view
is a known offender: above CONSOLE_RELOAD_GB the watchdog asks the Console to
reload its page when nobody is typing and no chat is streaming (POST /ui/reload;
the page decides when), and measures whether the reload freed memory. If it did
not, the next alert offers "Restart Console when idle" instead.

Ordering: a kill happens BEFORE its notification (notifications run in a
thread), because during a freeze the notifier's subprocesses are what stall.

Stdlib only, system python (3.9). launchd must root the job in /bin/bash (see
the plist): bash holds Full Disk Access, and TCC attributes a launchd job's
file access to its root binary, so the notifier under ~/Documents is readable.
Rooted in python3 directly, every notifier call fails with "Operation not
permitted" (that was v3's silent failure from 2026-09 to 2026-10-11).
"""
import ctypes
import ctypes.util
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def _harness_dir():
    """Locate the harness repo. Run in place, it is this file's parent dir. The
    launchd copy lives in ~/Library/Application Support (see README), so there
    the install step records the repo path in a `harness-dir` file next to it."""
    parent = os.path.dirname(HERE)
    if os.path.isdir(os.path.join(parent, "mist-voice")):
        return parent
    try:
        with open(os.path.join(HERE, "harness-dir")) as f:
            return f.read().strip()
    except OSError:
        return ""


def _env_f(name, default):
    return float(os.environ.get(name, str(default)))


def _env_i(name, default):
    return int(os.environ.get(name, str(default)))


# --- tunables (override via env) -------------------------------------------
CHECK_SECS = _env_f("MEMWD_CHECK_SECS", 20)
WARN_GB = _env_f("MEMWD_WARN_GB", 5.0)             # per-process level alert
KILL_GB = _env_f("MEMWD_KILL_GB", 12.0)            # auto-kill above this (sustained)
EMERGENCY_GB = _env_f("MEMWD_EMERGENCY_GB", 16.0)  # kill on FIRST read above this
SUSTAINED_CHECKS = _env_i("MEMWD_SUSTAINED", 2)
TOP_N = _env_i("MEMWD_TOP_N", 5)
TOP_EVERY = _env_i("MEMWD_TOP_EVERY", 5)           # footprint scan every Nth tick when pressure is normal
AUTO_KILL = os.environ.get("MEMWD_AUTO_KILL", "1") != "0"
NOTIFY = os.environ.get("MEMWD_NOTIFY", "1") != "0"
EXPENDABLE_KILL_GB = _env_f("MEMWD_EXPENDABLE_KILL_GB", 3.0)
EXPENDABLE = tuple(n for n in os.environ.get("MEMWD_EXPENDABLE", "ugrep,bfs").split(",") if n)
# growth alert: a process over SLOPE_MIN_GB that gained SLOPE_GB_10MIN in 10 min
SLOPE_MIN_GB = _env_f("MEMWD_SLOPE_MIN_GB", 1.0)
SLOPE_GB_10MIN = _env_f("MEMWD_SLOPE_GB_10MIN", 0.5)
PROC_ALERT_THROTTLE = _env_f("MEMWD_PROC_ALERT_THROTTLE", 3600)  # one alert per pid per hour
# pressure alerts
THRASH_PAGES_PER_SEC = _env_f("MEMWD_THRASH_PAGES_PER_SEC", 3000)  # ~47 MB/s of 16 KB pages
PRESSURE_SUSTAIN_SECS = _env_f("MEMWD_PRESSURE_SUSTAIN_SECS", 600)
PRESSURE_REALERT_SECS = _env_f("MEMWD_PRESSURE_REALERT_SECS", 7200)
PRESSURE_DAILY_CAP = _env_i("MEMWD_PRESSURE_DAILY_CAP", 3)
CRITICAL_REALERT_SECS = _env_f("MEMWD_CRITICAL_REALERT_SECS", 1800)
SWAP_WARN_GB = _env_f("MEMWD_SWAP_WARN_GB", 12.0)   # high-water mark only (13 GB preceded the 2026-10-08 freeze)
# Console web view remedy
CONSOLE_PORT = _env_i("MEMWD_CONSOLE_PORT", 5014)
CONSOLE_DIR = os.environ.get("MEMWD_CONSOLE_DIR", os.path.expanduser("~/Documents/mist-console"))
CONSOLE_RELOAD_GB = _env_f("MEMWD_CONSOLE_RELOAD_GB", 2.5)  # 0 disables the automatic reload request
CONSOLE_RELOAD_COOLDOWN = _env_f("MEMWD_CONSOLE_RELOAD_COOLDOWN", 1800)
CONSOLE_RELOAD_CHECK_SECS = _env_f("MEMWD_CONSOLE_RELOAD_CHECK_SECS", 180)
LOG_MAX_BYTES = _env_i("MEMWD_LOG_MAX", 5 * 1024 * 1024)

LOG_FILE = os.path.join(HERE, "mem-watchdog.log")
EVENT_FILE = os.path.join(HERE, "events.log")

# Never kill these, matched on the exact basename of the command.
PROTECTED = frozenset((
    "kernel_task", "launchd", "WindowServer", "loginwindow", "logind",
    "Finder", "Dock", "SystemUIServer", "coreaudiod", "mds", "mds_stores",
    "syspolicyd", "opendirectoryd", "configd", "powerd", "mem-watchdog.py",
))
WEBCONTENT = "com.apple.WebKit.WebContent"

_own_pid = os.getpid()
_dry_run = False


# ------------------------------------------------------------------ logging --

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
    if _dry_run:
        print("[{}] {}".format(os.path.basename(path), line), flush=True)


# ------------------------------------------------------------- kernel reads --

_libc = None
try:
    _libc = ctypes.CDLL(ctypes.util.find_library("c"))
except Exception:
    _libc = None


def sysctl_int(name, default=None):
    """kern.memorystatus_vm_pressure_level etc. via sysctlbyname, no fork."""
    if _libc is not None:
        v = ctypes.c_int(0)
        n = ctypes.c_size_t(ctypes.sizeof(v))
        if _libc.sysctlbyname(name.encode(), ctypes.byref(v), ctypes.byref(n), None, 0) == 0:
            return v.value
    try:
        out = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True,
                             check=False, timeout=5).stdout.strip()
        return int(out)
    except Exception:
        return default


def swap_gb():
    """(used, total) in GB from vm.swapusage (struct xsw_usage)."""
    if _libc is not None:
        buf = ctypes.create_string_buffer(32)
        n = ctypes.c_size_t(32)
        if _libc.sysctlbyname(b"vm.swapusage", buf, ctypes.byref(n), None, 0) == 0:
            total, _avail, used = struct.unpack("QQQ", buf.raw[:24])
            return used / 2.0 ** 30, total / 2.0 ** 30
    out = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True,
                         text=True, check=False).stdout
    # "total = 7168.00M  used = 6005.06M  free = 1162.94M  (encrypted)"
    try:
        def val(key):
            raw = out.split(key + " =")[1].split()[0]
            v = float(raw.rstrip("MG"))
            return v / 1024.0 if raw.endswith("M") else v
        return val("used"), val("total")
    except (IndexError, ValueError):
        return 0.0, 0.0


PRESSURE_NAMES = {1: "normal", 2: "warning", 4: "critical"}


def pressure_level():
    lvl = sysctl_int("kern.memorystatus_vm_pressure_level", 1)
    return lvl if lvl in PRESSURE_NAMES else (4 if lvl and lvl > 2 else 1)


def vm_counters():
    """Cumulative page counters from vm_stat (one cheap fork)."""
    out = subprocess.run(["vm_stat"], capture_output=True, text=True, check=False,
                         timeout=10).stdout
    want = {"Compressions": "comp", "Decompressions": "decomp", "Swapins": "swapin",
            "Swapouts": "swapout", "Pageins": "pagein", "Pages free": "free",
            "Pages occupied by compressor": "compressor"}
    got = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().strip('"')
        if key in want:
            try:
                got[want[key]] = int(val.strip().rstrip("."))
            except ValueError:
                pass
    return got


class Rates:
    """Per-second deltas of the vm counters, plus a 10-minute thrash average."""

    def __init__(self):
        self.prev = None
        self.prev_t = 0.0
        self.now = {}
        self.window = deque()   # (t, thrash pages/s)

    def update(self):
        t = time.time()
        cur = vm_counters()
        rates = {}
        if self.prev and t > self.prev_t:
            dt = t - self.prev_t
            for k in ("comp", "decomp", "swapin", "swapout", "pagein"):
                if k in cur and k in self.prev:
                    rates[k] = max(0.0, (cur[k] - self.prev[k]) / dt)
        self.prev, self.prev_t = cur, t
        self.now = rates
        thrash = rates.get("comp", 0.0) + rates.get("decomp", 0.0)
        self.window.append((t, thrash))
        while self.window and t - self.window[0][0] > 600:
            self.window.popleft()
        return rates

    @property
    def thrash(self):
        return self.now.get("comp", 0.0) + self.now.get("decomp", 0.0)

    def thrash_avg(self):
        if not self.window:
            return 0.0
        return sum(v for _, v in self.window) / len(self.window)

    def text(self):
        r = self.now
        if not r:
            return "thrash=n/a"
        return "thrash={:.0f}/s (c={:.0f} d={:.0f} si={:.0f} so={:.0f})".format(
            self.thrash, r.get("comp", 0), r.get("decomp", 0), r.get("swapin", 0), r.get("swapout", 0))


# ------------------------------------------------------------ process reads --

def ps_rows():
    """pid -> (ppid, rss_gb, comm) for every process, one fork."""
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,rss=,comm="],
                         capture_output=True, text=True, check=False, timeout=15).stdout
    rows = {}
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            rows[int(parts[0])] = (int(parts[1]), int(parts[2]) / 1024.0 / 1024.0, parts[3].strip())
        except ValueError:
            continue
    return rows


def top_footprint():
    """pid -> phys footprint GB from `top` (includes COMPRESSED pages).

    ps RSS only counts resident uncompressed pages, so a leaking process whose
    stale garbage gets compressed can reach tens of GB of real footprint while
    RSS stays under 1GB -- how the 2026-08-14 34GB Console balloon slid past
    every RSS-based tick. top's MEM column matches Activity Monitor's Memory
    column (validated against /usr/bin/footprint)."""
    out = subprocess.run(
        ["top", "-l", "1", "-o", "mem", "-n", "40", "-stats", "pid,mem,command"],
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


def snapshot(use_top):
    """(rows sorted desc by GB as [(pid, gb, comm, metric)], ps map, footprint map)."""
    ps = ps_rows()
    fp = {}
    if use_top:
        try:
            fp = top_footprint()
        except Exception as exc:
            _log(EVENT_FILE, "ERROR top: {}".format(exc))
    rows = []
    for pid, (_ppid, rss, comm) in ps.items():
        f = fp.get(pid, 0.0)
        if f > rss:
            rows.append((pid, f, comm, "footprint"))
        else:
            rows.append((pid, rss, comm, "rss"))
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows, ps, fp


def full_command(pid):
    out = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                         capture_output=True, text=True, check=False).stdout.strip()
    return out[:300]


def etime_secs(pid):
    out = subprocess.run(["ps", "-p", str(pid), "-o", "etime="],
                         capture_output=True, text=True, check=False).stdout.strip()
    if not out:
        return None
    days = 0
    if "-" in out:
        d, out = out.split("-", 1)
        days = int(d)
    parts = [int(x) for x in out.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return days * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def is_protected(pid, comm):
    return pid == _own_pid or os.path.basename(comm) in PROTECTED


def claude_summary(ps, fp):
    """One line: live Claude Code sessions and the footprint of their MCP children."""
    kids = {}
    for pid, (ppid, _rss, _comm) in ps.items():
        kids.setdefault(ppid, []).append(pid)
    roots = [pid for pid, (_p, _r, comm) in ps.items() if os.path.basename(comm) == "claude"]
    if not roots:
        return "claude sessions: 0"

    def tree(pid):
        out = [pid]
        for k in kids.get(pid, []):
            out += tree(k)
        return out

    def gb(pid):
        return max(fp.get(pid, 0.0), ps[pid][1])

    children = 0.0
    own = 0.0
    nproc = 0
    for r in roots:
        ids = tree(r)
        nproc += len(ids) - 1
        own += gb(r)
        children += sum(gb(i) for i in ids if i != r)
    return "claude sessions: {} ({:.1f} GB) with {} MCP child procs ({:.1f} GB)".format(
        len(roots), own, nproc, children)


# ------------------------------------------------------------------ history --

class History:
    """Per-pid footprint samples (footprint ticks only) for growth detection."""

    def __init__(self, keep_secs=3900):
        self.keep = keep_secs
        self.samples = {}   # pid -> deque[(t, gb)]

    def record(self, rows, now):
        seen = set()
        for pid, gb, _comm, metric in rows:
            if metric != "footprint":
                continue
            seen.add(pid)
            dq = self.samples.setdefault(pid, deque())
            dq.append((now, gb))
            while dq and now - dq[0][0] > self.keep:
                dq.popleft()
        for pid in list(self.samples):
            if pid not in seen and self.samples[pid] and now - self.samples[pid][-1][0] > 900:
                del self.samples[pid]

    def growth(self, pid, window, now, band=150):
        """Rise of the footprint floor over `window` seconds, or None without a sample that old.

        Compares the minimum of the samples in the last `band` seconds with the
        minimum of the samples within `band` of the window start. A point-to-point
        difference reads a sawtooth (a video tab that swings 0.5 to 1.7 GB between
        GC passes, 2026-10-12) as a leak. A real leak raises the floor too.
        """
        dq = self.samples.get(pid)
        if not dq or now - dq[0][0] < window * 0.8:
            return None
        start = [gb for t, gb in dq if abs((now - t) - window) <= band]
        recent = [gb for t, gb in dq if now - t <= band]
        if not start or not recent:
            return None
        return min(recent) - min(start)


# -------------------------------------------------------------- notifier -----

def _mist_notify_path():
    p = os.path.join(_harness_dir(), "mist-voice", "bin", "mist-notify")
    return p if os.path.exists(p) else None


def _deliver(title, message, sound, urgency, actions, context, nid):
    """Deliver through mist-notify (banner + Discord + bell panel), else fall
    back to terminal-notifier, else osascript. Runs in a worker thread."""
    mist = _mist_notify_path()
    if mist:
        argv = [mist, message, title, sound or "none", "console", "--group", "memory", "--discord"]
        if nid:
            argv += ["--id", nid]
        if urgency:
            argv += ["--urgency", urgency]
        if context:
            argv += ["--context", context[:4000]]
        for label, target in actions[:3]:
            argv += ["--action", "{}={}".format(label, target)]
        if _dry_run:
            argv.append("--dry-run")
        try:
            r = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=40)
            if r.returncode == 0:
                if _dry_run:
                    print("[mist-notify --dry-run] " + r.stdout.strip()[:600], flush=True)
                return "mist-notify"
            _log(EVENT_FILE, "NOTIFY-FAIL mist-notify rc={} {}".format(
                r.returncode, (r.stderr or r.stdout).strip()[-200:]))
        except Exception as exc:
            _log(EVENT_FILE, "NOTIFY-FAIL mist-notify {}: {}".format(type(exc).__name__, exc))
    if _dry_run:
        return "dry-run"
    safe_msg = message.replace('"', "'")
    safe_title = title.replace('"', "'")
    tn = shutil.which("terminal-notifier") or "/opt/homebrew/bin/terminal-notifier"
    try:
        if os.path.exists(tn):
            argv = [tn, "-title", safe_title, "-message", safe_msg,
                    "-execute", "open -a 'Activity Monitor'"]
            if sound and sound != "none":
                argv += ["-sound", sound]
            subprocess.run(argv, check=False, timeout=10)
            return "terminal-notifier"
    except Exception:
        pass
    try:
        subprocess.run(["osascript", "-e",
                        'display notification "{}" with title "{}"'.format(safe_msg, safe_title)],
                       check=False, timeout=10)
        return "osascript"
    except Exception:
        return "failed"


def notify(kind, title, message, sound="none", urgency=None, actions=(), context="", nid=None):
    """Non-blocking. The tick never waits on a banner, a DM or a stalled helper."""
    _log(EVENT_FILE, "NOTIFY[{}] {} | {}".format(kind, title, message))
    if not NOTIFY:
        return

    def run():
        via = _deliver(title, message, sound, urgency, list(actions), context, nid)
        _log(EVENT_FILE, "NOTIFIED[{}] via {}".format(kind, via))

    t = threading.Thread(target=run, daemon=True)
    t.start()
    if _dry_run:
        t.join(45)


# --------------------------------------------------------------- console ----

class Console:
    """The MIST Console's web view is a known offender: it grows with rendered
    content (~1.5 GB per active chat hour, measured 2026-10-11) and gives
    nothing back until the page reloads. The Console exposes GET /ui/webview
    (its web process pid, whether a chat is streaming) and POST /ui/reload (the
    page reloads once nobody is typing and no chat streams)."""

    def __init__(self):
        self.base = "http://127.0.0.1:{}".format(CONSOLE_PORT)
        self.last_request = 0.0
        self.pending_check = None     # (deadline, pid, gb_before)
        self.ineffective = set()      # webview pids where a reload did not free memory
        self.info = None
        self.info_t = 0.0
        self.missing_logged = False

    def _get(self, path, timeout=1.5):
        try:
            with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except Exception:
            return None

    def _post(self, path, body, timeout=3.0):
        data = json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return {"ok": False, "http": exc.code}
        except Exception:
            return None

    def refresh(self, now):
        if now - self.info_t < 30:
            return self.info
        self.info_t = now
        self.info = self._get("/ui/webview")
        if self.info is None and not self.missing_logged:
            self.missing_logged = True
        elif self.info is not None and self.missing_logged:
            self.missing_logged = False
        return self.info

    def webview_pid(self, rows, ps):
        """The Console's WebContent pid: from the Console itself when it knows,
        else the WebContent process that started within 20 s of the Console app."""
        info = self.info or {}
        pid = info.get("webview_pid")
        if pid and pid in ps:
            return pid
        app_pid = info.get("app_pid")
        if not app_pid:
            for p, (_pp, _r, comm) in ps.items():
                if comm.strip() == "MIST Console Server":
                    app_pid = p
                    break
        if not app_pid or app_pid not in ps:
            return None
        app_age = etime_secs(app_pid)
        if app_age is None:
            return None
        best = None
        for p, _gb, comm, _m in rows:
            if os.path.basename(comm) != WEBCONTENT:
                continue
            age = etime_secs(p)
            if age is not None and abs(age - app_age) <= 20:
                best = p
                break
        return best

    def reload_action(self, pid):
        if pid in self.ineffective:
            cmd = ("launchctl remove com.exobrain.mist-console-restart 2>/dev/null; "
                   "launchctl submit -l com.exobrain.mist-console-restart -- /bin/bash "
                   "'{}/bin/restart-server-when-idle'".format(CONSOLE_DIR))
            return ("Restart Console when idle", "cmd:" + cmd)
        return ("Reload Console", "cmd:curl -s -X POST '{}/ui/reload?force=1&reason=banner'".format(self.base))

    def maybe_reload(self, pid, gb, now):
        """Ask the Console to reload its page when the web view is over the
        threshold, no chat is streaming, and the cooldown has passed."""
        if CONSOLE_RELOAD_GB <= 0 or pid is None or gb < CONSOLE_RELOAD_GB:
            return
        if pid in self.ineffective or now - self.last_request < CONSOLE_RELOAD_COOLDOWN:
            return
        if self.pending_check is not None:
            return
        info = self.info or {}
        if info.get("streaming"):
            return
        res = self._post("/ui/reload", {"reason": "footprint", "gb": round(gb, 2), "pid": pid})
        self.last_request = now
        if not res or not res.get("ok"):
            _log(EVENT_FILE, "CONSOLE-RELOAD request failed ({}); the Console may predate /ui/reload"
                 .format(res))
            return
        _log(EVENT_FILE, "CONSOLE-RELOAD requested: web view pid={} at {:.1f}GB".format(pid, gb))
        self.pending_check = (now + CONSOLE_RELOAD_CHECK_SECS, pid, gb)

    def check_result(self, rows, now):
        if self.pending_check is None or now < self.pending_check[0]:
            return
        _deadline, pid, before = self.pending_check
        self.pending_check = None
        after = None
        for p, gb, _c, _m in rows:
            if p == pid:
                after = gb
                break
        if after is None:
            _log(EVENT_FILE, "CONSOLE-RELOAD result: web view pid={} gone (new process); {:.1f}GB released"
                 .format(pid, before))
            return
        freed = before - after
        if after <= before * 0.6:
            _log(EVENT_FILE, "CONSOLE-RELOAD result: {:.1f}GB -> {:.1f}GB (freed {:.1f}GB)".format(before, after, freed))
        else:
            self.ineffective.add(pid)
            _log(EVENT_FILE, "CONSOLE-RELOAD result: {:.1f}GB -> {:.1f}GB; a page reload does not free this "
                 "web view, offering a Console restart instead".format(before, after))


# ---------------------------------------------------------------- alerts ----

class Alerts:
    def __init__(self):
        self.level = 1
        self.level_since = time.time()
        self.last_pressure_alert = 0.0
        self.last_critical_alert = 0.0
        self.pressure_alerted = False   # an alert is open; send "cleared" once it ends
        self.cleared_pending_since = None
        self.day = datetime.now().date()
        self.pressure_today = 0
        self.swap_high = False
        self.last_swap_alert = 0.0
        self.proc_last = {}             # pid -> last alert epoch

    def _roll_day(self):
        d = datetime.now().date()
        if d != self.day:
            self.day = d
            self.pressure_today = 0

    def pressure(self, lvl, free_pct, swap_used, rates, ctx, actions, now):
        self._roll_day()
        if lvl != self.level:
            _log(EVENT_FILE, "PRESSURE {} -> {} (free={}% swap={:.1f}GB {})".format(
                PRESSURE_NAMES.get(self.level), PRESSURE_NAMES.get(lvl), free_pct, swap_used, rates.text()))
            self.level = lvl
            self.level_since = now
        sustained = now - self.level_since
        if lvl == 4:
            if now - self.last_critical_alert >= CRITICAL_REALERT_SECS:
                self.last_critical_alert = now
                self.pressure_alerted = True
                self.cleared_pending_since = None
                notify("critical", "MIST memory: critical pressure",
                       "The kernel reports critical memory pressure (free {}%, swap {:.0f} GB, "
                       "compressor {:.0f} MB/s). {}".format(free_pct, swap_used, rates.thrash * 16 / 1024,
                                                           ctx.splitlines()[0] if ctx else ""),
                       sound="Basso", urgency="timeSensitive", actions=actions, context=ctx,
                       nid="memwd-pressure")
            return
        if lvl == 2:
            self.cleared_pending_since = None
            if (sustained >= PRESSURE_SUSTAIN_SECS and rates.thrash_avg() >= THRASH_PAGES_PER_SEC
                    and now - self.last_pressure_alert >= PRESSURE_REALERT_SECS
                    and self.pressure_today < PRESSURE_DAILY_CAP):
                self.last_pressure_alert = now
                self.pressure_today += 1
                self.pressure_alerted = True
                notify("pressure", "MIST memory: sustained pressure",
                       "Memory pressure has been at warning for {:.0f} min with the compressor moving "
                       "{:.0f} MB/s (free {}%, swap {:.0f} GB). {}".format(
                           sustained / 60, rates.thrash_avg() * 16 / 1024, free_pct, swap_used,
                           ctx.splitlines()[0] if ctx else ""),
                       sound="none", actions=actions, context=ctx, nid="memwd-pressure")
            return
        # normal
        if self.pressure_alerted:
            if self.cleared_pending_since is None:
                self.cleared_pending_since = now
            elif now - self.cleared_pending_since >= PRESSURE_SUSTAIN_SECS:
                self.pressure_alerted = False
                self.cleared_pending_since = None
                notify("cleared", "MIST memory: pressure cleared",
                       "Memory pressure is back to normal (free {}%, swap {:.0f} GB).".format(free_pct, swap_used),
                       sound="none", nid="memwd-pressure")

    def swap(self, swap_used, ctx, actions, now):
        if swap_used >= SWAP_WARN_GB and not self.swap_high:
            self.swap_high = True
            if now - self.last_swap_alert >= PRESSURE_REALERT_SECS:
                self.last_swap_alert = now
                notify("swap", "MIST memory: swap high-water mark",
                       "Swap is at {:.0f} GB ({} GB preceded the 2026-10-08 freeze). {}".format(
                           swap_used, int(SWAP_WARN_GB) + 1, ctx.splitlines()[0] if ctx else ""),
                       sound="none", actions=actions, context=ctx, nid="memwd-swap")
        elif swap_used < SWAP_WARN_GB - 2 and self.swap_high:
            self.swap_high = False
            _log(EVENT_FILE, "SWAP back under {:.0f}GB ({:.1f}GB)".format(SWAP_WARN_GB - 2, swap_used))

    def proc_ok(self, pid, now):
        return now - self.proc_last.get(pid, 0.0) >= PROC_ALERT_THROTTLE

    def proc_mark(self, pid, now):
        self.proc_last[pid] = now
        for p in list(self.proc_last):
            if now - self.proc_last[p] > 86400:
                del self.proc_last[p]


# ----------------------------------------------------------------- kills ----

def kill(pid, label):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "gone"
    except PermissionError:
        _log(EVENT_FILE, "KILL-DENIED pid={} {} (not permitted)".format(pid, label))
        return "denied"
    for _ in range(10):
        time.sleep(1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            _log(EVENT_FILE, "KILLED pid={} {} (SIGTERM)".format(pid, label))
            return "term"
    try:
        os.kill(pid, signal.SIGKILL)
        _log(EVENT_FILE, "KILLED pid={} {} (SIGKILL after grace)".format(pid, label))
        return "kill"
    except ProcessLookupError:
        _log(EVENT_FILE, "KILLED pid={} {} (gone before SIGKILL)".format(pid, label))
        return "term"


# ------------------------------------------------------------------ tick -----

rates = Rates()
history = History()
alerts = Alerts()
console = Console()
_over_kill_streak = {}
_tick_n = 0


def short_name(comm):
    base = os.path.basename(comm)
    if base == WEBCONTENT:
        return "WebContent (web view)"
    return base


def describe(pid, comm, cmd, console_pid):
    """Human name + the remedy actions for a known offender."""
    base = os.path.basename(comm)
    actions = []
    if base == WEBCONTENT and pid == console_pid:
        return "the MIST Console's web view", [console.reload_action(pid)]
    if base == WEBCONTENT:
        return "a WebKit web view (not the Console's)", actions
    if "linkedin-mcp" in cmd or "Google Chrome for Testing" in comm:
        return "the LinkedIn MCP's Chrome (it closes with its chat)", actions
    if base == "Python" or base.startswith("python"):
        return "python ({})".format(cmd[-80:]), actions
    return base, actions


def tick():
    global _tick_n
    _tick_n += 1
    now = time.time()
    lvl = pressure_level()
    free_pct = sysctl_int("kern.memorystatus_level", -1)
    swap_used, swap_total = swap_gb()
    rates.update()
    use_top = lvl != 1 or swap_used >= 8.0 or _tick_n % TOP_EVERY == 1 or _over_kill_streak
    rows, ps, fp = snapshot(use_top)
    if not rows:
        return
    if use_top:
        history.record(rows, now)
    top = rows[:TOP_N]
    top_txt = " | ".join("{:.1f}G[{}] {}({})".format(gb, metric[0], comm, pid) for pid, gb, comm, metric in top)
    _log(LOG_FILE, "lvl={} free={}% swap={:.1f}/{:.1f}G {}{}".format(
        lvl, free_pct, swap_used, swap_total, rates.text(), (" top: " + top_txt) if use_top else ""))

    console.refresh(now)
    console_pid = console.webview_pid(rows, ps) if use_top else None

    ctx_lines = ["pressure={} free={}% swap={:.1f}/{:.1f} GB {}".format(
        PRESSURE_NAMES.get(lvl, lvl), free_pct, swap_used, swap_total, rates.text())]
    if use_top:
        ctx_lines.append("top by footprint: " + " | ".join(
            "{:.1f} GB {}({})".format(gb, short_name(comm), pid) for pid, gb, comm, _m in top))
        ctx_lines.append(claude_summary(ps, fp))
    ctx = "\n".join(ctx_lines)
    pressure_actions = []
    if console_pid is not None:
        for p, gb, _c, _m in rows:
            if p == console_pid and gb >= 1.0:
                pressure_actions.append(console.reload_action(p))
                break
    pressure_actions.append(("Activity Monitor", "/System/Applications/Utilities/Activity Monitor.app"))

    seen_pids = set()
    for pid, gb, comm, metric in rows:
        if pid == _own_pid:
            continue
        if gb < min(SLOPE_MIN_GB, EXPENDABLE_KILL_GB):
            break   # sorted desc; nothing below this matters
        seen_pids.add(pid)
        cmd = full_command(pid)
        label = "{} {}={:.1f}GB cmd={}".format(comm, metric, gb, cmd)

        # Fast lane: a ballooning search tool dies on first sight, silently
        # (its parent session sees the failed command; a banner would be spam).
        if AUTO_KILL and gb >= EXPENDABLE_KILL_GB and os.path.basename(comm) in EXPENDABLE:
            _log(EVENT_FILE, "ACTION kill-expendable {}".format(label))
            kill(pid, comm)
            _over_kill_streak.pop(pid, None)
            continue

        if gb >= KILL_GB:
            _over_kill_streak[pid] = _over_kill_streak.get(pid, 0) + 1
            streak = _over_kill_streak[pid]
            _log(EVENT_FILE, "OVER-KILL-THRESH pid={} {:.1f}GB[{}] streak={} {}".format(pid, gb, metric, streak, comm))
            # A fast balloon can hit tens of GB inside one interval and freeze
            # the machine before a streak accumulates, so past EMERGENCY_GB one
            # reading is enough.
            enough = streak >= SUSTAINED_CHECKS or gb >= EMERGENCY_GB
            if AUTO_KILL and not is_protected(pid, comm) and enough:
                _log(EVENT_FILE, "ACTION kill {}".format(label))
                how = kill(pid, comm)          # kill FIRST; the banner can wait
                _over_kill_streak.pop(pid, None)
                notify("kill", "MIST memory: killed {}".format(short_name(comm)),
                       "Killed {} at {:.0f} GB before it froze the machine ({}).".format(short_name(comm), gb, how),
                       sound="Basso", urgency="timeSensitive", context=ctx + "\n" + label,
                       nid="memwd-kill-{}".format(pid))
                continue
            if is_protected(pid, comm):
                _log(EVENT_FILE, "PROTECTED (not killing) {}".format(label))

        if not use_top:
            continue   # level/growth alerts need footprint, not RSS

        # Growth and level alerts: one per process per hour, silent, with the
        # remedy attached when there is one.
        g10 = history.growth(pid, 600, now) if gb >= SLOPE_MIN_GB else None
        growing = g10 is not None and g10 >= SLOPE_GB_10MIN
        if (gb >= WARN_GB or growing) and alerts.proc_ok(pid, now):
            alerts.proc_mark(pid, now)
            name, actions = describe(pid, comm, cmd, console_pid)
            if growing:
                rate_h = (g10 or 0.0) * 6
                eta_txt = ""
                if rate_h > 0 and gb < 8.0:
                    eta_txt = " (reaches physical RAM in {:.0f} min)".format((8.0 - gb) / rate_h * 60)
                msg = "{} is at {:.1f} GB and growing {:.1f} GB/h{}.".format(name, gb, rate_h, eta_txt)
                kind = "growth"
            else:
                msg = "{} is holding {:.1f} GB on the 8 GB machine.".format(name, gb)
                kind = "level"
            _log(EVENT_FILE, "{} pid={} {:.1f}GB g10={} {}".format(kind.upper(), pid, gb, g10, label))
            notify(kind, "MIST memory", msg, sound="none", actions=actions,
                   context=ctx + "\n" + label, nid="memwd-proc-{}".format(pid))

    for pid in list(_over_kill_streak):
        if pid not in seen_pids:
            _over_kill_streak.pop(pid, None)

    if use_top and console_pid is not None:
        for p, gb, _c, _m in rows:
            if p == console_pid:
                console.maybe_reload(p, gb, now)
                break
        console.check_result(rows, now)

    alerts.pressure(lvl, free_pct, swap_used, rates, ctx, pressure_actions, now)
    alerts.swap(swap_used, ctx, pressure_actions, now)


def main():
    global _dry_run, AUTO_KILL
    once = "--once" in sys.argv
    _dry_run = "--dry-run" in sys.argv
    if _dry_run:
        AUTO_KILL = False
    _log(EVENT_FILE, "watchdog start v4: pressure-level + growth alerts, Console reload hook "
         "(warn={}GB kill={}GB emergency={}GB expendable={}@{}GB slope=+{}GB/10min over {}GB "
         "swap-high={}GB thrash={}pg/s console-reload={}GB auto_kill={} notify={} every {}s, top every {} ticks)"
         .format(WARN_GB, KILL_GB, EMERGENCY_GB, ",".join(EXPENDABLE), EXPENDABLE_KILL_GB, SLOPE_GB_10MIN,
                 SLOPE_MIN_GB, SWAP_WARN_GB, THRASH_PAGES_PER_SEC, CONSOLE_RELOAD_GB, AUTO_KILL, NOTIFY,
                 CHECK_SECS, TOP_EVERY))
    while True:
        try:
            tick()
        except Exception as exc:   # never let one bad read kill the watchdog
            _log(EVENT_FILE, "ERROR {}: {}".format(type(exc).__name__, exc))
        if once:
            return
        time.sleep(CHECK_SECS)


if __name__ == "__main__":
    main()
