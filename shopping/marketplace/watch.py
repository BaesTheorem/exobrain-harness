"""Marketplace watcher: keep the index fresh and send saved-search alerts as one digest.

launchd runs this every 30 minutes (shopping/marketplace/com.exobrain.marketplace-watch.plist).
Each run:

1. Sweeps the index if the last sweep is more than 2 hours old (shared lock with the server).
2. For each saved search with alerts on: runs the query newest first at its radius (about two
   pages), then takes every index listing that passes the search's filters and matches its words
   in the title, plus every listing Facebook returned for the query.
3. Compares with what that search already saw (`alert_seen`). The first run seeds silently.
   A new listing alerts. A price drop alerts. A relist of an item the search already saw alerts
   only when the price is lower.
4. Fetches the pin for each alert, rechecks the distance, then sends ONE digest for the whole run
   through mist-notify --discord (banner plus Discord DM).

No language model runs here: the listings are data and go out as data.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
import time
from urllib.parse import urlencode

from shoptools.common import HARNESS, LaneError

from . import filters
from .crawl import Crawler
from .store import DATA, Store

NOTIFY = HARNESS / "mist-voice" / "bin" / "mist-notify"
LOG = DATA / "watch.log"
QUIET = (0, 7)              # no runs from midnight to 7 am; the 7 am run catches up
APP = "http://127.0.0.1:5041/"
MAX_LINES = 12


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def dist_text(r: dict) -> str:
    if r.get("miles") is not None:
        return f"{r['miles']:.1f} mi"
    if r.get("band_hi") is not None:
        lo, hi = r.get("band_lo") or 0, r["band_hi"]
        return f"{lo:g}-{hi:g} mi" if lo else f"under {hi:g} mi"
    return "distance unknown"


def price_text(r: dict) -> str:
    if r.get("price") == 0:
        return "Free"
    return r.get("formatted") or (f"${r['price']:,.0f}" if r.get("price") is not None else "no price")


def search_alerts(store: Store, crawler: Crawler, saved: dict, rows_by_id: dict[str, dict]) -> list[tuple[str, dict, str]]:
    """(kind, row, note) for one saved search. Also records what the search has now seen."""
    name, p = saved["name"], saved["params"]
    q = (p.get("q") or "").strip()
    hits: set[str] = set()
    if q:
        job = crawler.new_job({"q": q, "max_mi": p.get("max_mi"), "min": p.get("min") or None,
                               "max": p.get("max") or None, "days": None, "condition": p.get("condition") or [],
                               "local_only": p.get("local_only", True)}, rings=[float(p.get("max_mi") or 10)])
        crawler.run_job(job, sort="date", pages=2)
        if job.warnings:
            log(f"[{name}] search warning: {job.warnings[0]}")
        hits = set(job.ids)
        crawler.drain_hashes()
        for r in store.rows(job.ids):
            rows_by_id[r["id"]] = r
    now = time.time()
    cands = {i: r for i, r in rows_by_id.items()
             if filters.match(r, p, now) and (not q or i in hits or filters.text_match(r.get("title"), q))}
    seen = store.alert_seen(name)
    if not seen:
        store.mark_alert_seen(name, {i: r.get("price") for i, r in cands.items()})
        log(f"[{name}] first run: seeded {len(cands)} listings, no alert")
        return []
    by_key: dict[str, list[str]] = {}
    for i, r in rows_by_id.items():
        by_key.setdefault(r.get("relist_key") or i, []).append(i)
    out = []
    for i, r in cands.items():
        price = r.get("price")
        if i not in seen:
            siblings = [s for s in by_key.get(r.get("relist_key") or i, []) if s != i and s in seen]
            if siblings:
                was = min((v for s in siblings if (v := seen[s]) is not None), default=None)
                if was is not None and price is not None and price < was:
                    out.append(("relisted lower", r, f"was ${was:,.0f}"))
            else:
                out.append(("new", r, ""))
        elif price is not None and seen[i] is not None and price < seen[i]:
            out.append(("price drop", r, f"was ${seen[i]:,.0f}"))
    # Pin each alert and recheck: a ring band can straddle the search's radius.
    kept = []
    for kind, r, note in out:
        if r.get("enriched_at") is None:
            try:
                crawler.locate_now(r["id"])
                r = next(iter(store.rows([r["id"]])), r)
            except LaneError as e:
                log(f"[{name}] pin failed for {r['id']}: {e}")
            time.sleep(1)
        if filters.match(r, p, now):
            kept.append((kind, r, note))
    store.mark_alert_seen(name, {i: r.get("price") for i, r in cands.items()})
    log(f"[{name}] {len(cands)} matching, {len(kept)} to alert")
    return kept


def digest(found: dict[str, list[tuple[str, dict, str]]]) -> tuple[str, str, str]:
    total = sum(len(v) for v in found.values())
    lines = []
    shown = 0
    for name, items in found.items():
        if not items:
            continue
        lines.append(f"{name}:")
        for kind, r, note in items:
            if shown >= MAX_LINES:
                break
            tag = "" if kind == "new" else f" ({kind}{', ' + note if note else ''})"
            lines.append(f"- {price_text(r)} {r.get('title', '')[:60]}{tag}, {dist_text(r)}: {r['url']}")
            shown += 1
    if total > shown:
        lines.append(f"... and {total - shown} more in Curbside.")
    title = f"Marketplace: {total} new match{'es' if total != 1 else ''}"
    first = next(r for v in found.values() for _, r, _ in v)
    link = first["url"] if total == 1 else APP
    return title, "\n".join(lines), link


def main() -> int:
    hour = dt.datetime.now().hour
    if QUIET[0] <= hour < QUIET[1] and "--now" not in sys.argv:
        return 0
    store = Store()
    crawler = Crawler(store, background=False)
    alerting = [s for s in store.saved() if s.get("alert")]
    try:
        if crawler.sweep_due() or "--sweep" in sys.argv:
            t = time.time()
            new_ids = crawler.sweep()
            if new_ids is None:
                log("sweep skipped: another process is sweeping")
            else:
                st = crawler.sweep_status()
                log(f"sweep: {len(new_ids)} new listings, {st.get('pages')} pages, {time.time() - t:.0f}s"
                    + (f", error: {st['error']}" if st.get("error") else ""))
                crawler.drain_hashes()
        if not alerting:
            return 0
        rows_by_id = {r["id"]: r for r in store.index(0)}
        found = {s["name"]: search_alerts(store, crawler, s, rows_by_id) for s in alerting}
    except LaneError as e:
        log(f"error: {e}")
        subprocess.run([str(NOTIFY), f"Curbside watcher stopped: {e}", "Marketplace", "Basso", APP,
                        "--discord", "--context", str(e)], check=False)
        return 1
    if not any(found.values()):
        return 0
    title, body, link = digest(found)
    q = next((s for s in alerting if found.get(s["name"])), None)
    if q and link == APP:
        link = APP + "#" + urlencode({k: (",".join(v) if isinstance(v, list) else v)
                                      for k, v in q["params"].items() if v not in ("", None, False, [])})
    log(f"alert: {title}")
    subprocess.run([str(NOTIFY), f"{title}\n{body}", "Marketplace", "Purr", link, "--discord",
                    "--group", "marketplace", "--context", f"Curbside saved-search digest\n{body}"], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

