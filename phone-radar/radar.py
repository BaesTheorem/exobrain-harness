#!/usr/bin/env python3
"""MIST Radar: find your phone by Bluetooth signal strength.

A small pywebview window shows nearby BLE devices; lock onto one (your
phone) and a big MIST face tells you warmer/colder as you walk around
with the laptop. RSSI only; nothing connects to anything.
"""

import asyncio
import logging
import math
import os
import threading
import time

import webview
from bleak import BleakScanner

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.expanduser("~/Library/Logs/exobrain/mist-radar.log")

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("mist-radar")

APPLE_COMPANY_ID = 0x004C
STALE_PRUNE_SEC = 60.0
# Address-rotation and coalescing safety net: restart the scan periodically
# even when the duplicates patch is active.
SCAN_RESTART_SEC = 10.0
EMA_TAU = 1.2  # seconds


def patch_bleak_allow_duplicates():
    """bleak's CoreBluetooth backend scans with options=None, so macOS
    coalesces advertisements and RSSI only arrives on first sight. Re-scan
    with CBCentralManagerScanOptionAllowDuplicatesKey to get a live stream.
    """
    try:
        from bleak.backends.corebluetooth import CentralManagerDelegate as cmd
        from CoreBluetooth import (
            CBUUID,
            CBCentralManagerScanOptionAllowDuplicatesKey,
        )
        from Foundation import NSArray, NSDictionary, NSNumber

        async def start_scan(self, service_uuids):
            uuids = (
                NSArray.alloc().initWithArray_(
                    [CBUUID.UUIDWithString_(u) for u in service_uuids]
                )
                if service_uuids
                else None
            )
            opts = NSDictionary.dictionaryWithObject_forKey_(
                NSNumber.numberWithBool_(True),
                CBCentralManagerScanOptionAllowDuplicatesKey,
            )
            self.central_manager.scanForPeripheralsWithServices_options_(uuids, opts)

        cmd.CentralManagerDelegate.start_scan = start_scan
        return True
    except Exception:
        log.exception("allow-duplicates patch failed; falling back to restarts")
        return False


class Radar:
    def __init__(self):
        self._lock = threading.Lock()
        self._devices = {}
        self.status = "starting"

    def _on_adv(self, device, adv):
        now = time.monotonic()
        with self._lock:
            d = self._devices.get(device.address)
            if d is None:
                d = {
                    "id": device.address,
                    "name": None,
                    "apple": False,
                    "rssi": adv.rssi,
                    "ema": float(adv.rssi),
                    "last": now,
                    "hist": [],
                }
                self._devices[device.address] = d
            dt = now - d["last"]
            alpha = 1.0 - math.exp(-max(dt, 0.05) / EMA_TAU)
            d["ema"] += alpha * (adv.rssi - d["ema"])
            d["rssi"] = adv.rssi
            d["last"] = now
            # Advertised name wins; fall back to macOS's cached name for
            # known/paired devices (iPhones advertise anonymously, so most
            # Apple gear shows no name at all).
            if adv.local_name:
                d["name"] = adv.local_name
            elif device.name and not d["name"]:
                d["name"] = device.name
            if adv.manufacturer_data and APPLE_COMPANY_ID in adv.manufacturer_data:
                d["apple"] = True
            d["hist"].append((now, d["ema"]))
            cutoff = now - 8.0
            while d["hist"] and d["hist"][0][0] < cutoff:
                d["hist"].pop(0)

    async def _scan_forever(self):
        self.status = "scanning"
        while True:
            try:
                async with BleakScanner(self._on_adv):
                    await asyncio.sleep(SCAN_RESTART_SEC)
            except Exception as e:
                self.status = f"bluetooth error: {e}"
                log.exception("scan cycle failed; retrying in 3s")
                await asyncio.sleep(3.0)
            else:
                self.status = "scanning"
                with self._lock:
                    log.info("scan cycle ok: %d devices in range", len(self._devices))
            now = time.monotonic()
            with self._lock:
                for addr in [
                    a
                    for a, d in self._devices.items()
                    if now - d["last"] > STALE_PRUNE_SEC
                ]:
                    del self._devices[addr]

    def run_in_thread(self):
        t = threading.Thread(
            target=lambda: asyncio.run(self._scan_forever()), daemon=True
        )
        t.start()

    # ---- pywebview JS API ----

    def get_state(self):
        now = time.monotonic()
        with self._lock:
            devices = [
                {
                    "id": d["id"],
                    "name": d["name"],
                    "apple": d["apple"],
                    "rssi": d["rssi"],
                    "ema": round(d["ema"], 1),
                    "age": round(now - d["last"], 2),
                    "trend": self._trend(d, now),
                }
                for d in self._devices.values()
            ]
        devices.sort(key=lambda d: -d["ema"])
        return {"status": self.status, "devices": devices}

    @staticmethod
    def _trend(d, now):
        """dB change over the last ~4s of EMA history; + means warmer."""
        past = [e for t, e in d["hist"] if t <= now - 3.0]
        if not past:
            return 0.0
        return round(d["ema"] - past[-1], 1)


def main():
    patched = patch_bleak_allow_duplicates()
    log.info("starting (allow-duplicates patch: %s)", patched)
    radar = Radar()
    radar.run_in_thread()
    webview.create_window(
        "MIST Radar",
        url=os.path.join(APP_DIR, "ui.html"),
        js_api=radar,
        width=430,
        height=640,
        min_size=(360, 480),
        background_color="#111318",
    )
    webview.start()


if __name__ == "__main__":
    main()
