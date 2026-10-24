"""List nearby Bluetooth LE advertisers, strongest signal first.

Run through `bin/ble-run scan [seconds] [name-filter]`; bare python from the
Console is killed by TCC. macOS hides real MAC addresses, so the address column
is a per-Mac CoreBluetooth UUID.
"""

import asyncio
import sys

from bleak import BleakScanner


async def main() -> None:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    needle = sys.argv[2].lower() if len(sys.argv) > 2 else ""
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    rows = sorted(found.values(), key=lambda t: -t[1].rssi)
    for dev, adv in rows:
        name = adv.local_name or dev.name or "-"
        if needle and needle not in name.lower():
            continue
        mfr = {f"0x{k:04x}": v.hex() for k, v in adv.manufacturer_data.items()}
        print(f"{adv.rssi:>4} dBm  {dev.address}  {name}")
        if adv.service_uuids:
            print(f"          services: {', '.join(adv.service_uuids)}")
        if mfr:
            print(f"          manufacturer: {mfr}")
    print(f"({len(rows)} advertisers in {seconds:g}s)")


asyncio.run(main())
