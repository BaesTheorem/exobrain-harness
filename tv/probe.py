"""
Read-only audit of the Samsung TV: device info, open ports, UPnP descriptors,
installed apps. Writes one JSON snapshot per run so firmware updates and
debloat changes can be diffed.

Nothing here changes TV state: REST GETs, TCP connect probes, an SSDP
M-SEARCH, and the `ed.installedApp.get` query over the already-paired WSS
channel (no new pairing prompt, no key presses).

INVARIANTS
- No method that sends a key, launches/closes an app, or changes a setting.
- Uses the existing token only; if it is missing, skip the WSS step rather
  than trigger a pairing prompt.
"""

import asyncio
import base64
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import websocket

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tv_control as t

OUT_DIR = Path.home() / "Documents" / "tv-analysis" / "probes"


def rest(host, path=""):
    try:
        with urllib.request.urlopen(f"http://{host}:8001/api/v2/{path}", timeout=4) as r:
            return {"status": r.status, "body": json.loads(r.read() or b"null")}
    except urllib.error.HTTPError as e:
        return {"status": e.code}
    except Exception as e:  # noqa: BLE001 - record any failure as data
        return {"error": repr(e)}


async def _probe(host, port, sem):
    async with sem:
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(host, port), 1.0)
            w.close()
            return port
        except Exception:  # noqa: BLE001 - closed/filtered
            return None


async def scan(host):
    sem = asyncio.Semaphore(100)  # light enough to not disturb a TV in use
    res = await asyncio.gather(*(_probe(host, p, sem) for p in range(1, 65536)))
    return [p for p in res if p]


def banner(host, port):
    out = {}
    for scheme in ("http", "https"):
        ctx = ssl._create_unverified_context()  # noqa: S323, SLF001 - TV uses self-signed certs
        try:
            with urllib.request.urlopen(f"{scheme}://{host}:{port}/", timeout=3, context=ctx) as r:
                out[scheme] = {"status": r.status, "server": r.headers.get("Server"), "body": r.read(300).decode("latin1")}
        except urllib.error.HTTPError as e:
            out[scheme] = {"status": e.code, "server": e.headers.get("Server")}
        except Exception as e:  # noqa: BLE001
            out[scheme] = {"error": type(e).__name__}
    return out


def ssdp(host, wait=4):
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
           'MAN: "ssdp:discover"\r\nMX: 3\r\nST: ssdp:all\r\n\r\n').encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.5)
    s.sendto(msg, ("239.255.255.250", 1900))
    locs, end = {}, time.time() + wait
    while time.time() < end:
        try:
            data, addr = s.recvfrom(4096)
        except socket.timeout:
            continue
        if addr[0] != host:
            continue
        m = re.search(rb"(?im)^location:\s*(\S+)", data)
        st = re.search(rb"(?im)^st:\s*(\S+)", data)
        if m:
            locs[m.group(1).decode()] = st.group(1).decode() if st else None
    descs = {}
    for url in locs:
        try:
            with urllib.request.urlopen(url, timeout=4) as r:
                descs[url] = r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            descs[url] = f"error: {e!r}"
    return {"locations": locs, "descriptions": descs}


def installed_apps(host):
    if not t.TOKEN_FILE.exists():
        return {"skipped": "no token; not pairing from a read-only probe"}
    token = t.TOKEN_FILE.read_text().strip()
    try:
        token = json.loads(token).get("token", token)
    except (json.JSONDecodeError, AttributeError):
        pass
    name = base64.b64encode(b"Claude Code").decode()
    url = f"wss://{host}:8002/api/v2/channels/samsung.remote.control?name={name}&token={token}"
    ws = websocket.create_connection(url, timeout=8, sslopt={"cert_reqs": ssl.CERT_NONE})
    try:
        first = json.loads(ws.recv())
        if first.get("event") != "ms.channel.connect":
            return {"error": "no connect event", "got": first}
        ws.send(json.dumps({"method": "ms.channel.emit",
                            "params": {"event": "ed.installedApp.get", "to": "host"}}))
        end = time.time() + 10
        while time.time() < end:
            msg = json.loads(ws.recv())
            if msg.get("event") == "ed.installedApp.get":
                return {"apps": msg.get("data", {}).get("data", msg.get("data"))}
        return {"error": "timeout waiting for app list"}
    finally:
        ws.close()


def main():
    host = t.load_env().get("TV_HOST")
    info = rest(host)
    if "body" not in info:
        print(f"TV at {host} not reachable on 8001 ({info}). Is it on, and is this Mac on the home LAN?")
        sys.exit(1)
    snap = {"taken": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host": host, "device_info": info["body"]}
    print("scanning 65535 TCP ports...", flush=True)
    snap["open_ports"] = asyncio.run(scan(host))
    snap["banners"] = {p: banner(host, p) for p in snap["open_ports"]}
    snap["ssdp"] = ssdp(host)
    try:
        snap["installed_apps"] = installed_apps(host)
    except Exception as e:  # noqa: BLE001
        snap["installed_apps"] = {"error": repr(e)}
    apps = snap["installed_apps"].get("apps") or []
    snap["app_status"] = {a.get("appId"): rest(host, f"applications/{a.get('appId')}") for a in apps if isinstance(a, dict)}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"probe-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(snap, indent=2))
    dev = snap["device_info"].get("device", {})
    print(f"model {dev.get('modelName')}  OS {dev.get('OS')}  firmware {dev.get('firmwareVersion')}")
    print(f"open ports: {snap['open_ports']}")
    print(f"UPnP descriptors: {len(snap['ssdp']['descriptions'])}  installed apps: {len(apps)}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
