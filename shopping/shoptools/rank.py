"""Rank every source x every legal code subset by net cost.

`best` is arithmetic, not a measurement. It applies percent codes before fixed ones, then
shipping, then tax, then the gift-card discount on what you pay, then cashback on the
post-code subtotal. Rows are `verified` only when every code in them was confirmed on a cart.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path


def _price(offer: dict, codes: list[dict]) -> dict:
    sub = offer["price"] * offer.get("qty", 1)
    ship = offer.get("shipping", 0.0)
    for c in codes:
        if sub < c.get("min_subtotal", 0):
            return {}
    after = sub
    # Percent codes compound on the subtotal, then fixed amounts come off. Most
    # carts work this way, but not all, so the result stays an estimate until tested.
    for c in (c for c in codes if c["type"] == "pct"):
        after *= 1 - c["value"] / 100
    for c in (c for c in codes if c["type"] == "fixed"):
        after -= c["value"]
    after = max(after, 0.0)
    if any(c["type"] == "freeship" for c in codes):
        ship = 0.0
    tax = after * offer.get("tax_rate", 0.0)
    total = after + ship + tax
    cash = total * (1 - offer.get("giftcard_pct", 0) / 100)
    back = after * offer.get("cashback_pct", 0) / 100
    return {
        "source": offer["source"], "url": offer.get("url", ""),
        "codes": [c["code"] for c in codes],
        "checkout_total": round(total, 2), "out_of_pocket": round(cash, 2),
        "cashback": round(back, 2), "net": round(cash - back, 2),
        # No codes means the listed shelf price, which was read directly.
        "verified": all(c.get("verified") for c in codes),
    }


def run(path: Path) -> dict:
    data = json.loads(path.read_text())
    rows = []
    for offer in data["offers"]:
        codes = offer.get("codes", [])
        limit = offer.get("max_codes", 1)
        for k in range(0, min(limit, len(codes)) + 1):
            for combo in itertools.combinations(codes, k):
                if k > 1 and not all(c.get("stackable", False) for c in combo):
                    continue
                if r := _price(offer, list(combo)):
                    rows.append(r)
    rows.sort(key=lambda r: (r["net"], not r["verified"]))
    # Best verified row per source, plus the best estimate when it beats that.
    best_per_source: dict[tuple[str, bool], dict] = {}
    for r in rows:
        best_per_source.setdefault((r["source"], r["verified"]), r)
    return {"item": data.get("item", ""), "ranked": sorted(best_per_source.values(), key=lambda r: r["net"]),
            "combinations_tried": len(rows)}


def print_result(r: dict) -> None:
    print(f"{r['item']}   ({r['combinations_tried']} priced combinations)")
    for x in r["ranked"]:
        tag = "verified" if x["verified"] else "estimate"
        codes = "+".join(x["codes"]) or "-"
        print(f"  {x['net']:>9.2f} net  {x['out_of_pocket']:>9.2f} paid  {x['cashback']:>6.2f} back  "
              f"{x['source']:<18} {codes:<24} [{tag}]")
