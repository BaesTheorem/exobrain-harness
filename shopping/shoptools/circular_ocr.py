"""Image-only weekly circulars (Sun Fresh, Cosentino's Market) -> item and price rows.

Both chains publish the weekly ad as a PDF whose pages are one JPEG each (no text layer:
`pdftotext` returns 6 bytes for a 6-page Sun Fresh ad, measured 2026-10-07). Tesseract reads
almost nothing off the designed layout (2 price tokens on a page with ~25 deals), while Apple's
Vision framework reads 88 text boxes with their positions on the same page in under 3 s. So
this module:

1. downloads the PDF into shopping/.cache/circulars/ (keyed by URL hash),
2. pulls each page's JPEG straight out of the PDF with pypdf (no re-render: pdftoppm took 56 s
   on one 2700x6450 pt page, pypdf extraction takes 1 s),
3. runs `visionocr`, a 40-line Swift tool next to this file that the module compiles once with
   `swiftc` into the cache (about 16 s the first time), and
4. groups the text boxes into deals: a price token, then the name lines stacked under it.

Prices in these ads are typographic: "$149" is $1.49 (the cents are superscript, Vision drops
the size change), "099" is 99 cents, "99%" is Vision reading the cents sign, "2 99" is $2.99,
"5/$5" is five for $5. `parse_price` knows those shapes and returns the per-unit value plus the
ad's own wording, so sorting works and the printout still reads like the ad.

The grouping is a heuristic over normalized Vision boxes (origin bottom-left). It is tuned on
the two chains' current layouts and will miss some deals and mis-attach the odd line; treat the
rows as an index into the ad, not a price list. Every row carries the page number and the PDF
URL so the page can be opened. OCR results are cached beside the PDF.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import statistics
import subprocess
from pathlib import Path

from .common import ROOT, LaneError, session

CACHE = ROOT / ".cache"
CIRCULARS = CACHE / "circulars"
SWIFT_SRC = Path(__file__).with_name("visionocr.swift")
OCR_BIN = CACHE / "visionocr"
KEEP_DAYS = 30
MIN_CONF = 0.3

# ------------------------------------------------------------------ price tokens

_RE_MULTI = re.compile(r"^(\d{1,2})\s*/\s*\$?\s*(\d{1,3}(?:\.\d{1,2})?)$")       # 2/$5, 3/$10.00
_RE_DECIMAL = re.compile(r"^\$?\s*(\d{1,3})\.(\d{2})$")                            # $1.99, 12.49
_RE_SUPER = re.compile(r"^\$\s*(\d{1,2})\s?(\d{2})$")                              # $149 -> 1.49, $1099
_RE_SPACED = re.compile(r"^(\d{1,2})\s(\d{2})$")                                   # 2 99 -> 2.99
_RE_CENTS = re.compile(r"^(\d{2})\s*[¢%]$")                                        # 99¢, and Vision's 99%
_RE_LEADING_ZERO = re.compile(r"^0(\d{2})$")                                        # 099 -> 0.99
_RE_BARE = re.compile(r"^(\d)(\d{2})$")                                             # 299 -> 2.99, only when tall
UNIT_RE = re.compile(r"^(lb|lbs|ea|each|oz|ct|pk|pkg)\.?$", re.I)
# "0z" is Vision reading "oz" with a zero; the ads print sizes in small type.
SIZE_RE = re.compile(r"\d.*\b(oz|0z|lb|lbs|ct|pk|pkg|gal|qt|pt|l|ml|liter|litre|fl)\b\.?", re.I)


def parse_price(text: str, tall: bool = False) -> tuple[float | None, str | None]:
    """Ad price token -> (per-unit dollars, the ad's wording). (None, None) when it is not a price.

    `tall` says the text box is taller than the page's body text, which is how a bare "299"
    (no $, no decimal) earns a reading as $2.99 instead of a quantity or a year.
    """
    t = text.strip().replace("O", "0").replace("o", "0") if re.fullmatch(r"[\$\d\s./¢%Oo]+", text.strip()) else text.strip()
    t = re.sub(r"\s+", " ", t)
    if m := _RE_MULTI.match(t):
        qty, total = int(m.group(1)), float(m.group(2))
        if qty and 0 < total <= 200:
            return round(total / qty, 3), f"{qty}/${total:g}"
    if m := _RE_DECIMAL.match(t):
        v = float(f"{m.group(1)}.{m.group(2)}")
        return (v, f"${v:.2f}") if 0 < v <= 200 else (None, None)
    if m := _RE_SUPER.match(t) or _RE_SPACED.match(t) or _RE_LEADING_ZERO.match(t):
        g = m.groups()
        v = float(f"{g[0]}.{g[1]}") if len(g) == 2 else float(f"0.{g[0]}")
        return (v, f"${v:.2f}") if 0 < v <= 200 else (None, None)
    if m := _RE_CENTS.match(t):
        v = int(m.group(1)) / 100
        return v, f"{m.group(1)}¢"
    if tall and (m := _RE_BARE.match(t)):
        v = float(f"{m.group(1)}.{m.group(2)}")
        return (v, f"${v:.2f}") if v > 0 else (None, None)
    return None, None


# ------------------------------------------------------------------ grouping


def _cx(b: dict) -> float:
    return b["x"] + b["w"] / 2


def group_boxes(boxes: list[dict], page: int) -> list[dict]:
    """Vision text boxes for one page -> deal rows [{title, price, formatted, size, unit, page}].

    Boxes are normalized, origin bottom-left. A deal is a price token with its name lines
    stacked directly under it (centers aligned, small vertical gaps). Each line joins one deal.
    """
    boxes = [b for b in boxes if b.get("conf", 1) >= MIN_CONF and b.get("text", "").strip()]
    if not boxes:
        return []
    med_h = statistics.median(b["h"] for b in boxes)
    prices: list[tuple[dict, float, str]] = []
    for b in boxes:
        price, formatted = parse_price(b["text"], tall=b["h"] >= 1.5 * med_h)
        if price is not None:
            prices.append((b, price, formatted or b["text"]))
    price_ids = {id(b) for b, _, _ in prices}
    taken: set[int] = set()
    rows: list[dict] = []
    for p, price, formatted in sorted(prices, key=lambda x: -x[0]["y"]):
        unit = None
        lines: list[dict] = []
        for b in boxes:
            if id(b) in price_ids or id(b) in taken:
                continue
            if UNIT_RE.match(b["text"]) and b["y"] < p["y"] + p["h"] and b["y"] + b["h"] > p["y"] \
                    and abs(b["x"] - (p["x"] + p["w"])) < 0.04:
                unit = b["text"].strip(". ").lower()
                taken.add(id(b))
                continue
            gap = p["y"] - (b["y"] + b["h"])          # price bottom to line top
            if gap < -0.5 * p["h"] or gap > 0.035:
                continue
            if abs(_cx(b) - _cx(p)) > 0.5 * max(p["w"], b["w"]) + 0.02:
                continue
            lines.append(b)
        lines.sort(key=lambda b: -b["y"])
        kept: list[dict] = []
        for b in lines:
            if kept and (kept[-1]["y"] - (b["y"] + b["h"])) > 0.015:
                break
            kept.append(b)
            if len(kept) == 5:
                break
        if not kept:
            continue
        for b in kept:
            taken.add(id(b))
        size = next((b["text"].strip(" ,") for b in kept if SIZE_RE.search(b["text"])), None)
        title = " ".join(b["text"].strip() for b in kept if b["text"].strip(" ,") != size)
        rows.append({"title": title, "price": price, "formatted": formatted, "size": size, "unit": unit, "page": page,
                     "top": round(1 - (p["y"] + p["h"]), 3)})
    return rows


# ------------------------------------------------------------------ OCR plumbing


def ocr_binary() -> Path:
    """The compiled Vision helper, built from visionocr.swift when missing or stale."""
    if OCR_BIN.exists() and OCR_BIN.stat().st_mtime >= SWIFT_SRC.stat().st_mtime:
        return OCR_BIN
    if not shutil.which("swiftc"):
        raise LaneError("circular OCR needs swiftc (Xcode command line tools) to build the Vision helper once")
    CACHE.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["swiftc", "-O", "-o", str(OCR_BIN), str(SWIFT_SRC)], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise LaneError(f"circular OCR: swiftc failed: {r.stderr[-400:]}")
    return OCR_BIN


def ocr_image(path: Path) -> list[dict]:
    r = subprocess.run([str(ocr_binary()), str(path)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise LaneError(f"circular OCR: visionocr failed on {path.name}: {r.stderr[-200:]}")
    return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]


def pdf_page_images(pdf: Path) -> list[Path]:
    """One JPEG per page, extracted (not rendered) from an image-only PDF."""
    from pypdf import PdfReader

    out: list[Path] = []
    reader = PdfReader(str(pdf))
    for n, page in enumerate(reader.pages, 1):
        dest = pdf.with_name(f"{pdf.stem}-p{n}.jpg")
        if not dest.exists():
            imgs = page.images
            if not imgs:
                continue
            biggest = max(imgs, key=lambda i: len(i.data))
            dest.write_bytes(biggest.data)
        out.append(dest)
    if not out:
        raise LaneError(f"circular OCR: {pdf.name} has no page images (not an image-only PDF?)")
    return out


def _prune(days: int = KEEP_DAYS) -> None:
    cutoff = dt.datetime.now().timestamp() - days * 86400
    for f in CIRCULARS.glob("*"):
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def fetch_pdf(url: str) -> Path:
    CIRCULARS.mkdir(parents=True, exist_ok=True)
    _prune()
    dest = CIRCULARS / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".pdf")
    if not dest.exists():
        r = session().get(url, timeout=120)
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            raise LaneError(f"circular: HTTP {r.status_code} fetching {url}, not a PDF")
        dest.write_bytes(r.content)
    return dest


def circular_rows(url: str, retailer: str, valid_from: str = "", valid_to: str = "") -> list[dict]:
    """Deal rows for one ad PDF, cached beside it in shopping/.cache/circulars/."""
    pdf = fetch_pdf(url)
    cache = pdf.with_suffix(".rows.json")
    if cache.exists():
        rows = json.loads(cache.read_text())
    else:
        rows = []
        for n, img in enumerate(pdf_page_images(pdf), 1):
            rows.extend(group_boxes(ocr_image(img), n))
        cache.write_text(json.dumps(rows))
    out = []
    for i, r in enumerate(rows):
        out.append({"retailer": retailer, "id": f"{pdf.stem}-p{r['page']}-{i}", "url": url, "kind": "ad",
                    "valid_from": valid_from, "valid_to": valid_to, **r})
    return out
