#!/usr/bin/env python3
"""Keep free-personal-team iOS sideloads alive on the phone.

Apple signs apps from a free Apple Developer account for exactly 7 days. When
the embedded provisioning profile expires the app stays on the home screen but
refuses to launch, which is a silent failure: you find out when you tap it and
it bounces. Paying $99/yr fixes it; so does rebuilding and reinstalling before
the deadline, which is all this does.

Every piece of that is non-interactive, which is what makes the automation
possible at all:

  * `xcodebuild -allowProvisioningUpdates` mints a fresh 7-day profile against
    the saved Xcode account without a 2FA prompt (verified 2026-08-23).
  * `devicectl` reaches the phone over the local-network tunnel once it has
    been paired for network connection, so nothing has to be plugged in.

So the job is just bookkeeping: know when each app dies, rebuild it a couple of
days early, push it over WiFi, and say something only when it matters.

Run `refresh.py --status` to see the countdown without touching anything.

INVARIANTS
  * Never install a bundle that is not already on the device. An app missing
    from `devicectl device info apps` was deleted on purpose, and resurrecting
    it every night would be obnoxious.
  * `state.json` is authoritative for what is ON THE PHONE. The embedded
    profile of a local build only bootstraps an unknown app, because Alex can
    build by hand without installing, which would otherwise read as "fresh"
    while the phone still holds the old, dying copy.
  * Never install a simulator build. Products/ holds both, they have the same
    bundle id, and installing the wrong one fails in a confusing way.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent
CONFIG_PATH = HERE / "apps.json"
STATE_PATH = HERE / "state.json"
PROFILE_DIR = Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles"
NOTIFY = HARNESS / "mist-voice" / "bin" / "mist-notify"
DEVELOPER_DIR = os.environ.get("DEVELOPER_DIR", "/Applications/Xcode.app/Contents/Developer")

# A 7-day life with a 2-day cushion leaves ~4 scheduled attempts before an app
# actually dies, which is the slack that makes a sleeping laptop survivable.
DEFAULT_THRESHOLD_DAYS = 2.0
QUIET = [False]
BUILD_TIMEOUT_SEC = 1200
DEVICE_TIMEOUT_SEC = 120


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    env = {**os.environ, "DEVELOPER_DIR": DEVELOPER_DIR}
    return subprocess.run(cmd, capture_output=True, text=True, env=env, **kw)


def devicectl_json(cmd: list[str]) -> dict | None:
    """Run a devicectl subcommand and return its parsed --json-output.

    Worth the temp file: the human-readable output interleaves progress lines
    with the data and puts device names containing spaces in the same columns
    as the fields you want, so scraping it is guesswork.
    """
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        out = run(["xcrun", "devicectl", *cmd, "--json-output", str(path)])
        if out.returncode != 0 or not path.exists() or path.stat().st_size == 0:
            return None
        return json.loads(path.read_text()).get("result")
    except (json.JSONDecodeError, OSError):
        return None
    finally:
        path.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# provisioning profiles


def profile_expiry(app_path: Path) -> dt.datetime | None:
    """Expiry of the profile embedded in a built .app, or None if unsigned."""
    embedded = app_path / "embedded.mobileprovision"
    if not embedded.exists():
        return None
    # Decode as bytes: a mobileprovision is CMS-wrapped and the payload can be
    # a binary plist, which a text-mode pipe would mangle.
    raw = subprocess.run(
        ["security", "cms", "-D", "-i", str(embedded)], capture_output=True
    ).stdout
    if not raw:
        return None
    try:
        expires = plistlib.loads(raw)["ExpirationDate"]
    except (plistlib.InvalidFileException, KeyError, ValueError):
        return None
    # plistlib hands back naive datetimes that are already UTC.
    return expires.replace(tzinfo=dt.timezone.utc)


def evict_cached_profiles(bundle_id: str) -> int:
    """Delete Xcode's cached provisioning profiles for one bundle id.

    This is the step that makes early refreshing work at all. Xcode reuses a
    cached profile for as long as it is technically still valid, so rebuilding
    on day 5 re-signs with the SAME profile that dies on day 7 and the app
    lapses anyway. With no cached profile to reuse, -allowProvisioningUpdates
    mints a new one and the 7-day clock restarts from now.

    Only ever removes profiles for the bundle being refreshed, and only ones
    Xcode can mint again on demand. Verified 2026-08-23: evicting produced a
    profile dated 7 minutes later than the one it replaced.
    """
    removed = 0
    for path in PROFILE_DIR.glob("*.mobileprovision"):
        raw = subprocess.run(
            ["security", "cms", "-D", "-i", str(path)], capture_output=True
        ).stdout
        if not raw:
            continue
        try:
            app_id = plistlib.loads(raw)["Entitlements"]["application-identifier"]
        except (plistlib.InvalidFileException, KeyError, ValueError):
            continue
        if app_id.split(".", 1)[-1] == bundle_id:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def prune_products(search_root: Path, bundle_id: str) -> None:
    """Delete existing device builds so the codesign step cannot be skipped.

    An up-to-date product means xcodebuild reports success without re-signing,
    which would leave the old profile embedded and quietly defeat the refresh.
    """
    for app in search_root.rglob("*.app"):
        if "-iphoneos" in app.parent.name and bundle_id_of(app) == bundle_id:
            shutil.rmtree(app, ignore_errors=True)


def bundle_id_of(app_path: Path) -> str | None:
    info = app_path / "Info.plist"
    if not info.exists():
        return None
    try:
        return plistlib.loads(info.read_bytes()).get("CFBundleIdentifier")
    except Exception:
        return None


# --------------------------------------------------------------------------
# device


def find_device(pinned: str | None, wait_sec: int = DEVICE_TIMEOUT_SEC) -> tuple[str, dict] | None:
    """Return (device identifier, connection properties) once the phone answers.

    The phone drops off whenever it sleeps deeply or leaves the LAN, and
    launchd fires at a fixed hour regardless, so a short poll turns most
    "phone was napping" misses into successes.

    Note the trap: `list devices` reports a cached `tunnelState`, and it says
    "disconnected" for a phone that is perfectly reachable, because the tunnel
    is only brought up on demand. Asking for device details is what actually
    establishes it, so that call is the reachability test. Trusting the listing
    would make this job give up on a working phone every time.
    """
    deadline = time.monotonic() + wait_sec
    while True:
        listing = devicectl_json(["list", "devices"]) or {}
        candidates = [
            d["identifier"]
            for d in listing.get("devices", [])
            if d.get("connectionProperties", {}).get("pairingState") == "paired"
        ]
        if pinned:
            candidates = [c for c in candidates if c == pinned]
        for identifier in candidates:
            props = device_connection(identifier)
            if props and props.get("tunnelState") == "connected":
                return identifier, props
        if time.monotonic() >= deadline:
            return None
        time.sleep(15)


def device_connection(identifier: str) -> dict | None:
    result = devicectl_json(["device", "info", "details", "--device", identifier])
    if not result:
        return None
    return result.get("connectionProperties", {})


def sideloaded_bundle_ids(identifier: str) -> set[str] | None:
    """Bundle ids on the phone that came from a developer build, not the store.

    Returns None when the device could not be queried, which the caller must
    treat differently from "the app is gone": an empty answer would otherwise
    look like Alex deleted everything.
    """
    result = devicectl_json(["device", "info", "apps", "--device", identifier])
    if not result:
        return None
    return {
        a["bundleIdentifier"] for a in result.get("apps", []) if a.get("builtByDeveloper")
    }


# --------------------------------------------------------------------------
# build + install


def discover_app(search_root: Path, bundle_id: str, newer_than: float) -> Path | None:
    """Newest signed device build of `bundle_id` under `search_root`.

    Deliberately discovered rather than configured: the Products directory
    holds Debug, Release and simulator variants of the same bundle id, and
    which one a scheme emits changes without warning. `-iphoneos` filters the
    simulator out, `embedded.mobileprovision` proves it was signed, and the
    mtime floor proves it came from the build we just ran.
    """
    candidates = []
    for app in search_root.rglob("*.app"):
        if "-iphoneos" not in app.parent.name:
            continue
        if not (app / "embedded.mobileprovision").exists():
            continue
        if bundle_id_of(app) != bundle_id:
            continue
        mtime = app.stat().st_mtime
        if mtime + 1 < newer_than:
            continue
        candidates.append((mtime, app))
    if not candidates:
        return None
    return max(candidates)[1]


def build_app(cfg: dict) -> tuple[bool, str]:
    workdir = Path(os.path.expanduser(cfg["dir"]))
    cmd = cfg["build"]
    env = {**os.environ, "DEVELOPER_DIR": DEVELOPER_DIR, **cfg.get("env", {})}
    log(f"  building: {' '.join(cmd)} (cwd {workdir})")
    try:
        out = subprocess.run(
            cmd, cwd=workdir, env=env, capture_output=True, text=True, timeout=BUILD_TIMEOUT_SEC
        )
    except subprocess.TimeoutExpired:
        return False, f"build timed out after {BUILD_TIMEOUT_SEC}s"
    if out.returncode != 0:
        errors = [ln for ln in out.stdout.splitlines() + out.stderr.splitlines() if "error:" in ln]
        detail = errors[-1] if errors else (out.stderr.strip() or "no error line found").splitlines()[-1]
        return False, detail[:300]
    return True, ""


def install_app(udid: str, app_path: Path) -> tuple[bool, str]:
    out = run(["xcrun", "devicectl", "device", "install", "app", "--device", udid, str(app_path)])
    if out.returncode != 0:
        text = (out.stderr + out.stdout).strip().splitlines()
        detail = next((ln for ln in reversed(text) if ln.strip()), "install failed")
        return False, detail.strip()[:300]
    return True, ""


# --------------------------------------------------------------------------
# state


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def notify(message: str, title: str, sound: str, link: str, *extra: str) -> None:
    # mist-notify speaks the line aloud as well as raising the banner, which is
    # what the scheduled run should do and emphatically not what a manual run
    # in a terminal should do.
    if QUIET[0]:
        log(f"  (quiet) {title}: {message}")
        return
    if not NOTIFY.exists():
        log(f"  (notify unavailable) {title}: {message}")
        return
    subprocess.run([str(NOTIFY), message, title, sound, link, *extra], check=False)


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true", help="report the countdown, change nothing")
    ap.add_argument("--force", action="store_true", help="refresh every app regardless of expiry")
    ap.add_argument("--only", metavar="BUNDLE_ID", help="restrict to one app")
    ap.add_argument("--threshold-days", type=float, default=None)
    ap.add_argument("--quiet", action="store_true", help="suppress notifications (manual runs)")
    ap.add_argument(
        "--discover", action="store_true",
        help="list developer-signed apps on the phone and flag any missing from apps.json",
    )
    args = ap.parse_args()

    QUIET[0] = args.quiet
    config = load_json(CONFIG_PATH, None)
    if config is None:
        log(f"No config at {CONFIG_PATH}. Copy apps.example.json and fill it in (see README.md).")
        return 1

    if args.discover:
        found = find_device(config.get("deviceUdid"), wait_sec=30)
        if not found:
            log("Phone is not reachable. Unlock it on the home WiFi and try again.")
            return 1
        on_device = sideloaded_bundle_ids(found[0]) or set()
        known = {a["bundleId"] for a in config["apps"]}
        for bundle in sorted(on_device):
            note = "" if bundle in known else "   <- not in apps.json, cannot be refreshed"
            print(f"{bundle}{note}")
        return 0

    threshold = args.threshold_days or config.get("thresholdDays", DEFAULT_THRESHOLD_DAYS)
    state = load_json(STATE_PATH, {})
    apps = [a for a in config["apps"] if not args.only or a["bundleId"] == args.only]
    now = utcnow()

    # What does each app think its deadline is? state.json is what we actually
    # put on the phone; a local build is only a bootstrap guess for an app we
    # have never handled.
    plans = []
    for cfg in apps:
        known = state.get(cfg["bundleId"], {}).get("expiresAt")
        expires = dt.datetime.fromisoformat(known) if known else None
        source = "state"
        if expires is None:
            search = Path(os.path.expanduser(cfg.get("searchRoot", cfg["dir"])))
            found = discover_app(search, cfg["bundleId"], 0)
            expires = profile_expiry(found) if found else None
            source = "local build" if expires else "unknown"
        remaining = (expires - now).total_seconds() / 86400 if expires else -999
        plans.append({"cfg": cfg, "expires": expires, "remaining": remaining, "source": source})

    if args.status:
        for p in plans:
            when = f"{p['expires']:%Y-%m-%d %H:%M} UTC" if p["expires"] else "unknown"
            left = f"{p['remaining']:+.2f}d" if p["expires"] else "  n/a"
            print(f"{p['cfg']['name']:24} {left:>8}  expires {when}  ({p['source']})")
        return 0

    due = [p for p in plans if args.force or p["remaining"] < threshold]
    if not due:
        soonest = min(plans, key=lambda p: p["remaining"])
        log(f"Nothing due. Soonest is {soonest['cfg']['name']} in {soonest['remaining']:.1f}d.")
        return 0

    log(f"Due for refresh: {', '.join(p['cfg']['name'] for p in due)}")

    found = find_device(config.get("deviceUdid"))
    if not found:
        # Only nag when something is actually about to die, and at most daily,
        # because "unlock your phone" every evening trains him to ignore it.
        urgent = [p for p in due if p["remaining"] < 1]
        last_nag = state.get("_meta", {}).get("lastNagAt")
        nagged_today = last_nag and dt.datetime.fromisoformat(last_nag).date() == now.date()
        log("Phone is not reachable on the tunnel; will retry on the next run.")
        if urgent and not nagged_today:
            names = ", ".join(p["cfg"]["name"] for p in urgent)
            notify(
                f"{names} expires within a day and your phone is off the tunnel. "
                "Unlock it on the home WiFi and I will refresh it.",
                "Sideload expiring", "Basso", "console",
            )
            state.setdefault("_meta", {})["lastNagAt"] = now.isoformat()
            save_state(state)
        return 0

    udid, props = found
    log(f"Device {udid} reachable ({props.get('transportType')}, tunnel {props.get('tunnelState')}).")
    on_device = sideloaded_bundle_ids(udid)

    refreshed, failed, skipped = [], [], []
    for plan in due:
        cfg = plan["cfg"]
        name, bundle = cfg["name"], cfg["bundleId"]
        log(f"{name} ({bundle}): {plan['remaining']:.2f}d left, refreshing.")

        if on_device is not None and bundle not in on_device and not cfg.get("alwaysInstall"):
            log("  not on the device any more; leaving it uninstalled.")
            skipped.append(name)
            continue

        search = Path(os.path.expanduser(cfg.get("searchRoot", cfg["dir"])))
        evicted = evict_cached_profiles(bundle)
        prune_products(search, bundle)
        log(f"  evicted {evicted} cached profile(s), pruned old device builds")

        started = time.time()
        ok, err = build_app(cfg)
        if not ok:
            log(f"  BUILD FAILED: {err}")
            failed.append((name, f"build: {err}", cfg))
            continue

        app_path = discover_app(search, bundle, started)
        if not app_path:
            log("  build succeeded but no signed device .app appeared")
            failed.append((name, "no signed .app found after build", cfg))
            continue

        expires = profile_expiry(app_path)
        # Belt and braces: if the rebuild handed back a profile that is still
        # inside the danger window, something upstream refused to renew and
        # installing it would reset nothing while looking like a success.
        if expires is None or (expires - now).total_seconds() / 86400 < threshold:
            when = f"{expires:%Y-%m-%d}" if expires else "unreadable"
            log(f"  profile did not renew (expires {when}); refusing to install")
            failed.append((name, f"profile did not renew (expires {when})", cfg))
            continue

        ok, err = install_app(udid, app_path)
        if not ok:
            log(f"  INSTALL FAILED: {err}")
            failed.append((name, f"install: {err}", cfg))
            continue

        log(f"  installed, good until {expires:%Y-%m-%d %H:%M} UTC")
        state[bundle] = {
            "expiresAt": expires.isoformat() if expires else None,
            "installedAt": now.isoformat(),
            "appPath": str(app_path),
        }
        refreshed.append((name, expires))
        save_state(state)

    save_state(state)

    if refreshed and not failed:
        names = ", ".join(n for n, _ in refreshed)
        soonest = min(e for _, e in refreshed if e)
        notify(
            f"Refreshed {names}. Signed for another 7 days, good until {soonest:%b %-d}.",
            "Sideloads refreshed", "Purr", "console",
        )
    if failed:
        first, reason, cfg = failed[0]
        others = f" (+{len(failed) - 1} more)" if len(failed) > 1 else ""
        notify(
            f"Could not refresh {first}{others}. {reason}",
            "Sideload refresh failed", "Basso",
            os.path.expanduser(cfg["dir"]),
        )
    if skipped:
        log(f"Skipped (not installed): {', '.join(skipped)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
