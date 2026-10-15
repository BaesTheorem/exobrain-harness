"""Local HTTP server for the trace-labeling page (bin/traces review).

INVARIANTS
- Binds 127.0.0.1 only. Each /api request needs the token (X-Review-Token
  header) and a Host header of 127.0.0.1 or localhost on this port, so other
  web pages in the browser cannot read traces or write labels.
- Serves only the sessions in the sample: any other id is a 404, and no file
  path ever comes from the request.
- Static files come from fixed name lists in traces/review/ and the vendored
  Beer CSS dist. Any other name is a 404.
- Every response carries a CSP with script-src 'self', so text from a
  transcript cannot run as script even if the page mishandled it.
"""

from __future__ import annotations

import functools
import hmac
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import trace_review

HERE = Path(__file__).resolve().parent
PAGE = HERE / "review"
BEER = Path.home() / "Documents" / "material-design" / "beercss" / "dist" / "cdn"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript"),
          "/app.css": ("app.css", "text/css")}
BEER_FILES = {"beer.min.css": "text/css", **{f"material-symbols-{cut}.woff2": "font/woff2"
                                               for cut in ("outlined", "rounded", "sharp", "subset")}}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
       "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
MAX_BODY = 16_384


class Review:
    """The state one server holds: the sample, its labels dir, the archive, the token."""

    def __init__(self, sample_path: Path, labels_dir: Path, archive: Path | None, token: str):
        if sample_path.exists():
            self.doc = json.loads(sample_path.read_text())
        else:  # the page shows its empty state with the command that makes a sample
            self.doc = {"name": sample_path.stem, "window": [], "items": []}
        self.labels_dir = labels_dir
        self.archive = archive
        self.token = token
        self.ids = [i["file_id"] for i in self.doc["items"]]
        try:
            self.meta = trace_review.item_meta(self.ids)
        except Exception as exc:  # noqa: BLE001 -- the page still works without names, so log and go on
            print(f"item names unavailable ({exc!r}); showing first prompts", file=sys.stderr)
            self.meta = {}
        self.condense = functools.lru_cache(maxsize=24)(self._condense)

    def _condense(self, file_id: str) -> dict:
        return trace_review.condense(file_id, self.archive)

    def listing(self) -> dict:
        done = trace_review.labels(self.labels_dir)
        items = []
        for i in self.doc["items"]:
            m = self.meta.get(i["file_id"], {})
            lab = done.get(i["file_id"])
            items.append({"id": i["file_id"], "stratum": i["stratum"],
                          "label": m.get("label") or trace_review.short_label(i.get("title"), i.get("first_prompt"),
                                                                               None),
                          "first_ts": m.get("first_ts"), "entrypoint": m.get("entrypoint"),
                          "n_human_prompts": i["n_human_prompts"], "n_tool_calls": i["n_tool_calls"],
                          "n_tool_errors": i["n_tool_errors"], "cost_usd": i.get("cost_usd"),
                          "verdict": lab["verdict"] if lab else None, "note": lab["note"] if lab else ""})
        return {"name": self.doc["name"], "window": self.doc["window"], "items": items, "tally": self.tally(done)}

    def tally(self, done: dict | None = None) -> dict:
        done = done if done is not None else trace_review.labels(self.labels_dir)
        out = {"pass": 0, "fail": 0, "skip": 0, "labeled": 0, "total": len(self.ids)}
        for file_id in self.ids:
            if file_id in done:
                out[done[file_id]["verdict"]] += 1
                out["labeled"] += 1
        return out


def make_handler(review: Review, port: int) -> type[BaseHTTPRequestHandler]:
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "traces-review"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 -- stdlib signature
            if args and str(args[1]) not in ("200", "304"):
                sys.stderr.write("%s %s\n" % (self.address_string(), format % args))

        def send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, code: int, obj: object) -> None:
            self.send(code, json.dumps(obj, ensure_ascii=False).encode())

        def allowed(self, api: bool) -> bool:
            if self.headers.get("Host", "") not in hosts:
                self.send_json(403, {"error": "bad host"})
                return False
            if api and not hmac.compare_digest(self.headers.get("X-Review-Token", ""), review.token):
                self.send_json(403, {"error": "bad token"})
                return False
            return True

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path in STATIC:
                if self.allowed(api=False):
                    name, ctype = STATIC[url.path]
                    self.send(200, (PAGE / name).read_bytes(), ctype)
            elif url.path.startswith("/beer/"):
                name = url.path.removeprefix("/beer/")
                if name not in BEER_FILES:
                    self.send_json(404, {"error": "not found"})
                elif self.allowed(api=False):
                    self.send(200, (BEER / name).read_bytes(), BEER_FILES[name])
            elif url.path == "/api/sample":
                if self.allowed(api=True):
                    self.send_json(200, review.listing())
            elif url.path == "/api/trace":
                if not self.allowed(api=True):
                    return
                file_id = parse_qs(url.query).get("id", [""])[0]
                if file_id not in review.ids:
                    self.send_json(404, {"error": "not in this sample"})
                    return
                try:
                    self.send_json(200, review.condense(file_id))
                except OSError as exc:
                    self.send_json(500, {"error": f"archive read failed: {exc}"})
            else:
                self.send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/label":
                self.send_json(404, {"error": "not found"})
                return
            if not self.allowed(api=True):
                return
            size = int(self.headers.get("Content-Length") or 0)
            if size <= 0 or size > MAX_BODY:
                self.send_json(413, {"error": "body size"})
                return
            try:
                body = json.loads(self.rfile.read(size))
                file_id, verdict, note = body["id"], body["verdict"], str(body.get("note", ""))
            except (ValueError, KeyError, TypeError):
                self.send_json(400, {"error": "expected id, verdict, note"})
                return
            if file_id not in review.ids:
                self.send_json(404, {"error": "not in this sample"})
                return
            try:
                row = trace_review.add_label(review.doc["name"], file_id, verdict, note, review.labels_dir)
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            self.send_json(200, {"label": row, "tally": review.tally()})

    return Handler


def load_token(path: Path) -> str:
    """One token per install, kept in a 0600 file so the page URL stays the same after a restart."""
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(18)
    path.touch(mode=0o600)
    path.write_text(token + "\n")
    return token


def serve(sample: str = "sample-1", port: int = 5019, labels_dir: Path = trace_review.LABELS,
          archive: Path | None = None, token: str | None = None) -> None:
    review = Review(labels_dir / f"{sample}.json", labels_dir, archive,
                    token or load_token(labels_dir / ".review-token"))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(review, port))
    print(f"trace review: http://127.0.0.1:{port}/#t={review.token}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
