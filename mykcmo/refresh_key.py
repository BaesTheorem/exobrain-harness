"""Rebuild civic-config.json from the current myKCMO Android APK.

The MyCivic API signs requests with a key that is hard-coded in the app. When
the vendor ships an app update with a new key, every signed call returns 403
"Signature Verification Failed". This script downloads the newest APK,
decompiles only the classes that hold the key, the city id and the app
version, proves the new values work with one signed read, and only then
writes the config.

    refresh_key.py           refresh from a new APK, write the config if it works
    refresh_key.py --check   signed probe with the current config; exit 2 if rejected
    refresh_key.py --auto    --check, and refresh only when the key is rejected
    refresh_key.py --auto --notify
                             the weekly launchd form: banner + Discord DM on a
                             rotation (fixed or not), then rebuild the KC 311
                             iPhone app so it carries the new key

INVARIANTS:
- The config is written only after a signed get_main call succeeds with it.
- Exit codes: 0 ok, 1 refresh failed, 2 key rejected (--check only).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import civicapi

PACKAGE = "com.civicapps.kansascitymo"
CLASSES = {
    "key": ("com.my.city.app.apicontroller.WebServiceController", r'String KEY = "([^"]+)"'),
    "city_id": ("com.my.city.app.utils.Utils", r'String city_UDID = "([0-9a-f]{32})"'),
    "app_version": ("com.my.city.app.BuildConfig", r'String APP_VERSION = "([^"]+)"'),
}


def log(msg: str) -> None:
    print(f"[mykcmo-refresh-key] {msg}", file=sys.stderr)


def download_apk(work: Path) -> Path:
    # APKPure is the source that works without a Google account. The APK is
    # only decompiled here, never installed or run.
    subprocess.run(
        ["apkeep", "-d", "apk-pure", "-o", "acknowledge_dangers=true", "-a", PACKAGE, str(work)],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    apks = sorted(work.glob(f"{PACKAGE}*.apk")) or sorted(work.glob(f"{PACKAGE}*.xapk"))
    if not apks:
        raise RuntimeError("apkeep finished but wrote no APK")
    return apks[0]


def extract(apk: Path, work: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for name, (cls, pattern) in CLASSES.items():
        out = work / f"{cls}.java"
        subprocess.run(
            ["jadx", "--single-class", cls, "--single-class-output", str(out), str(apk)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if out.exists() and (m := re.search(pattern, out.read_text())):
            found[name] = m.group(1)
    missing = [n for n in CLASSES if n not in found]
    if missing:
        # Class names moved (new obfuscation or a refactor). Fall back to a
        # full decompile and search every source file for the same patterns.
        log(f"single-class lookup missed {missing}; decompiling the whole APK")
        src = work / "src"
        subprocess.run(
            ["jadx", "-d", str(src), "--no-res", "-j", "8", str(apk)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for path in src.rglob("*.java"):
            text = path.read_text(errors="ignore")
            for name in list(missing):
                if m := re.search(CLASSES[name][1], text):
                    if name != "key" or "hmacShaKeyFor" in text:
                        found[name] = m.group(1)
                        missing.remove(name)
            if not missing:
                break
    if missing:
        raise RuntimeError(f"could not find {missing} in the decompiled APK")
    return found


def refresh() -> int:
    old = json.loads(civicapi.CONFIG_PATH.read_text()) if civicapi.CONFIG_PATH.exists() else {}
    work = Path(tempfile.mkdtemp(prefix="mykcmo-apk-"))
    try:
        log("downloading the newest APK")
        apk = download_apk(work)
        log(f"decompiling {apk.name}")
        values = extract(apk, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    cfg = {
        **old,
        **values,
        "package": PACKAGE,
        "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    cfg.setdefault("device_uid", "")
    if not cfg["device_uid"]:
        cfg["device_uid"] = civicapi.uuid.uuid4().hex[:16]
    try:
        ok = civicapi.check(cfg)
    except civicapi.CivicError as exc:
        log(f"the new values do not work either: {exc}")
        return 1
    if not ok:
        log("signed probe did not return success; config not written")
        return 1
    civicapi.CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    changed = [k for k in CLASSES if old.get(k) != cfg[k]]
    log(f"config written to {civicapi.CONFIG_PATH}; changed: {', '.join(changed) or 'nothing'}")
    print(json.dumps({"ok": True, "changed": changed, "app_version": cfg["app_version"]}))
    return 0


def check() -> int:
    try:
        ok = civicapi.check()
    except civicapi.KeyRejected as exc:
        log(f"key rejected: {exc}")
        return 2
    except civicapi.CivicError as exc:
        log(str(exc))
        return 2 if "missing" in str(exc) else 1
    log("signed probe OK" if ok else "signed probe returned no success")
    return 0 if ok else 1


HARNESS = civicapi.HERE.parent
NOTIFY = HARNESS / "mist-voice" / "bin" / "mist-notify"
APP_INSTALL = Path.home() / "Documents" / "kc311" / "ios" / "scripts" / "install.sh"


def notify(msg: str, context: str) -> None:
    subprocess.run(
        [str(NOTIFY), msg, "myKCMO API key", "Glass", str(civicapi.CONFIG_PATH),
         "--discord", "--context", context],
        check=False,
    )


def rebuild_app() -> str:
    if not APP_INSTALL.exists():
        return "no KC 311 app to rebuild"
    run = subprocess.run([str(APP_INSTALL)], capture_output=True, text=True)
    tail = (run.stdout + run.stderr).strip().splitlines()[-3:]
    return ("app rebuilt and installed" if run.returncode == 0 else "app rebuild FAILED") + ": " + " | ".join(tail)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="probe the current config only")
    ap.add_argument("--auto", action="store_true", help="refresh only when the key is rejected")
    ap.add_argument("--notify", action="store_true", help="with --auto: notify and rebuild the app on rotation")
    args = ap.parse_args()
    if args.check:
        return check()
    if args.auto:
        status = check()
        if status != 2:
            if status == 1 and args.notify:
                notify("myKCMO API probe failed (not a key rejection). Check the log.", "mykcmo-refresh-key --auto: probe failed")
            return status
        result = refresh()
        if args.notify:
            if result == 0:
                notify(f"The city rotated the myKCMO API key. New key pulled from the APK. {rebuild_app()}.",
                       "mykcmo-refresh-key --auto: key rotated, refresh OK")
            else:
                notify("The myKCMO API key rotated and the auto-refresh FAILED. KC 311 app and MCP filing are down.",
                       "mykcmo-refresh-key --auto: key rotated, refresh failed; run mykcmo/bin/mykcmo-refresh-key by hand")
        return result
    return refresh()


if __name__ == "__main__":
    sys.exit(main())
