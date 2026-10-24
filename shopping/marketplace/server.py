"""HTTP server for the Marketplace front end: static UI plus a small JSON API.

Binds to 127.0.0.1 by default. Every API call can make requests to Facebook with Alex's
session, so do not bind it to a public interface; use --host with a Tailscale address for the
phone.

API
  GET  /api/config              home point, rings, locator state
  POST /api/search              {q, max_mi, min, max, days, condition[], local_only} -> {job}
  GET  /api/job/<id>            status and every listing found so far
  GET  /api/item/<id>           one listing in full (fetches the item page if needed)
  POST /api/hide | /api/unhide  {kind: listing|seller, key, label}
  GET  /api/hidden
  GET  /api/saved | POST /api/saved {name, params} | POST /api/saved/delete {name}
"""

from __future__ import annotations

import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from shoptools.common import LaneError

from .crawl import RINGS_MI, Crawler
from .store import Store

STATIC = Path(__file__).resolve().parent / "static"
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("font/woff2", ".woff2")


def make_handler(store: Store, crawler: Crawler) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "marketplace/1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            if not self.path.startswith("/api/job/"):
                super().log_message(format, *args)

        # -------------------------------------------------------- plumbing

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _same_origin(self) -> bool:
            # Block cross-site POSTs from other pages in the browser; they would act with the session.
            origin = self.headers.get("Origin")
            return origin is None or origin.split("//", 1)[-1] == self.headers.get("Host")

        # -------------------------------------------------------- routes

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/api/config":
                return self._json({"home": crawler.home, "rings": RINGS_MI, "pending": crawler.pending(),
                                   "locator_error": crawler.locator_error})
            if m := re.fullmatch(r"/api/job/(\w+)", path):
                job = crawler.jobs.get(m.group(1))
                if not job:
                    return self._json({"error": "unknown job"}, 404)
                rows = store.rows(job.ids)
                return self._json({"id": job.id, "status": job.status, "params": job.params,
                                   "rings": job.rings, "rings_done": job.rings_done,
                                   "warnings": job.warnings, "pending": crawler.pending(),
                                   "locator_error": crawler.locator_error, "rows": rows})
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
            path = self.path.split("?", 1)[0]
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
                store.save_search(str(body["name"]), body.get("params") or {})
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
    httpd = ThreadingHTTPServer((host, port), make_handler(store, crawler))
    print(f"marketplace: http://{host}:{port}/", flush=True)
    httpd.serve_forever()
