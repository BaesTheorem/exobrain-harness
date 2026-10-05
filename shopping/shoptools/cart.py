"""Shopify cart tests: the only lane that PROVES a code works.

The Ajax Cart API (`POST /cart/update.js {"discount": "A,B"}`) returns per-code `applicable`
flags and the discounted `total_price` for an anonymous cart. Comma-joined codes show whether
the store lets codes combine. Each run first applies a nonsense code and aborts if the store
reports it as applicable. Nothing ever reaches checkout and nothing is charged.

Small Shopify stores rate-limit hard: basicallyfood.com answered 429 with a "Verifying your
connection" page after roughly 20 cart requests, and kept blocking for more than 5 minutes.
Run one test at a time. The cart has no shipping line, so a free-shipping code shows as
applicable but saves $0.
"""

from __future__ import annotations

import itertools
import re
import sys
import time
from typing import Literal
from urllib.parse import urlparse

from .codes import bare_domain, harvest
from .common import session


class Shopify:
    def __init__(self, product_url: str):
        u = urlparse(product_url)
        self.base = f"{u.scheme or 'https'}://{u.netloc}"
        m = re.search(r"/products/([^/?#]+)", u.path)
        if not m:
            raise SystemExit(f"not a Shopify product URL (no /products/<handle>): {product_url}")
        self.handle = m.group(1)
        self.s = session()

    def _req(self, method: Literal["GET", "POST"], path: str, **kw):
        # Shopify's bot check answers 429 once requests come too fast (two parallel
        # runs were enough on 2026-09-23). Back off and retry, then give up clearly.
        for wait in (15, 30, 60, 0):
            r = self.s.request(method, f"{self.base}{path}", timeout=25, **kw)
            if r.status_code != 429:
                return r
            if wait:
                print(f"429 from {self.base}; waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
        raise SystemExit(f"{self.base} kept rate-limiting (429). Wait a few minutes, run one test at a time.")

    def product(self) -> dict:
        r = self._req("GET", f"/products/{self.handle}.js")
        try:
            data = r.json() if r.status_code == 200 else None
        except ValueError:
            data = None
        if not isinstance(data, dict) or "variants" not in data:
            raise SystemExit(f"{self.base} does not answer the Shopify product API (HTTP {r.status_code}). "
                             "Wrong handle, not a Shopify store, or a headless one; test codes by hand at checkout.")
        return data

    def fill(self, variant: int, qty: int, selling_plan: int | None = None) -> None:
        item: dict = {"id": variant, "quantity": qty}
        if selling_plan:
            item["selling_plan"] = selling_plan
        self._req("POST", "/cart/clear.js")
        r = self._req("POST", "/cart/add.js", json={"items": [item]})
        if r.status_code != 200:
            raise SystemExit(f"add to cart failed (HTTP {r.status_code}): {r.text[:200]}")

    def apply(self, codes: list[str]) -> dict:
        r = self._req("POST", "/cart/update.js", json={"discount": ",".join(codes)})
        c = r.json()
        return {
            "codes": codes,
            "applicable": [d["code"] for d in c.get("discount_codes", []) if d.get("applicable")],
            "subtotal": c["original_total_price"] / 100,
            "total": c["total_price"] / 100,
            "currency": c.get("currency", ""),
        }


def run(url: str, codes: list[str], variant: int | None = None, qty: int = 1, harvest_more: bool = False,
        max_stack: int = 3, selling_plan: int | None = None) -> dict:
    shop = Shopify(url)
    prod = shop.product()
    variants = prod["variants"]
    if variant:
        v = next((x for x in variants if x["id"] == variant), None)
        if v is None:
            raise SystemExit(f"variant {variant} not on this product; ids: {[x['id'] for x in variants]}")
    else:
        v = next((x for x in variants if x.get("available")), variants[0])
    shop.fill(v["id"], qty, selling_plan)

    cands = list(dict.fromkeys(codes))
    if harvest_more:
        cands += [c["code"] for c in harvest(bare_domain(shop.base), [], guess=True) if c["code"] not in cands]

    # Instrument check: a nonsense code must come back not applicable. If it
    # "applies", the store auto-discounts everything and results mean nothing.
    ctrl = shop.apply(["ZZNOTACODE9137"])
    if ctrl["applicable"]:
        raise SystemExit("control failed: a nonsense code reported applicable; this cart cannot tell good codes from bad")
    base_total = ctrl["total"]

    singles = []
    for c in cands:
        res = shop.apply([c])
        res["saves"] = round(base_total - res["total"], 2)
        singles.append(res)
        time.sleep(1.0)
    live = [r for r in singles if r["applicable"]]
    live.sort(key=lambda r: -r["saves"])

    combos = []
    pool = [r["codes"][0] for r in live]
    for k in range(2, min(max_stack, len(pool)) + 1):
        for combo in itertools.combinations(pool, k):
            res = shop.apply(list(combo))
            res["saves"] = round(base_total - res["total"], 2)
            combos.append(res)
            time.sleep(1.0)
    shop.apply([])

    everything = live + combos
    best = min(everything, key=lambda r: r["total"]) if everything else None
    return {
        "store": shop.base, "product": prod["title"], "variant": v.get("title"), "variant_id": v["id"],
        "qty": qty, "base_total": base_total, "tested": len(cands),
        "working": live, "combos": combos, "best": best,
    }


def print_result(r: dict) -> None:
    print(f"{r['product']} ({r['variant']}) x{r['qty']} at {r['store']}")
    print(f"cart before codes: {r['base_total']:.2f}   codes tested: {r['tested']}")
    for w in r["working"]:
        note = "  (applies; saves 0 in cart, likely free shipping or a threshold)" if w["saves"] == 0 else ""
        print(f"  OK  {w['codes'][0]:<22} -{w['saves']:.2f} -> {w['total']:.2f}{note}")
    for c in r["combos"]:
        print(f"  +   {'+'.join(c['codes']):<22} -{c['saves']:.2f} -> {c['total']:.2f}  applied: {c['applicable']}")
    if r["best"]:
        b = r["best"]
        print(f"BEST: {'+'.join(b['applicable'])} -> {b['total']:.2f} {b['currency']} (saves {b['saves']:.2f})")
    else:
        print("BEST: no code applied")
