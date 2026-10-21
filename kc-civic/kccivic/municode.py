"""Kansas City, MO code text from Municode, cached as JSON lines per chapter.

Municode serves the code from library.municode.com/api behind a Cloudflare
challenge. A headless Chrome page passes it (walled.browser_page), and fetch()
calls made from that page must send the header "x-csrf: 1" or they get 401.
The city has two products: the Code of Ordinances, and a separate Zoning and
Development Code. Chapter 88 in the first product is only a link to the second.

A content call for a large node returns either the whole subtree, or only the
node's own heading (then the TOC children are walked), or a list of sections
with empty bodies (then each empty section is fetched once on its own).

INVARIANTS:
- One API call per THROTTLE seconds at most. A burst of about 600 calls got
  HTTP 429 for more than an hour (2026-10-21). Stop at the first 429; never
  retry in a loop.
- The cache under data/code/ is public law text that can be fetched again. It
  stays gitignored with the rest of data/.
"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from .walled import browser_page

API = "https://library.municode.com/api"
HOME = "https://library.municode.com/mo/kansas_city/codes/code_of_ordinances"
CLIENT_ID = 2797  # Kansas City, MO
PRODUCTS = {"ordinances": "code of ordinances", "zoning": "zoning and development code"}
CACHE = Path(__file__).resolve().parent.parent / "data" / "code"
THROTTLE = 1.5
_JS = """async (u) => { const r = await fetch(u, {headers: {Accept: 'application/json, text/plain, */*', 'x-csrf': '1'}});
  return [r.status, await r.text()]; }"""


class RateLimited(RuntimeError):
    pass


class _Api:
    def __init__(self, pg, product: str):
        self.pg = pg
        self.last = 0.0
        pr = self.get(f"{API}/Products/name?clientId={CLIENT_ID}&productName={PRODUCTS[product].replace(' ', '+')}")
        self.prod = (pr.get("Model") or pr)["ProductID"]
        jb = self.get(f"{API}/Jobs/latest/{self.prod}")
        self.job = (jb.get("Model") or jb)["Id"]

    def get(self, url: str):
        wait = THROTTLE - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        status, body = self.pg.evaluate(_JS, url)
        self.last = time.monotonic()
        if status == 429:
            raise RateLimited("Municode returned HTTP 429; wait an hour before the next run")
        if status != 200 or not body:
            return {}
        return json.loads(body)

    def content(self, node: str) -> list[dict]:
        return self.get(f"{API}/CodesContent?jobId={self.job}&nodeId={node}&productId={self.prod}").get("Docs", [])

    def children(self, node: str = "") -> list[dict]:
        tree = self.get(f"{API}/codesToc?jobId={self.job}&productId={self.prod}" + (f"&nodeId={node}" if node else ""))
        return tree.get("Children", []) if not node else _find(tree, node)


def _find(t: dict, node: str) -> list[dict]:
    if t.get("Id") == node:
        return t.get("Children") or []
    for c in t.get("Children") or []:
        r = _find(c, node)
        if r:
            return r
    return []


def clean(h: str) -> str:
    """Section HTML to plain text; table cells become ' | '-separated."""
    h = re.sub(r"<(br|/p|/tr|/li|/div|/h\d)[^>]*>", "\n", h or "")
    h = re.sub(r"<(td|th)[^>]*>", " | ", h)
    h = re.sub(r"<[^>]+>", "", h)
    return re.sub(r"[ \t]+", " ", html.unescape(h)).strip()


def _walk(api: _Api, node: str, rows: dict[str, dict]) -> None:
    docs = api.content(node)
    for d in docs:
        rows.setdefault(d["Id"], {"id": d["Id"], "title": d.get("Title", ""), "text": clean(d.get("Content") or "")})
    if len(docs) <= 1:
        for k in api.children(node):
            _walk(api, k["Id"], rows)
        return
    for rid in [r for r, v in rows.items() if not v["text"] and r.startswith(node)]:
        for d in api.content(rid):
            t = clean(d.get("Content") or "")
            if d["Id"] in rows and t and not rows[d["Id"]]["text"]:
                rows[d["Id"]]["text"] = t


def fetch(product: str, nodes: list[str]) -> list[Path]:
    out = CACHE / product
    out.mkdir(parents=True, exist_ok=True)
    saved = []
    with browser_page(HOME) as pg:
        api = _Api(pg, product)
        for node in nodes:
            rows: dict[str, dict] = {}
            try:
                _walk(api, node, rows)
            finally:
                if rows:
                    p = out / f"{node}.jsonl"
                    p.write_text("".join(json.dumps(r) + "\n" for r in rows.values()))
                    saved.append(p)
                    print(f"{node}: {len(rows)} sections, {sum(1 for r in rows.values() if not r['text'])} empty -> {p}")
    return saved


def toc(product: str, node: str = "") -> None:
    with browser_page(HOME) as pg:
        api = _Api(pg, product)
        for k in api.children(node):
            print(f"{k['Id']} | {k.get('Heading', '')}")


def cached_rows(product: str | None = None):
    for p in sorted(CACHE.glob(f"{product or '*'}/*.jsonl")):
        for line in p.open():
            yield p, json.loads(line)


def grep(pattern: str, product: str | None = None, width: int = 160) -> None:
    rx = re.compile(pattern, re.I)
    for _p, r in cached_rows(product):
        t = re.sub(r"\s+", " ", r["text"])
        m = rx.search(t)
        if m:
            print(f"{r['title'][:90]}\n    ...{t[max(0, m.start() - width // 2): m.end() + width // 2]}...")


def show(prefix: str, product: str | None = None) -> None:
    for _p, r in cached_rows(product):
        if r["title"].startswith(prefix):
            print(f"## {r['title']}\n{r['text']}\n")
