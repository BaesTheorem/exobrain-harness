"""Pages behind a Cloudflare challenge (edckc.com, kcmo.gov), read with a real Chrome.

curl, curl_cffi and a plain request context all get 403 from these sites. A real
Chrome (patchright, headless with a normal UA) passes the challenge, and a fetch()
run inside that page reuses the cleared session for feeds and PDFs.

INVARIANTS:
- One browser per pass, and callers gate passes to about once a day per site.
  These are small public sites; do not poll them.
- Google Drive "file/d/<id>/view" links are rewritten to the public direct
  download, because the CPC posts its docket on Drive.
"""

from __future__ import annotations

import base64
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")  # headless says "HeadlessChrome"


@contextmanager
def browser_page(home: str) -> Iterator[object]:
    from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        # Headless: a windowed Chrome placed off screen still comes forward and takes focus.
        b = p.chromium.launch(channel="chrome", headless=True)
        try:
            pg = b.new_page(user_agent=UA, viewport={"width": 1100, "height": 800})
            pg.goto(home, timeout=90000)
            for _ in range(30):
                if "Just a moment" not in pg.title():
                    break
                pg.wait_for_timeout(1500)
            yield pg
        finally:
            b.close()


def page_fetch_text(pg, url: str) -> str:
    status, body = pg.evaluate(
        "async (u) => { const r = await fetch(u); return [r.status, await r.text()]; }", url)
    if status != 200:
        raise RuntimeError(f"EDC fetch {url} -> HTTP {status}")
    return body


def page_fetch_bytes(pg, url: str) -> bytes:
    status, b64 = pg.evaluate(
        """async (u) => { const r = await fetch(u); const b = new Uint8Array(await r.arrayBuffer());
        let s = ''; for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
        return [r.status, btoa(s)]; }""", url)
    if status != 200:
        raise RuntimeError(f"EDC fetch {url} -> HTTP {status}")
    return base64.b64decode(b64)


DOC_RE = re.compile(r'href="([^"]+?(?:\.pdf[^"]*|drive\.google\.com/file/d/[^"/]+[^"]*))"', re.I)
DRIVE_RE = re.compile(r"drive\.google\.com/file/d/([^/?#]+)")


def fetch_page_docs(pg, url: str, dest: Path, limit: int = 12, prefix: str = "doc") -> tuple[str, list[Path]]:
    """The page's visible text plus every PDF (or Drive file) it links, saved under dest."""
    pg.goto(url, timeout=90000)
    for _ in range(20):
        if "Just a moment" not in pg.title():
            break
        pg.wait_for_timeout(1500)
    pg.wait_for_timeout(1500)
    html = pg.content()
    text = pg.evaluate("() => (document.querySelector('main') || document.body).innerText")
    saved = []
    for i, href in enumerate(dict.fromkeys(h.replace("&amp;", "&") for h in DOC_RE.findall(html))):
        if i >= limit:
            break
        drive = DRIVE_RE.search(href)
        try:
            if drive:
                data = _direct(f"https://drive.google.com/uc?export=download&id={drive.group(1)}")
            else:
                data = page_fetch_bytes(pg, href)
        except (RuntimeError, OSError):
            continue
        if not data:
            continue
        p = dest / f"{prefix}-{i + 1}.pdf"
        p.write_bytes(data)
        saved.append(p)
    return text, saved


def _direct(url: str) -> bytes:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read(30 * 1024 * 1024)
    return data if data[:4] == b"%PDF" else b""
