"""govee: control Govee lights on the LAN (UDP local API) via govee-local-api.

Commands:
    govee scan                      discover bulbs, refresh the device cache
    govee status [TARGET]           power, brightness, color of each bulb
    govee on|off [TARGET]
    govee brightness PCT [TARGET]   1-100
    govee color COLOR [TARGET]      name (red, warm), #rrggbb, or r,g,b
    govee temp KELVIN [TARGET]      2700-6500 on the H6008 (it clamps values outside)
    govee name DEVICE ALIAS         give a bulb a short name
    govee sync-names                copy the Govee app names into the aliases (cloud API)
    govee google-script             print a Google Home script: warm white by day, red at night

TARGET is "all" (default), an alias, an alias group, an IP, or the tail of the
device id. An alias group is the alias without its "-N" suffix ("vanity"
selects vanity-1 to vanity-4). Commas select several targets: "desk,vanity".

The device cache (data/devices.json, gitignored) keeps the IP and alias of each
bulb, so a command probes the known IPs directly and does not wait on a full
multicast scan.

INVARIANTS:
- The LAN API never acknowledges a command. A set command is fire-and-forget,
  so the CLI confirms only when --check reads status back.
- Each bulb must have "LAN Control" turned on in the Govee app, or it does not
  reply to a scan.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from govee_local_api import GoveeController, GoveeDevice  # pyright: ignore[reportMissingImports]

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "devices.json"
ENV = HERE.parent / ".env"
CLOUD = "https://openapi.api.govee.com/router/api/v1"
DISCOVERY_WAIT = 2.5
STATUS_WAIT = 1.5

NAMED_COLORS = {
    "red": (255, 0, 0),
    "orange": (255, 100, 0),
    "amber": (255, 160, 20),
    "yellow": (255, 220, 0),
    "green": (0, 255, 0),
    "teal": (0, 200, 150),
    "cyan": (0, 255, 255),
    "blue": (0, 0, 255),
    "purple": (140, 0, 255),
    "magenta": (255, 0, 255),
    "pink": (255, 80, 160),
    "white": (255, 255, 255),
}
NAMED_TEMPS = {"warm": 2700, "soft": 3000, "neutral": 4000, "daylight": 5500, "cool": 6500}


def load_cache() -> dict[str, dict]:
    if DATA.exists():
        return json.loads(DATA.read_text())
    return {}


def save_cache(cache: dict[str, dict]) -> None:
    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")


def parse_color(text: str) -> tuple[int, int, int]:
    t = text.strip().lower()
    if t in NAMED_COLORS:
        return NAMED_COLORS[t]
    if t.startswith("#") and len(t) == 7:
        return int(t[1:3], 16), int(t[3:5], 16), int(t[5:7], 16)
    parts = t.split(",")
    if len(parts) == 3 and all(p.strip().isdigit() for p in parts):
        rgb = tuple(int(p) for p in parts)
        if all(0 <= v <= 255 for v in rgb):
            return rgb  # type: ignore[return-value]
    raise SystemExit(f"govee: cannot read color {text!r} (use a name, #rrggbb, or r,g,b)")


async def discover(cache: dict[str, dict], full: bool) -> GoveeController:
    """Start a controller and wait until every cached bulb answers, or time runs out."""
    controller = GoveeController(
        loop=asyncio.get_running_loop(),
        discovery_enabled=full or not cache,
        discovery_interval=1,
        update_enabled=False,
    )
    for entry in cache.values():
        if entry.get("ip"):
            controller.add_device_to_discovery_queue(entry["ip"])
    await controller.start()
    controller.send_discovery_message()
    expected = sum(1 for e in cache.values() if e.get("ip"))
    deadline = asyncio.get_running_loop().time() + DISCOVERY_WAIT
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.1)
        if not full and expected and len(controller.devices) >= expected:
            break
    return controller


def remember(cache: dict[str, dict], devices: list[GoveeDevice]) -> None:
    for d in devices:
        entry = cache.setdefault(d.fingerprint, {})
        entry["ip"] = d.ip
        entry["sku"] = d.sku
    save_cache(cache)


def label(cache: dict[str, dict], d: GoveeDevice) -> str:
    return cache.get(d.fingerprint, {}).get("alias") or d.fingerprint[-5:]


def select(cache: dict[str, dict], devices: list[GoveeDevice], target: str) -> list[GoveeDevice]:
    if target == "all":
        return sorted(devices, key=lambda d: label(cache, d))
    chosen: list[GoveeDevice] = []
    for want in (w.strip().lower() for w in target.split(",")):
        hits = [
            d
            for d in devices
            if want in {d.ip, (cache.get(d.fingerprint, {}).get("alias") or "").lower()}
            or d.fingerprint.lower().replace(":", "").endswith(want.replace(":", ""))
        ]
        hits += [
            d
            for d in devices
            if re.fullmatch(re.escape(want) + r"-\d+", (cache.get(d.fingerprint, {}).get("alias") or "").lower())
        ]
        if not hits:
            raise SystemExit(f"govee: no bulb matches {want!r} (run `govee status` to see names)")
        chosen += [d for d in hits if d not in chosen]
    return chosen


async def read_status(controller: GoveeController, devices: list[GoveeDevice]) -> None:
    for d in devices:
        controller._send_update_message(d)  # noqa: SLF001  (library has no public one-device poll)
    await asyncio.sleep(STATUS_WAIT)


def print_status(cache: dict[str, dict], devices: list[GoveeDevice]) -> None:
    for d in devices:
        if d.on is None:
            print(f"{label(cache, d):<12} {d.ip:<15} no status reply")
            continue
        if d.temperature_color:
            shade = f"{d.temperature_color}K"
        else:
            shade = "#{:02x}{:02x}{:02x}".format(*d.rgb_color)
        power = "on " if d.on else "off"
        print(f"{label(cache, d):<12} {d.ip:<15} {power} {d.brightness:>3}%  {shade}")


def slug(name: str) -> str:
    """'Alex's bedroom 2' -> 'bedroom-2'. Drops possessives so aliases stay short."""
    words = [w for w in re.findall(r"[a-z0-9']+", name.lower()) if not w.endswith("'s")]
    return "-".join(w.replace("'", "") for w in words) or name


