"""HTTP server for the Marketplace front end: static UI plus a small JSON API.

Binds to 127.0.0.1 by default. Every API call can make requests to Facebook with Alex's
session, so do not bind it to a public interface; use --host with a Tailscale address for the
phone.

API
  GET  /api/config              home point, index radius, categories, sweep and pin state
  GET  /api/index?since=T       light rows changed at or after T (0 = everything), plus `now`
  POST /api/sweep {force}       start an index sweep if one is due (or forced)
  POST /api/pins {ids}          fetch pins for these listings (the cards on screen)
  POST /api/search              {q, max_mi, min, max, days, condition[], local_only} -> {job}
  GET  /api/job/<id>            status and the ids Facebook returned for the query
  GET  /api/item/<id>           one listing in full (fetches the item page if needed)
  POST /api/hide | /api/unhide  {kind: listing|seller, key, label}
  GET  /api/hidden
  GET  /api/saved | POST /api/saved {name, params, alert} | POST /api/saved/delete {name}
  POST /api/saved/alert {name, on}
"""

from __future__ import annotations

import gzip
import json
import mimetypes
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from shoptools.common import LaneError

from .crawl import INDEX_MI, SWEEP_CATEGORIES, Crawler
from .store import Store

STATIC = Path(__file__).resolve().parent / "static"
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("font/woff2", ".woff2")
CATEGORY_LABELS = {
    "apparel": "Apparel", "classifieds": "Classifieds", "electronics": "Electronics",
    "entertainment": "Entertainment", "family": "Family", "free": "Free stuff", "furniture": "Furniture",
    "garden": "Garden & outdoor", "hobbies": "Hobbies", "home": "Home goods",
    "home-improvements": "Home improvement", "instruments": "Musical instruments",
    "office-supplies": "Office supplies", "pets": "Pet supplies", "sports": "Sporting goods",
    "toys": "Toys & games", "vehicles": "Vehicles",
}


def make_handler(store: Store, crawler: Crawler) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "marketplace/2"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            if not re.match(r"^/api/(job|index|pins|config)", self.path):
                super().log_message(format, *args)

        # -------------------------------------------------------- plumbing

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if len(body) > 2048 and "gzip" in (self.headers.get("Accept-Encoding") or ""):
                body = gzip.compress(body, 5)
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj, separators=(",", ":")).encode(), "application/json")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _same_origin(self) -> bool:
            # Block cross-site POSTs from other pages in the browser; they would act with the session.
            origin = self.headers.get("Origin")
            return origin is None or origin.split("//", 1)[-1] == self.headers.get("Host")

        # -------------------------------------------------------- routes

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            path, qs = url.path, parse_qs(url.query)
            if path == "/api/config":
                return self._json({"home": crawler.home, "index_mi": INDEX_MI,
                                   "categories": [[c, CATEGORY_LABELS.get(c, c)] for c in SWEEP_CATEGORIES
                                                  if c != "free"] + [["other", "Other"]],
                                   "sweep": crawler.sweep_status(), "sweep_due": crawler.sweep_due(),
                                   "pending": crawler.pending(), "locator_error": crawler.locator_error})
            if path == "/api/index":
                since = int((qs.get("since") or ["0"])[0] or 0)
                now = int(time.time())
                return self._json({"now": now, "rows": store.index(since), "sweep": crawler.sweep_status(),
                                   "pending": crawler.pending(), "locator_error": crawler.locator_error})
            if m := re.fullmatch(r"/api/job/(\w+)", path):
                job = crawler.jobs.get(m.group(1))
                if not job:
                    return self._json({"error": "unknown job"}, 404)
                return self._json({"id": job.id, "status": job.status, "params": job.params, "rings": job.rings,
                                   "rings_done": job.rings_done, "warnings": job.warnings, "ids": list(job.ids)})
            if m := re.fullmatch(r"/api/item/(\d+)", path):
                if store.needs_item(m.group(1)):
                    try:
                        crawler.locate_now(m.group(1))
                    except LaneError as e:
                        return self._json({"error": str(e)}, 502)
                rows = store.rows([m.group(1)])
                return self._json(rows[0] if rows else {"error": "not found or hidden"}, 200 if rows else 404)
            if path == "/api/hidden":
                return self._json(store.hidden())
            if path == "/api/saved":
                return self._json(store.saved())
            return self._static(path)

        def do_POST(self) -> None:
            if not self._same_origin():
                return self._json({"error": "cross-origin request refused"}, 403)
            path = urlsplit(self.path).path
            body = self._body()
            if path == "/api/search":
                q = str(body.get("q") or "").strip()
                if not q:
                    return self._json({"error": "a search term is required"}, 400)
                params = {
                    "q": q,
                    "max_mi": max(1.0, min(float(body.get("max_mi") or 20), 100.0)),
                    "min": float(body["min"]) if body.get("min") not in (None, "") else None,
                    "max": float(body["max"]) if body.get("max") not in (None, "") else None,
                    "days": int(body["days"]) if body.get("days") else None,
                    "condition": [c for c in body.get("condition") or [] if c],
                    "local_only": bool(body.get("local_only", True)),
                }
                return self._json({"job": crawler.start(params).id})
            if path == "/api/sweep":
                if body.get("force") or crawler.sweep_due():
                    started = crawler.start_sweep()
                    return self._json({"started": started, "sweep": crawler.sweep_status()})
                return self._json({"started": False, "sweep": crawler.sweep_status()})
            if path == "/api/pins":
                ids = [str(i) for i in body.get("ids") or [] if str(i).isdigit()][:60]
                return self._json({"queued": crawler.request_pins(ids)})
            if path in ("/api/hide", "/api/unhide"):
                kind, key = body.get("kind"), str(body.get("key") or "")
                if kind not in ("listing", "seller") or not key:
                    return self._json({"error": "kind must be listing or seller, with a key"}, 400)
                if path == "/api/hide":
                    store.hide(kind, key, str(body.get("label") or ""))
                else:
                    store.unhide(kind, key)
                return self._json({"ok": True})
            if path == "/api/saved":
                store.save_search(str(body["name"]), body.get("params") or {}, bool(body.get("alert")))
                return self._json({"ok": True})
            if path == "/api/saved/alert":
                store.set_alert(str(body["name"]), bool(body.get("on")))
                return self._json({"ok": True})
            if path == "/api/saved/delete":
                store.delete_search(str(body["name"]))
                return self._json({"ok": True})
            return self._json({"error": "not found"}, 404)

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (STATIC / rel).resolve()
            if not target.is_file() or STATIC not in target.parents:
                return self._send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self._send(200, target.read_bytes(), ctype)

    return Handler


def serve(host: str = "127.0.0.1", port: int = 5041) -> None:
    store = Store()
    crawler = Crawler(store)
    # An empty or stale index fills itself; the page shows listings as they arrive.
    if crawler.sweep_due():
        threading.Timer(2.0, crawler.start_sweep).start()
    httpd = ThreadingHTTPServer((host, port), make_handler(store, crawler))
    print(f"marketplace: http://{host}:{port}/", flush=True)
    httpd.serve_forever()
