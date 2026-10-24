"""The page's filter rules in Python, for alerts. Keep in step with `visible()` in static/app.js.

A saved search stores the page state: q, max_mi, min, max, days, condition, categories,
local_only, exact, hide_dealers, hide_pending, hide_relists, drops_only.
"""

from __future__ import annotations

import re
import time

DEALER_MIN = 4
# Facebook mixes property rentals into product searches. Leaf category measured 2026-10-24.
HOUSING_CATEGORIES = {"1468271819871448"}
HOUSING_BROWSE = {"propertyrentals", "propertyforsale"}
HOUSING_TITLE = re.compile(r"^\d+ beds? \d+ baths? ", re.I)
CONDITION_LABELS = {"New": "new", "Used - Like New": "used_like_new", "Used - Good": "used_good",
                    "Used - Fair": "used_fair"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def text_match(title: str | None, q: str) -> bool:
    """Every query word, minus a plural "s", is in the title, ignoring spaces ("book shelf")."""
    hay = _norm(title or "")
    words = [_norm(w) for w in q.lower().split() if len(w) > 1]
    return bool(words) and all(any(f in hay for f in _forms(w)) for w in words)


def _forms(w: str) -> set[str]:
    """The word and its singular guesses: desks -> desk, boxes -> box, shelves -> shelf."""
    out = {w}
    if len(w) > 3 and w.endswith("ves"):
        out.add(w[:-3] + "f")
    if len(w) > 3 and w.endswith("es"):
        out.add(w[:-2])
    if len(w) > 2 and w.endswith("s"):
        out.add(w[:-1])
    return out


def is_housing(r: dict) -> bool:
    return (r.get("category_id") in HOUSING_CATEGORIES or r.get("browse_cat") in HOUSING_BROWSE
            or bool(HOUSING_TITLE.match(r.get("title") or "")))


def ship_only(r: dict) -> bool:
    d = r.get("delivery") or []
    return bool(d) and all(x.startswith("SHIPPING") for x in d)


def match(r: dict, p: dict, now: float | None = None) -> bool:
    """Every filter except the query text, which the caller applies (index match or search hit)."""
    now = now or time.time()
    if r.get("sold") or r.get("gone") or is_housing(r):
        return False
    max_mi = float(p.get("max_mi") or 10)
    # Distance must be known: a pin, or a ring band (pickup listings only). A listing with
    # neither is not shown to be in range, so it does not match.
    if r.get("miles") is not None:
        if r["miles"] > max_mi:
            return False
    elif r.get("band_hi") is None or (r.get("band_lo") or 0) >= max_mi:
        return False
    if p.get("local_only", True) and ship_only(r):
        return False
    if p.get("hide_pending") and r.get("pending"):
        return False
    if p.get("hide_dealers") and (r.get("seller_volume") or 1) >= DEALER_MIN:
        return False
    if p.get("hide_relists") and (r.get("relist_count") or 1) > 1:
        return False
    if p.get("drops_only") and not (r.get("drop") or 0) > 0:
        return False
    price = r.get("price")
    if p.get("min") not in (None, "") and price is not None and price < float(p["min"]):
        return False
    if p.get("max") not in (None, "") and price is not None and price > float(p["max"]):
        return False
    if p.get("days") and r.get("created") and now - r["created"] > int(p["days"]) * 86400:
        return False
    cond = CONDITION_LABELS.get(r.get("condition") or "")
    if p.get("condition") and cond and cond not in p["condition"]:
        return False
    cats = p.get("categories") or []
    if cats and r.get("browse_cat") and r["browse_cat"] not in cats:
        return False
    return not (p.get("exact") and p.get("q") and not text_match(r.get("title"), p["q"]))
