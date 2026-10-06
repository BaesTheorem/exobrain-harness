#!/usr/bin/env python3
"""Overland GPS receiver: takes the batches the Overland iOS app POSTs and
appends each point to a per-day JSONL file.

Overland keeps points on the phone until the server answers {"result": "ok"},
so this only has to be reachable on the home network. Points logged away
from home arrive on the next sync.

Config (harness .env):
  OVERLAND_TOKEN   shared secret, sent as "Authorization: Bearer X" or ?token=X
  OVERLAND_PORT    listen port (default 5061)

Output: location/data/points/YYYY-MM-DD.jsonl, one point per line,
{"t": local ISO time, "lat", "lon", "p": Overland properties}. The file
date is the point's local date, not the arrival date.

INVARIANTS:
  - Reply {"result": "ok"} only after every point in the batch is on disk.
    Any other reply makes Overland resend, which is the safe failure.
  - Never accept a batch without the token: the port is open to the LAN.
"""

import hmac
import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
HARNESS_DIR = HERE.parent
POINTS_DIR = HERE / "data" / "points"
MAX_BODY = 20 * 1024 * 1024
_write_lock = Lock()


def load_env():
    env_path = HARNESS_DIR / ".env"
    if not env_path.exists():
        return {}
    out = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def parse_ts(s):
    """Overland sends "2015-10-01T08:00:00-0700"; newer builds may send
    "Z" or "-07:00". Return an aware local datetime, or None."""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone()


def to_records(payload):
    """Turn an Overland batch into (local_date, record) pairs. Features
    without a point geometry or a usable timestamp are dropped."""
    out = []
    for feat in payload.get("locations") or []:
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        props = feat.get("properties") or {}
        if geom.get("type") != "Point" or len(coords) < 2:
            continue
        dt = parse_ts(str(props.get("timestamp", "")))
        if dt is None:
            continue
        rec = {"t": dt.isoformat(), "lon": coords[0], "lat": coords[1], "p": props}
        out.append((dt.date().isoformat(), rec))
    return out


def append_records(pairs, points_dir=POINTS_DIR):
    by_day = {}
    for day, rec in pairs:
        by_day.setdefault(day, []).append(rec)
    points_dir.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        for day, recs in by_day.items():
            with (points_dir / f"{day}.jsonl").open("a") as f:
                for rec in recs:
                    f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                f.flush()
    return {day: len(recs) for day, recs in by_day.items()}


class Handler(BaseHTTPRequestHandler):
    token = ""

    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        auth = self.headers.get("Authorization", "")
        given = auth[7:] if auth.startswith("Bearer ") else ""
        if not given:
            given = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        return bool(self.token) and hmac.compare_digest(given, self.token)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self._reply(200, {"ok": True})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self):
        if not self._authorized():
            self._reply(401, {"error": "bad token"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self._reply(400, {"error": "bad length"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            counts = append_records(to_records(payload))
        except (ValueError, OSError) as e:
            self.log_message("rejected batch: %s", e)
            self._reply(400, {"error": str(e)})
            return
        self.log_message("stored %s", counts or "nothing")
        self._reply(200, {"result": "ok"})

    def log_message(self, format, *args):  # noqa: A002 (stdlib signature)
        ts = datetime.now().isoformat(timespec="seconds")
        sys.stderr.write(f"[{ts}] {self.address_string()} {format % args}\n")


def main():
    env = load_env()
    Handler.token = env.get("OVERLAND_TOKEN", "")
    if not Handler.token:
        sys.exit("OVERLAND_TOKEN missing from the harness .env")
    port = int(env.get("OVERLAND_PORT", "5061"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    sys.stderr.write(f"overland receiver on :{port}, writing {POINTS_DIR}\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
