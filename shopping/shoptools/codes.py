"""Promo-code harvest: aggregator pages plus common guesses. Candidates only, until tested on a cart.

Aggregator coverage (tested 2026-09-23): SimplyCodes puts codes in `data-code` attributes, and
dealspotr.com and knoji.com redirect to it. Wethrift embeds `"code":` JSON. RetailMeNot,
CouponFollow and CouponCabin hide codes behind a click-out. Slickdeals `/coupons/` is 410,
CouponBirds 403. The Syrup open-source coupon DB sits behind a JS challenge and the repo is
archived, so do not build on it.
"""

from __future__ import annotations

import re
import sys
from urllib.parse import urlparse

from .common import session

# Welcome and newsletter codes follow a small set of patterns. On Shopify a wrong
# guess costs one request and the cart reports it as not applicable, so
# guessing is cheap. (WELCOME10 was a guess and was live at allbirds.com on 2026-09-23.)
GUESSES = [
    f"{w}{n}"
    for w in ("WELCOME", "SAVE", "FIRST", "EMAIL", "NEW", "THANKYOU", "COMEBACK", "SIGNUP", "HELLO", "TAKE")
    for n in ("10", "15", "20")
] + ["FREESHIP", "FREESHIPPING", "STUDENT", "MILITARY", "NEWSLETTER", "WELCOME"]

CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,29}$")


def bare_domain(s: str) -> str:
    host = urlparse(s if "//" in s else f"https://{s}").netloc or s
    return host.removeprefix("www.")


def _simplycodes(s, domain: str) -> list[str]:
    r = s.get(f"https://simplycodes.com/store/{domain}", timeout=25)
    if r.status_code == 404:
        raise LookupError("no page for this store")
    return re.findall(r'data-code="([^"]+)"', r.text)


def _wethrift(s, domain: str) -> list[str]:
    r = s.get(f"https://www.wethrift.com/{domain.split('.')[0]}", timeout=25)
    if r.status_code == 404:
        raise LookupError("no page for this store")
    return re.findall(r'"code"\s*:\s*"([^"]{3,30})"', r.text)


HARVESTERS = {"simplycodes": _simplycodes, "wethrift": _wethrift}


def harvest(domain: str, extra: list[str], guess: bool) -> list[dict]:
    s = session()
    found: dict[str, set[str]] = {}
    for name, fn in HARVESTERS.items():
        try:
            codes = fn(s, domain)
        except Exception as e:  # noqa: BLE001 -- one dead aggregator must not sink the rest
            print(f"warn: {name} failed: {e}", file=sys.stderr)
            continue
        if not codes:
            print(f"warn: {name} returned 0 codes for {domain}", file=sys.stderr)
        for c in codes:
            found.setdefault(c.strip(), set()).add(name)
    for c in extra:
        found.setdefault(c.strip(), set()).add("manual")
    if guess:
        for c in GUESSES:
            found.setdefault(c, set()).add("guess")
    return [{"code": c, "sources": sorted(src)} for c, src in found.items() if CODE_RE.match(c)]
