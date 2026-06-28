#!/usr/bin/env python3
"""
WiFi Roam — keep this Mac on the best-*throughput* known network.

macOS only consults the preferred-networks list at *join* time. Once it latches
onto a network (notably a phone hotspot) it sits there even when a better known
wifi is in range. This watcher fixes that: it scans on a timer, ranks every
*known* network by expected throughput, and switches to the best one.

Throughput cannot be measured for a network you are not connected to, so it is
handled in three layers:
  1. MEASURED  — a small capped speed probe of the *current* link (catches a
     throttled hotspot whose signal is strong but backhaul is slow).
  2. LEARNED   — every probe is stored per-SSID (EWMA) in state.json and used to
     rank that network next time without re-probing.
  3. ESTIMATED — for a known net we've never measured, capacity is estimated from
     the scan (band, channel width, signal). Cold-start only; learning overrides.

Signal (RSSI) is demoted to a *gate* (must be joinable) plus a tiebreaker.

Network names on macOS 14.4+ are gated behind Location Services, so this MUST run
from inside WiFiRoam.app (which holds the grant). Run it via the bundle's
executable, never the bare interpreter, or every SSID comes back redacted.

Modes:
  --scan       print the scan (known nets, signal, est. throughput) and exit
  --probe      run a throughput probe of the current link and exit
  --once       run one decide cycle and act, then exit
  --dry-run    decide + print, never switch (compose with --once)
  (no flag)    resident daemon: hold Location auth, then loop forever
"""
import sys, os, json, time, subprocess, urllib.request

import objc
import CoreWLAN
import CoreLocation
from Foundation import NSRunLoop, NSTimer, NSObject

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, "state.json")          # gitignored (learned speeds)
LOG_PATH = os.path.join(HERE, "roam.log")              # gitignored

DEFAULTS = {
    "interface": "en0",
    "poll_seconds": 30,
    # ---- joinability gate ----
    "min_join_rssi": -78,            # dBm; weaker known nets are ignored
    # ---- throughput ranking ----
    # switch only if the best candidate beats the current link by this fraction
    # AND by the absolute floor below (hysteresis, stops flapping)
    "throughput_margin_frac": 0.30,  # +30% expected throughput to bother switching
    "throughput_margin_floor_mbps": 5,
    # ---- speed probe (measures real end-to-end Mbps of the CURRENT link) ----
    "probe_url": "https://speed.cloudflare.com/__down?bytes={bytes}",
    "probe_bytes": 4_000_000,        # ~4 MB; capped by timeout
    "probe_timeout": 8,              # seconds
    "probe_interval_seconds": 600,   # don't re-probe the same link more often
    "ewma_alpha": 0.4,               # weight of a new measurement vs history
    "learned_ttl_seconds": 86_400,   # a learned speed older than this -> re-estimate
    # ---- metered networks (your hotspot): never probe; assume this throughput ----
    "metered_ssids": [],
    "assumed_metered_mbps": 8,
    # ---- switching ----
    # SSID -> password. With a password we join the target directly (no outage,
    # honors the throughput choice). Without one we fall back to disassociate +
    # macOS auto-join, which only reliably escapes low-priority nets (the hotspot).
    "passwords": {},
    "switch_cooldown_seconds": 120,   # min gap between switches (anti-flap)
}


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError) as e:
        log(f"config error ({e}); using defaults")
    return cfg


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_state(state):
    try:
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_PATH)
    except OSError as e:
        log(f"state save failed: {e}")


def iface(cfg):
    return CoreWLAN.CWWiFiClient.sharedWiFiClient().interfaceWithName_(cfg["interface"])


def preferred_ssids(cfg):
    try:
        out = subprocess.check_output(
            ["networksetup", "-listpreferredwirelessnetworks", cfg["interface"]],
            text=True, stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.startswith("\t")]


# ---- scan + capacity estimate -------------------------------------------------

# CWChannelBand: 1=2GHz 2=5GHz 3=6GHz.  CWChannelWidth: 1=20 2=40 3=80 4=160 MHz.
_BAND_BASE = {1: 80, 2: 350, 3: 600}        # rough best-case Mbps by band
_WIDTH_MULT = {1: 1.0, 2: 1.8, 3: 3.5, 4: 6.5}


def _rssi_quality(rssi):
    # fraction of capacity realistically usable at this signal level
    if rssi >= -55: return 1.0
    if rssi >= -62: return 0.85
    if rssi >= -68: return 0.65
    if rssi >= -73: return 0.45
    if rssi >= -78: return 0.25
    return 0.10


def estimate_mbps(entry):
    band = entry.get("band") or 2
    width = entry.get("width") or 1
    base = _BAND_BASE.get(band, 120) * _WIDTH_MULT.get(width, 1.0)
    return round(base * _rssi_quality(entry["rssi"]), 1)


