"""govee: control Govee lights on the LAN (UDP local API) via govee-local-api.

Commands:
    govee scan                      discover bulbs, refresh the device cache
    govee status [TARGET]           power, brightness, color of each bulb
    govee on|off [TARGET]
    govee brightness PCT [TARGET]   1-100
    govee color COLOR [TARGET]      name (red, warm), #rrggbb, or r,g,b
    govee temp KELVIN [TARGET]      2000-9000
    govee name DEVICE ALIAS         give a bulb a short name

TARGET is "all" (default), an alias, an IP, or the tail of the device id.
Commas select several targets: "desk,lamp".

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
import sys
from pathlib import Path

from govee_local_api import GoveeController, GoveeDevice  # pyright: ignore[reportMissingImports]

DATA = Path(__file__).resolve().parent / "data" / "devices.json"
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
NAMED_TEMPS = {"candle": 2000, "warm": 2700, "soft": 3000, "neutral": 4000, "daylight": 5500, "cool": 6500}


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
        controller.add_device_to_discovery_queue(entry["ip"])
    await controller.start()
    controller.send_discovery_message()
    expected = len(cache)
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


async def run(args: argparse.Namespace) -> int:
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
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
