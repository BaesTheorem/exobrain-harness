#!/usr/bin/env python3
"""
kqi_ble.py -- talk to a NIU KQi scooter (KQi Air and friends) over Bluetooth LE.

Run it through bin/kqi, which launches it inside the "NIU KQi" app bundle so
macOS attributes the Bluetooth use to something that carries an
NSBluetoothAlwaysUsageDescription (a bare python process gets SIGABRT'd by TCC).

Cloud side (one time):
    kqi login you@example.com          # NIU account; password prompted
    kqi scooters                       # vehicles bound to the account
    kqi setup [--sn SN]                # fetch the scooter's BLE password -> secrets/scooter.json

Bluetooth side (scooter powered on, within range):
    kqi find                           # which advertisement is the scooter
    kqi status                         # battery, speed, mode, settings, firmware
    kqi read foc_k_gears db_k_sn ...   # any field by name (kqi fields lists them)
    kqi write foc_k_max_speed 200      # any field (asks first; --yes to skip)
    kqi lock | unlock | on | off       # motor lock, dashboard power
    kqi cruise on|off  kickstart on|off  fastlock on|off  alarm on|off
    kqi ebs 0..3  unit 0|1  custom on|off [--max KMH]  daylight on|off|led
    kqi clock                          # set the scooter clock to now
    kqi cmd 7 | kqi cmd --db 1         # raw foc_k_cmd / db_k_cmd numbers
    kqi monitor [--seconds N]          # print frames the scooter pushes on its own
    kqi raw 0121...                    # send a hex frame and print what comes back

The wire protocol lives in niu_proto.py; niu_cloud.py does the credential
fetch.  Everything was recovered from the NIU Android app (5.12.2).
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
import time

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

import niu_cloud as C
import niu_proto as P

RESPONSE_TIMEOUT = 4.0
INTER_FRAME_DELAY = 0.005

# What `status` reads, in request-sized groups (one 16-byte block holds 5 codes).
STATUS_GROUPS = [
    ["db_k_sn", "db_k_sw_ver", "db_k_hw_ver", "db_k_f_code", "db_k_estimated_mileage"],
    ["db_k_realtime_status", "db_k_function_status", "db_k_function_cfg", "bms_soc_rt", "bms_dc_fl_t_rt"],
    ["foc_k_s_ver", "foc_k_h_ver", "foc_k_sn", "foc_k_gears", "foc_k_rt_speed"],
    ["foc_k_function_status1", "foc_k_realtime_status1", "foc_k_lighting_control_status", "foc_k_max_speed", "foc_k_def_max_speed"],
    ["foc_k_throttle_mode_set", "foc_k_no_zero_start", "foc_k_automatic_shutdown_en", "foc_k_decorative_light_mode", "foc_k_assist_max_speed"],
    ["bms_sn_id", "bms_s_ver_n", "bms_h_ver_n", "bms_c_cont", "bms_soh_rt"],
    ["bms_rated_vlt", "bms_long_life_soc", "ecu_bt_ver", "ecu_bt_status", "db_k_timestamp"],
]

# Bit meanings recovered from the app.  (?) = a guess that live testing still has to confirm.
BITS = {
    "foc_k_function_status1": {
        1: "speed unit index 1 (mph?)", 2: "kick-start required (non-zero start)", 4: "cruise control",
        256: "EBS bit A", 512: "EBS bit B", 1024: "bit 1024 (?)", 2048: "custom ride mode",
        8192: "novice course done", 32768: "fast lock supported", 65536: "fast lock on",
        131072: "dynamic mode (newer firmware)",
    },
    "foc_k_realtime_status1": {2048: "ride records waiting to sync", 4096: "fault records waiting to sync"},
    "db_k_realtime_status": {1: "powered on"},
    "db_k_function_status": {2: "alarm sound OFF (bit clear = on)"},
}

# Commands the app sends for a kick scooter: (field, value)
FOC, DB = "foc_k_cmd", "db_k_cmd"
COMMANDS = {
    "lock": (FOC, 1), "unlock": (FOC, 2),
    "on": (DB, 1), "off": (DB, 2),
    "alarm on": (DB, 6), "alarm off": (DB, 5),
    "kickstart on": (FOC, 5), "kickstart off": (FOC, 6),
    "cruise on": (FOC, 7), "cruise off": (FOC, 8),
    "unit 0": (FOC, 12), "unit 1": (FOC, 13),
    "fastlock on": (FOC, 18), "fastlock off": (FOC, 19),
    "daylight on": (DB, 9), "daylight off": (DB, 10), "daylight led": (DB, 11),
    "factory-reset": (DB, 100),
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ----------------------------------------------------------------------------- BLE session

class Scooter:
    def __init__(self, sc: dict, address: str | None = None, family: str = "auto", verbose: bool = False):
        self.sc = sc
        self.ble = sc.get("ble", {})
        self.address = address or sc.get("cb_address")
        self.family_opt = family
        self.verbose = verbose
        self.client: BleakClient | None = None
        self.service = ""
        self.ble_ver = 0
        self.notify_uuid = self.write_uuid = ""
        self.key = ""          # AES key for family-1 data frames ("" = plaintext)
        self.rx: asyncio.Queue[str] = asyncio.Queue()
        self.pushes: list[str] = []
        self._buf = ""

    # --- discovery -----------------------------------------------------------
    def _matches(self, dev, adv) -> tuple[int, str]:
        """Score an advertisement: 0 = no, higher = better."""
        mac = self.ble.get("mac", "").replace(":", "").lower()
        macrev = "".join(reversed([mac[i:i + 2] for i in range(0, 12, 2)])) if mac else ""
        name = (adv.local_name or dev.name or "") or ""
        bname = self.ble.get("name", "")
        score, why = 0, []
        if bname and name.lower() == bname.lower():
            score += 10; why.append(f"name {name!r}")
        elif name.upper().startswith("NIU"):
            score += 3; why.append(f"NIU-ish name {name!r}")
        blobs = [v.hex() for v in adv.manufacturer_data.values()] + [v.hex() for v in adv.service_data.values()]
        if mac and any(mac in b or macrev in b for b in blobs):
            score += 8; why.append("MAC in advertisement")
        if any(u.lower() in P.SERVICES for u in adv.service_uuids):
            score += 6; why.append("NIU service UUID")
        return score, ", ".join(why)

    async def find_all(self, timeout: float = 10.0) -> list[tuple]:
        """Every advertisement that looks like the scooter: (score, rssi, device, adv, why)."""
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        hits = []
        for dev, adv in found.values():
            score, why = self._matches(dev, adv)
            if score:
                hits.append((score, adv.rssi or -999, dev, adv, why))
        hits.sort(key=lambda h: (-h[0], -h[1]))
        return hits

    async def find(self, timeout: float = 10.0) -> BLEDevice:
        hits = await self.find_all(timeout)
        if not hits:
            raise BleakError("scooter not seen; is it powered on and within range? (try `kqi scan`)")
        if len(hits) > 1 and hits[0][0] == hits[1][0]:
            log("several candidates, taking the strongest signal:")
            for h in hits:
                log(f"  {h[1]:5d} dBm  {h[2].address}  {h[4]}")
        return hits[0][2]

    # --- connection ----------------------------------------------------------
    async def connect(self, timeout: float = 20.0) -> None:
        target: BLEDevice | str
        if self.address:
            target = self.address
        else:
            dev = await self.find()
            target = dev
            self.sc["cb_address"] = dev.address
            C.save_scooter(self.sc)
            log(f"found scooter at {dev.address}")
        self.client = BleakClient(target, timeout=timeout)
        try:
            await self.client.connect()
        except BleakError as e:
            if self.address:
                log(f"cached address failed ({e}); scanning again")
                self.address = None
                self.sc.pop("cb_address", None)
                return await self.connect(timeout)
            raise
        svc = None
        for s in self.client.services:
            if s.uuid.lower() in P.SERVICES:
                svc = s
                break
        if svc is None:
            uuids = ", ".join(s.uuid for s in self.client.services)
            await self.client.disconnect()
            raise BleakError(f"no NIU service on this device (services: {uuids})")
        self.service = svc.uuid.lower()
        self.ble_ver = P.SERVICES[self.service]
        self.notify_uuid, self.write_uuid = P.chars_for(self.service)
        if self.verbose:
            log(f"service {self.service} (bleVer {self.ble_ver}), mtu {getattr(self.client, 'mtu_size', '?')}")
        await self.client.start_notify(self.notify_uuid, self._on_notify)
        await self.handshake()

    async def disconnect(self) -> None:
        if self.client and self.client.is_connected:
            try:
                await self.client.stop_notify(self.notify_uuid)
            except Exception:
                pass
            await self.client.disconnect()

    def _on_notify(self, _handle, data: bytearray) -> None:
        h = bytes(data).hex()
        if self.verbose:
            log(f"  <- {h}")
        if self._buf or h.startswith("5aa5"):
            self._buf += h
            if P.frame_5aa5_complete(self._buf):
                need = (int(self._buf[4:8], 16) + 4) * 2
                self.rx.put_nowait(self._buf[:need])
                self._buf = self._buf[need:]
            return
        if len(h) % 40 == 0:
            for i in range(0, len(h), 40):
                self.rx.put_nowait(h[i:i + 40])
        else:
            self.rx.put_nowait(h)

    async def _write(self, frame_hex: str) -> None:
        if self.client is None:
            raise BleakError("not connected")
        if self.verbose:
            log(f"  -> {frame_hex}")
        data = bytes.fromhex(frame_hex)
        mtu = max(20, getattr(self.client, "mtu_size", 23) - 3)
        for i in range(0, len(data), mtu):
            await self.client.write_gatt_char(self.write_uuid, data[i:i + mtu], response=True)

    async def send(self, frames: list[str]) -> None:
        """Write raw frames, parking any unsolicited frames that arrived meanwhile."""
        while not self.rx.empty():
            self.pushes.append(self.rx.get_nowait())
        for i, f in enumerate(frames):
            await self._write(f)
            if i < len(frames) - 1:
                await asyncio.sleep(INTER_FRAME_DELAY)

    async def _next(self, headers: set[str] | None, timeout: float = RESPONSE_TIMEOUT) -> str:
        """Next frame whose header is in `headers` (None = any); pushes are kept aside."""
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("no reply from scooter")
            fr = await asyncio.wait_for(self.rx.get(), left)
            if headers is None or fr[:4].lower() in headers:
                return fr
            self.pushes.append(fr)
            if self.verbose:
                log(f"  (push {fr[:4]} set aside)")

    # --- authentication --------------------------------------------------------
    async def handshake(self) -> None:
        pwd = self.ble.get("password", "")
        if not pwd:
            log("no BLE password on file; skipping verify (works only on vehicles that need none)")
            self.key = ""
            return
        if len(pwd) != 16:
            raise P.NiuError("blePassword must be 16 characters")
        if self.ble_ver >= 20:
            fk, r1 = P.first_key(pwd, self.ble.get("mac"))
            await self.send([P.hs1_v2(fk)])
            reply = P.hs1_v2_parse(await self._next({"01b4", "01d4", "01f4"}), fk)
            if reply[:8].lower() != r1:
                raise P.NiuError("verify step 1: random code mismatch")
            await self.send([P.hs2_v2(reply, r1)])
            r2 = P.hs2_v2_parse(await self._next({"0194", "01d4"}), reply)
            if r2[:8].lower() != r1:
                raise P.NiuError("verify step 2: random code mismatch")
            self.key = reply
        else:
            fr1, rnd = P.hs1_v1(pwd)
            await self.send([fr1])
            reply = P.hs1_v1_parse(await self._next({"01a3", "01c3"}), pwd)
            await self.send([P.hs2_v1(rnd, reply, pwd)])
            P.hs2_v1_parse(await self._next({"0183", "01c3"}), pwd)
            aes = self.ble.get("aes", "")
            self.key = aes if len(aes) in (16, 32) else ""
        if self.verbose:
            log("verified with the scooter")

    # --- field traffic ---------------------------------------------------------
    def _families(self) -> list[int]:
        if self.family_opt != "auto":
            return [int(self.family_opt)]
        return [1, 10] if self.ble_ver >= 21 else [1]

    async def read(self, names: list[str]) -> dict:
        last: Exception | None = None
        for fam in self._families():
            try:
                if fam == 10:
                    await self.send([P.build_read_5aa5(names)])
                    fr = await self._next({"5aa5"})
                    _, data = P.parse_5aa5(fr, P.CMD_READ)
                    return P.parse_fields_sequential(data, names)
                h = P.HEADERS[fam]
                await self.send(P.build_read(names, self.key, fam))
                frames = []
                while True:
                    fr = await self._next(set(h["read_ack"]) | set(h["read_err"]))
                    frames.append(fr)
                    if P.is_last_frame(fr) or fr[:4].lower() in h["read_err"]:
                        break
                return P.parse_read_frames(frames, names, self.key, fam)
            except TimeoutError as e:
                last = e
                if self.verbose:
                    log(f"family {fam}: {e}")
        raise last or TimeoutError("read failed")

    async def write(self, values: dict) -> None:
        last: Exception | None = None
        for fam in self._families():
            try:
                if fam == 10:
                    await self.send([P.build_write_5aa5(values)])
                    P.parse_5aa5(await self._next({"5aa5"}), P.CMD_WRITE)
                    return
                h = P.HEADERS[fam]
                await self.send(P.build_write(values, self.key, fam))
                frames = []
                while True:
                    fr = await self._next(set(h["write_ack"]) | set(h["write_err"]))
                    frames.append(fr)
                    if P.is_last_frame(fr) or fr[:4].lower() in h["write_err"]:
                        break
                rc = P.parse_write_frames(frames, self.key, fam)
                if rc != "00":
                    raise P.NiuError(f"scooter answered the write with result {rc}")
                return
            except TimeoutError as e:
                last = e
        raise last or TimeoutError("write failed")

    async def command(self, fld: str, value: int) -> None:
        await self.write({fld: value})

    def decode_push(self, fr: str) -> dict | str:
        try:
            if fr[:4].lower() == "5aa5":
                _, data = P.parse_5aa5(fr)
                return P.parse_fields_coded(data)
            if fr[:4].lower() in P.PUSH_HEADERS and len(fr) == 40:
                return P.parse_push(fr, self.key)
        except P.NiuError as e:
            return f"{fr} ({e})"
        return fr


# ----------------------------------------------------------------------------- output helpers

def fmt_bits(name: str, value) -> str:
    if not isinstance(value, int) or name not in BITS:
        return ""
    on = [label for bit, label in BITS[name].items() if value & bit]
    if name == "foc_k_function_status1":
        lvl = (1 if value & 256 else 0) + (2 if value & 512 else 0)
        on = [o for o in on if not o.startswith("EBS bit")] + [f"EBS level {lvl}"]
    return "; ".join(on)


def print_fields(values: dict, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(values, indent=1, sort_keys=True))
        return
    width = max((len(k) for k in values), default=10)
    for k, v in values.items():
        extra = fmt_bits(k, v)
        if k in ("foc_k_rt_speed",) and isinstance(v, int):
            extra = f"{v / 10:.1f} km/h"
        if k in ("foc_k_max_speed", "foc_k_def_max_speed", "foc_k_assist_max_speed", "foc_k_assist_def_max_speed", "foc_k_no_zero_start") and isinstance(v, int):
            extra = f"{v / 10:.1f} km/h"
        if k == "db_k_timestamp" and isinstance(v, int) and v > 0:
            extra = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v))
        if k == "db_k_estimated_mileage" and isinstance(v, int):
            extra = f"{v / 100:.2f} km (if /100)"
        if isinstance(v, int) and k not in ("bms_soc_rt",) and v >= 256 and not extra:
            extra = f"0x{v:x}"
        print(f"{k:<{width}}  {v!s:<24} {extra}")


def confirm(prompt: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        log(f"{prompt} (not a terminal; pass --yes to proceed)")
        return False
    return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")


# ----------------------------------------------------------------------------- commands

async def with_scooter(args, fn):
    sc = C.load_scooter()
    s = Scooter(sc, address=args.address, family=args.family, verbose=args.verbose)
    await s.connect()
    try:
        return await fn(s)
    finally:
        await s.disconnect()


async def cmd_scan(args):
    found = await BleakScanner.discover(timeout=args.seconds, return_adv=True)
    rows = sorted(found.values(), key=lambda da: -(da[1].rssi or -999))
    for dev, adv in rows:
        mfr = " ".join(f"{k:04x}:{v.hex()}" for k, v in adv.manufacturer_data.items())
        sdata = " ".join(f"{k}:{v.hex()}" for k, v in adv.service_data.items())
        print(f"{adv.rssi:5d}  {dev.address}  name={adv.local_name!r}/{dev.name!r}  svcs={adv.service_uuids}  mfr=[{mfr}]  sdata=[{sdata}]")
    log(f"-- {len(rows)} devices in {args.seconds}s")


async def cmd_find(args):
    sc = C.load_scooter()
    s = Scooter(sc)
    hits = await s.find_all(timeout=args.seconds)
    if not hits:
        print("no advertisement matched the scooter (name, MAC, or NIU service UUID)")
        return 1
    for score, rssi, dev, adv, why in hits:
        print(f"{rssi:5d} dBm  score {score:2d}  {dev.address}  name={adv.local_name!r}  {why}")
    best = hits[0][2]
    sc["cb_address"] = best.address
    C.save_scooter(sc)
    print(f"remembered {best.address} as the scooter")
    return 0


async def cmd_status(args):
    async def go(s: Scooter):
        out = {}
        for group in STATUS_GROUPS:
            try:
                out.update(await s.read(group))
            except (P.NiuError, TimeoutError) as e:
                log(f"group {group[0]}..: {e}; reading one at a time")
                for name in group:
                    try:
                        out.update(await s.read([name]))
                    except (P.NiuError, TimeoutError) as e2:
                        out[name] = f"<{e2}>"
        print_fields(out, args.json)
        if s.pushes and args.verbose:
            for fr in s.pushes:
                log(f"push: {s.decode_push(fr)}")
    return await with_scooter(args, go)


async def cmd_read(args):
    for n in args.field:
        P.field(n)

    async def go(s: Scooter):
        out = {}
        for i in range(0, len(args.field), 5):
            out.update(await s.read(args.field[i:i + 5]))
        print_fields(out, args.json)
    return await with_scooter(args, go)


async def cmd_write(args):
    spec = P.field(args.field)
    P.encode_value(spec, args.value)
    if not confirm(f"write {args.field} = {args.value} to the scooter?", args.yes):
        return 1

    async def go(s: Scooter):
        await s.write({args.field: args.value})
        print(f"ok: {args.field} = {args.value}")
        if args.readback:
            print_fields(await s.read([args.field]))
    return await with_scooter(args, go)


async def cmd_simple(args):
    key = args.cmd_name if args.arg is None else f"{args.cmd_name} {args.arg}"
    if key not in COMMANDS:
        opts = sorted(k for k in COMMANDS if k.split()[0] == args.cmd_name)
        log(f"usage: kqi {args.cmd_name} <{ '|'.join(o.split()[1] for o in opts) }>")
        return 2
    fld, val = COMMANDS[key]
    if key == "factory-reset" and not confirm("really factory-reset the scooter?", args.yes):
        return 1

    async def go(s: Scooter):
        await s.command(fld, val)
        print(f"ok: {key} ({fld}={val})")
    return await with_scooter(args, go)


async def cmd_cmd(args):
    fld = DB if args.db else FOC
    if not confirm(f"send {fld} = {args.number}?", args.yes):
        return 1

    async def go(s: Scooter):
        await s.command(fld, args.number)
        print(f"ok: {fld} = {args.number}")
    return await with_scooter(args, go)


async def cmd_ebs(args):
    async def go(s: Scooter):
        cur = (await s.read(["foc_k_function_status1"]))["foc_k_function_status1"]
        new = cur & ~(256 | 512)
        if args.level in (1, 3):
            new |= 256
        if args.level in (2, 3):
            new |= 512
        await s.write({"foc_k_function_status1": new})
        print(f"ok: EBS level {args.level} (function status {cur} -> {new})")
    return await with_scooter(args, go)


async def cmd_custom(args):
    async def go(s: Scooter):
        vals = {FOC: 10 if args.state == "on" else 11}
        if args.state == "on":
            if args.max is None:
                log("custom mode on needs --max KMH")
                return 2
            vals["foc_k_def_max_speed"] = int(round(args.max * 10))
        await s.write(vals)
        print(f"ok: custom mode {args.state}" + (f", max {args.max} km/h" if args.state == "on" else ""))
    return await with_scooter(args, go)


async def cmd_clock(args):
    async def go(s: Scooter):
        now = int(time.time())
        await s.write({"db_k_timestamp": now})
        print(f"ok: clock set to {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}")
    return await with_scooter(args, go)


async def cmd_monitor(args):
    async def go(s: Scooter):
        log(f"listening for {args.seconds}s (ride, press buttons, etc.)")
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            try:
                fr = await asyncio.wait_for(s.rx.get(), 1.0)
            except asyncio.TimeoutError:
                continue
            print(time.strftime("%H:%M:%S"), s.decode_push(fr))
    return await with_scooter(args, go)


async def cmd_raw(args):
    async def go(s: Scooter):
        await s.send([args.hex.lower()])
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            try:
                fr = await asyncio.wait_for(s.rx.get(), max(0.05, end - time.monotonic()))
            except asyncio.TimeoutError:
                break
            print(fr, s.decode_push(fr) if not args.plain else "")
    return await with_scooter(args, go)


# ----------------------------------------------------------------------------- cloud commands (no Bluetooth)

def cmd_login(args):
    pw = os.environ.get("NIU_PASSWORD") or ""
    if args.password_stdin:
        pw = sys.stdin.readline().rstrip("\n")
    if not pw:
        if not sys.stdin.isatty():
            log("no password: use --password-stdin, or set NIU_PASSWORD, or run from a terminal")
            return 2
        pw = getpass.getpass("NIU password: ")
    sess = C.login(args.account, pw)
    print(f"logged in as {sess['account']} (token expires {time.strftime('%Y-%m-%d %H:%M', time.localtime(sess['expires_at']))})")
    return 0


def cmd_scooters(args):
    sess = C.session()
    items = C.scooters(sess["token"])
    if args.json:
        print(json.dumps(items, indent=1))
        return 0
    if not items:
        print("no vehicles bound to this account")
        return 0
    for it in items:
        print(f"{it.get('sn_id', '?')}  {it.get('scooter_name', '')!r}  {it.get('product_type', '')}  {it.get('sku_name', '')}"
              + ("  (default)" if it.get("isDefault") else ""))
    return 0


def cmd_setup(args):
    sess = C.session()
    items = C.scooters(sess["token"])
    if args.sn:
        pick = next((i for i in items if i.get("sn_id") == args.sn), {"sn_id": args.sn})
    elif len(items) == 1:
        pick = items[0]
    elif items:
        pick = next((i for i in items if i.get("isDefault")), items[0])
        log(f"several vehicles; using {pick.get('sn_id')} ({pick.get('scooter_name')}). Pass --sn to choose.")
    else:
        log("no vehicles bound to this account; bind the scooter in the NIU app first")
        return 1
    sn = pick["sn_id"]
    info = C.bleinfo(sess["token"], sn)
    det = {}
    try:
        det = C.detail(sess["token"], sn)
    except C.CloudError as e:
        log(f"detail lookup failed ({e}); continuing")
    sc = C.load_json(C.SCOOTER_FILE) or {}
    sc.update({
        "sn": sn, "name": pick.get("scooter_name", ""), "product_type": pick.get("product_type") or det.get("product_type", ""),
        "sku": pick.get("sku_name") or det.get("sku_name", ""),
        "ble": {"mac": info.get("bleMac", ""), "password": info.get("blePassword", ""), "aes": info.get("bleAes", ""),
                "sign": info.get("bleSign", ""), "name": info.get("bleName", ""),
                "bus_protocol_type": info.get("bus_protocol_type", det.get("bus_protocol_type", 0))},
        "detail": {k: det.get(k) for k in ("scooter_type", "scooter_version", "carframe_id", "is_hid", "car_type", "bus_protocol_type") if k in det},
        "fetched_at": int(time.time()),
    })
    if sc.get("cb_address") and args.sn:
        sc.pop("cb_address", None)
    C.save_scooter(sc)
    b = sc["ble"]
    print(f"saved {C.SCOOTER_FILE}")
    print(f"  {sn}  {sc['name']!r}  {sc['product_type']}  {sc['sku']}")
    print(f"  BLE name {b['name']!r}  mac {b['mac']}  password {'yes' if b['password'] else 'NONE'}  aes {'yes' if b['aes'] else 'none'}  bus {b['bus_protocol_type']}")
    return 0


def cmd_fields(args):
    rows = sorted(P.FIELDS.items()) if args.all else sorted(P.KCONFIG.items())
    for name, spec in rows:
        if args.grep and args.grep not in name:
            continue
        print(f"{name:<40} {spec['code']}  {spec['type']:<8} {spec['len']}")
    return 0


# ----------------------------------------------------------------------------- main

def main() -> int:
    p = argparse.ArgumentParser(prog="kqi", description="NIU KQi scooter over Bluetooth LE")
    p.add_argument("--address", help="CoreBluetooth address of the scooter (skips scanning)")
    p.add_argument("--family", default="auto", choices=["auto", "1", "2", "10"], help="frame family override")
    p.add_argument("-v", "--verbose", action="store_true", help="print every frame")
    p.add_argument("--json", action="store_true", help="JSON output where it applies")
    p.add_argument("-y", "--yes", action="store_true", help="skip confirmations")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("login", help="log in to the NIU cloud"); s.add_argument("account"); s.add_argument("--password-stdin", action="store_true"); s.set_defaults(fn=cmd_login, sync=True)
    s = sub.add_parser("scooters", help="vehicles bound to the account"); s.set_defaults(fn=cmd_scooters, sync=True)
    s = sub.add_parser("setup", help="fetch the scooter's BLE credentials"); s.add_argument("--sn"); s.set_defaults(fn=cmd_setup, sync=True)
    s = sub.add_parser("fields", help="list known field names"); s.add_argument("--all", action="store_true"); s.add_argument("grep", nargs="?"); s.set_defaults(fn=cmd_fields, sync=True)

    s = sub.add_parser("scan", help="list everything advertising nearby"); s.add_argument("--seconds", type=float, default=8.0); s.set_defaults(fn=cmd_scan)
    s = sub.add_parser("find", help="find the scooter's advertisement"); s.add_argument("--seconds", type=float, default=10.0); s.set_defaults(fn=cmd_find)
    s = sub.add_parser("status", help="read the standard status set"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("read", help="read fields by name"); s.add_argument("field", nargs="+"); s.set_defaults(fn=cmd_read)
    s = sub.add_parser("write", help="write one field"); s.add_argument("field"); s.add_argument("value"); s.add_argument("--readback", action="store_true"); s.set_defaults(fn=cmd_write)
    for name in ("lock", "unlock", "on", "off", "factory-reset"):
        s = sub.add_parser(name); s.set_defaults(fn=cmd_simple, cmd_name=name, arg=None)
    for name in ("alarm", "kickstart", "cruise", "fastlock", "daylight", "unit"):
        s = sub.add_parser(name); s.add_argument("arg"); s.set_defaults(fn=cmd_simple, cmd_name=name)
    s = sub.add_parser("cmd", help="raw foc_k_cmd (or --db for db_k_cmd)"); s.add_argument("number", type=int); s.add_argument("--db", action="store_true"); s.set_defaults(fn=cmd_cmd)
    s = sub.add_parser("ebs", help="regen braking level 0-3"); s.add_argument("level", type=int, choices=[0, 1, 2, 3]); s.set_defaults(fn=cmd_ebs)
    s = sub.add_parser("custom", help="custom ride mode"); s.add_argument("state", choices=["on", "off"]); s.add_argument("--max", type=float, help="max speed km/h"); s.set_defaults(fn=cmd_custom)
    s = sub.add_parser("clock", help="set the scooter clock"); s.set_defaults(fn=cmd_clock)
    s = sub.add_parser("monitor", help="print pushed frames"); s.add_argument("--seconds", type=float, default=60.0); s.set_defaults(fn=cmd_monitor)
    s = sub.add_parser("raw", help="send a raw hex frame"); s.add_argument("hex"); s.add_argument("--seconds", type=float, default=3.0); s.add_argument("--plain", action="store_true"); s.set_defaults(fn=cmd_raw)

    args = p.parse_args()
    try:
        if getattr(args, "sync", False):
            rc = args.fn(args)
        else:
            rc = asyncio.run(args.fn(args))
    except (P.NiuError, C.CloudError, BleakError, TimeoutError) as e:
        log(f"kqi: {e}")
        return 1
    except KeyboardInterrupt:
        return 130
    return int(rc or 0)


if __name__ == "__main__":
    sys.exit(main())