def scan(cfg):
    nets, err = iface(cfg).scanForNetworksWithName_error_(None, None)
    if err is not None:
        log(f"scan error: {err}")
        return []
    rows = {}
    for n in (nets or []):
        ssid = n.ssid()
        if not ssid:                       # redacted -> no Location grant
            continue
        ch = n.wlanChannel()
        band = ch.channelBand() if ch else None
        width = ch.channelWidth() if ch else None
        rssi = int(n.rssiValue())
        e = {"ssid": ssid, "bssid": n.bssid(), "rssi": rssi,
             "band": band, "width": width}
        if ssid not in rows or rssi > rows[ssid]["rssi"]:
            rows[ssid] = e
    out = list(rows.values())
    for e in out:
        e["est_mbps"] = estimate_mbps(e)
    return sorted(out, key=lambda e: -e["est_mbps"])


def current(cfg):
    i = iface(cfg)
    ssid = i.ssid()
    rssi = i.rssiValue()
    tx = i.transmitRate()
    return {"ssid": ssid,
            "rssi": int(rssi) if rssi else None,
            "tx_mbps": float(tx) if tx else None}


# ---- throughput probe + learning ---------------------------------------------

def probe_mbps(cfg):
    """Measure real end-to-end download throughput of the CURRENT link (Mbps)."""
    url = cfg["probe_url"].format(bytes=cfg["probe_bytes"])
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (WiFiRoam)"})
    try:
        t0 = time.time()
        got = 0
        with urllib.request.urlopen(req, timeout=cfg["probe_timeout"]) as r:
            deadline = t0 + cfg["probe_timeout"]
            while time.time() < deadline:
                chunk = r.read(65536)
                if not chunk:
                    break
                got += len(chunk)
        dt = time.time() - t0
        if dt <= 0 or got == 0:
            return None
        return round(got * 8 / dt / 1e6, 1)
    except Exception as e:
        log(f"probe failed: {e}")
        return None


def record(state, ssid, mbps, rssi, cfg):
    prev = state.get(ssid, {})
    if "mbps" in prev:
        a = cfg["ewma_alpha"]
        mbps = round(a * mbps + (1 - a) * prev["mbps"], 1)
    state[ssid] = {"mbps": mbps, "rssi": rssi, "ts": int(time.time())}
    save_state(state)


def learned_mbps(state, ssid, cfg):
    e = state.get(ssid)
    if not e:
        return None
    if time.time() - e.get("ts", 0) > cfg["learned_ttl_seconds"]:
        return None
    return e["mbps"]


def current_throughput(state, cfg, cur):
    """Best estimate of the current link's real throughput, probing if stale."""
    ssid = cur["ssid"]
    if not ssid:
        return 0.0, "no link"
    if ssid in cfg["metered_ssids"]:
        return float(cfg["assumed_metered_mbps"]), "metered (assumed)"
    e = state.get(ssid, {})
    fresh = e and time.time() - e.get("ts", 0) < cfg["probe_interval_seconds"]
    if fresh:
        return e["mbps"], "measured (cached)"
    m = probe_mbps(cfg)
    if m is not None:
        record(state, ssid, m, cur["rssi"], cfg)
        return m, "measured (probed)"
    if "mbps" in e:
        return e["mbps"], "measured (stale, probe failed)"
    return (cur["tx_mbps"] or 0.0), "PHY rate (no probe)"


def expected_mbps(state, entry, cfg):
    """Expected throughput for a CANDIDATE network (learned if we have it)."""
    if entry["ssid"] in cfg["metered_ssids"]:
        return float(cfg["assumed_metered_mbps"]), "metered"
    m = learned_mbps(state, entry["ssid"], cfg)
    if m is not None:
        return m, "learned"
    return entry["est_mbps"], "estimated"


# ---- decision -----------------------------------------------------------------

def decide(cfg, state):
    prefs = set(preferred_ssids(cfg))
    if not prefs:
        return None, "no preferred networks known"
    cur = current(cfg)
    found = scan(cfg)
    cands = [e for e in found if e["ssid"] in prefs and e["rssi"] >= cfg["min_join_rssi"]]
    if not cands:
        return None, f"no known network above {cfg['min_join_rssi']} dBm in range"

    cur_mbps, cur_src = current_throughput(state, cfg, cur)

    scored = []
    for e in cands:
        exp, src = expected_mbps(state, e, cfg)
        scored.append((exp, e, src))
    scored.sort(key=lambda x: -x[0])
    best_exp, best, best_src = scored[0]

    if best["ssid"] == cur["ssid"]:
        return None, (f"already on best: {cur['ssid']} "
                      f"~{cur_mbps:.0f} Mbps ({cur_src}, {cur['rssi']} dBm)")

    need = max(cur_mbps * (1 + cfg["throughput_margin_frac"]),
               cur_mbps + cfg["throughput_margin_floor_mbps"])
    if best_exp < need:
        return None, (f"staying on {cur['ssid']} ~{cur_mbps:.0f} Mbps ({cur_src}); "
                      f"best alt {best['ssid']} ~{best_exp:.0f} Mbps ({best_src}) "
                      f"below switch bar ~{need:.0f}")
    return best["ssid"], (f"switch {cur['ssid']}(~{cur_mbps:.0f} Mbps {cur_src}) -> "
                          f"{best['ssid']}(~{best_exp:.0f} Mbps {best_src}, {best['rssi']} dBm)")


