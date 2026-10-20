"""Scorebug publisher: posts the lineup model snapshot to the cloud.

The dashboard itself runs in the cloud (fantasy/scorebug/: the Worker serves
the page and does the live arithmetic). The Mac's part is the heavy model,
so while the Mac is up this posts fantasy/scorebug/snapshot.py every
GAME_GAP seconds on a game day and every IDLE_GAP seconds otherwise; the
Worker stores it only when it changed. When the Mac is away, the Worker
dispatches the same snapshot on GitHub Actions instead.

It also answers http://127.0.0.1:5023 with a redirect to the cloud app, so
old links keep working.

INVARIANTS
- Read-only against ESPN (snapshot.py uses the read-only `espn` client).
"""

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
FANTASY = HERE.parent
SNAPSHOT = FANTASY / "scorebug" / "snapshot.py"
CONF = FANTASY / "scorebug" / "scorebug.json"
PORT = 5023
GAME_GAP, IDLE_GAP = 120, 1800
GAME_DAYS = {0, 3, 6}  # Monday, Thursday, Sunday (datetime.weekday)

status: dict = {"last": None, "result": None}


def loop() -> None:
    while True:
        r = subprocess.run([sys.executable, str(SNAPSHOT), "--post"], capture_output=True, text=True,
                           timeout=600, cwd=FANTASY)
        status["last"] = datetime.now().astimezone().isoformat(timespec="seconds")
        status["result"] = (r.stdout.strip() or r.stderr.strip()[-300:])
        if r.returncode:
            print(f"{status['last']} snapshot failed: {status['result']}", file=sys.stderr, flush=True)
        time.sleep(GAME_GAP if datetime.now().weekday() in GAME_DAYS else IDLE_GAP)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        if self.path.startswith("/status"):
            body = json.dumps(status).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        conf = json.loads(CONF.read_text()) if CONF.exists() else {}
        self.send_response(302)
        self.send_header("Location", f"{conf.get('url', '')}/?k={conf.get('view_key', '')}")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        pass


if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