def api_key() -> str:
    key = os.environ.get("GOVEE_API_KEY", "")
    if not key and ENV.exists():
        for line in ENV.read_text().splitlines():
            if line.startswith("GOVEE_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
    if not key:
        raise SystemExit("govee: GOVEE_API_KEY is not set (harness .env)")
    return key


def sync_names() -> int:
    req = urllib.request.Request(f"{CLOUD}/user/devices", headers={"Govee-API-Key": api_key()})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.load(resp)
    if body.get("code") != 200:
        raise SystemExit(f"govee: cloud API said {body.get('code')} {body.get('message')}")
    cache = load_cache()
    for dev in body["data"]:
        if ":" not in dev["device"]:  # app-side groups have numeric ids and no LAN presence
            continue
        entry = cache.setdefault(dev["device"], {})
        entry.update(sku=dev["sku"], name=dev.get("deviceName", ""), alias=slug(dev.get("deviceName", "")))
    save_cache(cache)
    for fp, e in sorted(cache.items(), key=lambda kv: kv[1].get("alias", "")):
        print(f"{e.get('alias', fp[-5:]):<12} {e.get('ip') or 'not on LAN':<15} {e.get('name', '')}")
    return 0


# Power-on rule periods: (after, before, color field, brightness %, label).
# Day light is for wakefulness: 6500K is the H6008 maximum and the most melanopic white
# (Chellappa 2011; Brown 2022 asks for >=250 melanopic EDI lux at the eye by day).
# The last two hours before sunset step down to 2700K, the real H6008 floor (the API
# advertises 2000K, but the bulb clamps to 2700K). Night is dim red, which has almost no
# melanopic effect.
PERIODS = [
    ("SUNRISE", "SUNSET-2hour", "temperature: 6500K", 100, "day"),
    ("SUNSET-2hour", "SUNSET", "temperature: 2700K", 100, "late afternoon"),
    ("SUNSET", "SUNRISE", "spectrumRGB: FF0000", 30, "night"),
]


def google_script(room: str | None) -> int:
    """Print a Google Home script editor script: one day and one night automation per bulb.

    A script action cannot target "the device that started it", so each bulb gets its own
    pair. Google names a device "<name> - <room>"; the room is a placeholder unless --room
    or a "room" field in the cache gives it.
    """
    cache = load_cache()
    bulbs = sorted((e for e in cache.values() if e.get("name")), key=lambda e: e["name"])
    if room is None:
        skipped = [e["name"] for e in bulbs if not e.get("room")]
        bulbs = [e for e in bulbs if e.get("room")]
        if skipped:
            print(f"govee: skipped {', '.join(skipped)} (no room; set one with --room)", file=sys.stderr)
    if not bulbs:
        raise SystemExit("govee: no bulb names in the cache; run `govee sync-names` first")
    out = [
        "metadata:",
        "  name: Govee power-on color",
        "  description: When a Govee bulb turns on, set 6500K by day, 2700K in the 2 hours before sunset, dim red at night.",
        "automations:",
    ]
    for e in bulbs:
        device = f"{e['name']} - {e.get('room') or room}"
        for after, before, color, brightness, _label in PERIODS:
            out += [
                "  - starters:",
                "      - type: device.state.OnOff",
                f"        device: {device}",
                "        state: on",
                "        is: true",
                "    condition:",
                "      type: time.between",
                f"      after: {after}",
                f"      before: {before}",
                "    actions:",
                "      - type: device.command.ColorAbsolute",
                f"        devices: {device}",
                "        color:",
                f"          {color}",
                "      - type: device.command.BrightnessAbsolute",
                f"        devices: {device}",
                f"        brightness: {brightness}",
            ]
    print("\n".join(out))
    return 0


async def run(args: argparse.Namespace) -> int:
    if args.cmd == "sync-names":
        return sync_names()
    if args.cmd == "google-script":
        return google_script(args.room)
    cache = load_cache()
    controller = await discover(cache, full=args.cmd == "scan")
    try:
        devices = controller.devices
        remember(cache, devices)
        missing = [e.get("alias") or fp[-5:] for fp, e in cache.items() if fp not in {d.fingerprint for d in devices}]
        if missing:
            print(f"govee: no reply from {', '.join(missing)} (off at the wall switch, or LAN Control off)", file=sys.stderr)
        if not devices:
            return 1

        if args.cmd == "name":
            (d,) = select(cache, devices, args.device)
            cache[d.fingerprint]["alias"] = args.alias
            save_cache(cache)
            print(f"{d.ip} is now {args.alias!r}")
            return 0

        targets = select(cache, devices, getattr(args, "target", "all"))
        if args.cmd in {"scan", "status"}:
            await read_status(controller, targets)
            print_status(cache, targets)
            return 0

        for d in targets:
            if args.cmd in {"on", "off"}:
                await controller.turn_on_off(d, args.cmd == "on")
            elif args.cmd == "brightness":
                await controller.set_brightness(d, max(1, min(100, args.pct)))
            elif args.cmd == "color":
                temp = NAMED_TEMPS.get(args.color.lower())
                if temp:
                    await controller.set_color(d, rgb=None, temperature=temp)
                else:
                    await controller.set_color(d, rgb=parse_color(args.color), temperature=None)
            elif args.cmd == "temp":
                await controller.set_color(d, rgb=None, temperature=max(2000, min(9000, args.kelvin)))
        await asyncio.sleep(0.2)
        if args.check:
            await read_status(controller, targets)
            print_status(cache, targets)
        return 0
    finally:
        await controller.cleanup().wait()


def main() -> int:
    p = argparse.ArgumentParser(prog="govee", description="Control Govee lights on the LAN.")
    p.add_argument("--check", action="store_true", help="read status back after a set command")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="discover bulbs and show status")
    sub.add_parser("status").add_argument("target", nargs="?", default="all")
    for name in ("on", "off"):
        sub.add_parser(name).add_argument("target", nargs="?", default="all")
    b = sub.add_parser("brightness")
    b.add_argument("pct", type=int)
    b.add_argument("target", nargs="?", default="all")
    c = sub.add_parser("color", help="name, #rrggbb, r,g,b, or a white: " + ", ".join(NAMED_TEMPS))
    c.add_argument("color")
    c.add_argument("target", nargs="?", default="all")
    t = sub.add_parser("temp")
    t.add_argument("kelvin", type=int)
    t.add_argument("target", nargs="?", default="all")
    n = sub.add_parser("name")
    n.add_argument("device")
    n.add_argument("alias")
    sub.add_parser("sync-names", help="copy the Govee app names into the aliases")
    g = sub.add_parser("google-script", help="print a Google Home script for the power-on color rule")
    g.add_argument("--room", help="Google Home room for bulbs with no room in the cache (default: skip them)")
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