def _learn_current_link(ssid, cfg, state):
    """After a join settles, probe the new link so we learn its real throughput."""
    time.sleep(5)
    cur = current(cfg)
    if cur["ssid"] and cur["ssid"] not in cfg["metered_ssids"]:
        m = probe_mbps(cfg)
        if m is not None:
            record(state, cur["ssid"], m, cur["rssi"], cfg)
            log(f"learned {cur['ssid']!r} ~{m:.0f} Mbps")


def switch(ssid, cfg, state):
    cur_ssid = current(cfg)["ssid"]
    pw = cfg.get("passwords", {}).get(ssid)

    # 1. deterministic join when we hold the password — no outage, honors choice
    if pw:
        r = subprocess.run(
            ["networksetup", "-setairportnetwork", cfg["interface"], ssid, pw],
            capture_output=True, text=True,
        )
        out = (r.stdout + r.stderr).strip()
        if r.returncode == 0 and "Failed" not in out and "Could not" not in out:
            log(f"joined {ssid!r} (stored password)")
            _learn_current_link(ssid, cfg, state)
            return True
        log(f"join with stored password failed for {ssid!r}: {out!r}")

    # 2. no/failed password: disassociate + macOS auto-join, but only when that
    #    would actually move us toward the target (escaping a metered/lower-priority
    #    net). Otherwise auto-join would just re-pick the current network.
    prefs = preferred_ssids(cfg)
    def prio(s):
        return prefs.index(s) if s in prefs else 10_000
    leaving_metered = cur_ssid in cfg["metered_ssids"]
    target_higher = prio(ssid) < prio(cur_ssid)
    if leaving_metered or target_higher:
        log(f"disassociating from {cur_ssid!r} to auto-join a better known net "
            f"(toward {ssid!r})")
        iface(cfg).disassociate()
        _learn_current_link(ssid, cfg, state)
        return True

    log(f"can't switch to {ssid!r}: no stored password and it isn't higher-priority "
        f"than {cur_ssid!r}. Add its password to config 'passwords' for a direct join.")
    return False


def cycle(cfg, state, act=True):
    target, reason = decide(cfg, state)
    log(f"decide: {reason}")
    if target and act:
        since = time.time() - state.get("_last_switch", 0)
        if since < cfg["switch_cooldown_seconds"]:
            log(f"cooldown: {cfg['switch_cooldown_seconds'] - since:.0f}s left, not switching")
            return target
        if switch(target, cfg, state):
            state["_last_switch"] = int(time.time())
            save_state(state)
    return target


# ---- daemon -------------------------------------------------------------------

class Delegate(NSObject):
    def initWithCfg_(self, cfg):
        self = objc.super(Delegate, self).init()
        if self is None:
            return None
        self.cfg = cfg
        self.state = load_state()
        self.started = False
        return self

    def _maybe_start(self, mgr):
        status = mgr.authorizationStatus()
        if status in (3, 4) and not self.started:        # always / when-in-use
            self.started = True
            log("Location authorized — starting roam loop")
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                self.cfg["poll_seconds"], self, b"_tick:", None, True)
            self._tick_(None)
        elif status == 2:                                # denied
            log("Location DENIED — SSIDs will be redacted. Grant WiFiRoam under "
                "System Settings > Privacy & Security > Location Services.")

    def locationManagerDidChangeAuthorization_(self, mgr):
        self._maybe_start(mgr)

    def _tick_(self, _timer):
        try:
            cycle(self.cfg, self.state, act=True)
        except Exception as e:
            log(f"cycle error: {e}")


def run_daemon(cfg):
    mgr = CoreLocation.CLLocationManager.alloc().init()
    delegate = Delegate.alloc().initWithCfg_(cfg)
    mgr.setDelegate_(delegate)
    mgr.requestWhenInUseAuthorization()
    log("daemon up; requesting Location authorization")
    delegate._maybe_start(mgr)
    NSRunLoop.currentRunLoop().run()


def main():
    cfg = load_config()
    state = load_state()
    args = set(sys.argv[1:])
    if "--scan" in args:
        prefs = set(preferred_ssids(cfg))
        cur = current(cfg)
        print(f"current: {cur['ssid']!r} {cur['rssi']} dBm  PHY {cur['tx_mbps']} Mbps")
        print(f"{len(prefs)} preferred networks known")
        for e in scan(cfg):
            mark = "*" if e["ssid"] in prefs else " "
            learn = learned_mbps(state, e["ssid"], cfg)
            tag = f"learned ~{learn:.0f}" if learn else f"est ~{e['est_mbps']:.0f}"
            print(f" {mark} {e['rssi']:>4} dBm  {tag:>12} Mbps  {e['ssid']}")
        return
    if "--probe" in args:
        m = probe_mbps(cfg)
        print(f"probe: {m} Mbps" if m else "probe failed")
        return
    if "--once" in args:
        cycle(cfg, state, act="--dry-run" not in args)
        return
    run_daemon(cfg)


if __name__ == "__main__":
    main()
