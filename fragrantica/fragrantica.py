#!/usr/bin/env python3
"""Read Fragrantica: search, perfume records with the community vote data, and bulk lists.

Fragrantica sits behind Cloudflare, and the vote data on a perfume page (rating,
gender, longevity, sillage, seasons, "reminds me of") is an encrypted payload that
the site's own JavaScript opens in the browser. This tool gets both:

- Pages and search: curl_cffi with a browser TLS fingerprint. Cloudflare passes it.
- Search and lists: Fragrantica's Algolia index (name, brand, year, marketed gender,
  rating, vote count), with the public search key that every page carries.
- Vote data: one headless Chrome tab loads a perfume page with EVERY request served
  through curl_cffi, so Cloudflare never sees the browser. The page's own opener,
  window._pd, then decrypts the payloads of any page that curl_cffi fetched.

Usage:
  fragrantica search "encre noire"
  fragrantica get "terre d'hermes"            # name, id or URL; prints a summary
  fragrantica get 1834 31861 --json           # one JSON record per line
  fragrantica list --min-votes 5000 --gender male --sort rating --limit 50
  fragrantica batch --min-votes 3000 --out /tmp/perfumes.jsonl   # records for a whole list
  fragrantica batch --ids-file ids.txt --out records.jsonl

INVARIANTS (do not break when editing):
- Every network request goes through curl_cffi. The browser route handler fulfills
  each request itself and aborts other hosts and images, fonts, CSS and media.
  A direct browser request meets the Cloudflare challenge (it did not pass within 35 s in tests).
- Headless only. Never open a visible browser window.
- PACING: at least --delay seconds (default 1.0) between perfume page fetches and
  ALGOLIA_PACE between search requests. Back off on 403 and 429.
- No account, cookie import or identity header. The impersonation headers only.
- Records are cached as JSON in fragrantica/cache/ (gitignored). Raw pages are not
  kept, because each one is 1.4 to 1.9 MB.
- Field names in records are stable: other scripts read them (see README).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from curl_cffi.requests import AsyncSession

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
REC_DIR = CACHE / "perfumes"
KEY_FILE = CACHE / "algolia.json"
BASE = "https://www.fragrantica.com"
ALGOLIA_PACE = 0.35
ALGOLIA_MAX = 1000  # Algolia's default pagination limit per query
DROP_HEADERS = {"content-encoding", "content-length", "transfer-encoding", "connection", "set-cookie", "alt-svc"}
GENDER_KEYS = [("female", "female", 0.0), ("female_unisex", "more_female", 0.25), ("unisex", "unisex", 0.5),
               ("male_unisex", "more_male", 0.75), ("male", "male", 1.0)]
RATING_KEYS = {"5": "love", "4": "like", "3": "ok", "2": "dislike", "1": "hate"}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def perfume_url(pid: int | str) -> str:
    # The slug is ignored by the site; the trailing id selects the perfume.
    return f"{BASE}/perfume/x/x-{pid}.html"


class Client:
    """curl_cffi session with pacing, retries, the Algolia key and the lazy opener."""

    def __init__(self, delay: float = 1.0) -> None:
        self.http = AsyncSession(impersonate="chrome", timeout=45)
        # The opener tab gets its own session: its traffic (Cloudflare telemetry included)
        # once poisoned the shared cookies, and every later page fetch got 403.
        self.http_browser = AsyncSession(impersonate="chrome", timeout=45)
        self.delay = delay
        self._last_page = 0.0
        self._last_algolia = 0.0
        self._key: dict[str, Any] | None = None
        self._pw: Any = None
        self._browser: Any = None
        self._page: Any = None

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        await self.http.close()
        await self.http_browser.close()

    async def fetch(self, url: str, *, paced: bool = True) -> str:
        if paced:
            wait = self._last_page + self.delay - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        for attempt in range(4):
            r = await self.http.get(url, headers={"Referer": BASE + "/"})
            self._last_page = time.monotonic()
            if r.status_code == 200 and "Just a moment" not in r.text[:3000]:
                return r.text
            if r.status_code in (403, 429, 500, 502, 503, 504) or "Just a moment" in r.text[:3000]:
                backoff = 10 * (attempt + 1)
                log(f"  {r.status_code} on {url}; new session, waiting {backoff} s")
                await self.http.close()
                self.http = AsyncSession(impersonate="chrome", timeout=45)
                await asyncio.sleep(backoff)
                continue
            raise RuntimeError(f"HTTP {r.status_code} for {url}")
        raise RuntimeError(f"gave up on {url} after retries (Cloudflare or rate limit)")

    # ---------- Algolia ----------
    async def algolia_key(self) -> dict[str, Any]:
        if self._key and self._key["valid_until"] > time.time() + 600:
            return self._key
        if KEY_FILE.exists():
            k = json.loads(KEY_FILE.read_text())
            if k.get("valid_until", 0) > time.time() + 3600:
                self._key = k
                return k
        html = await self.fetch(BASE + "/", paced=False)
        app = re.search(r'"algoliaAppId":"(\w+)"', html)
        key = re.search(r'let toAbby = "([^"]+)"', html)
        until = re.search(r"let validUntil = (\d+)", html)
        if not (app and key):
            raise RuntimeError("Algolia app id or search key not found on the home page")
        k = {"app": app.group(1), "key": key.group(1), "valid_until": int(until.group(1)) if until else int(time.time()) + 86400}
        CACHE.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_text(json.dumps(k))
        self._key = k
        return k

    async def algolia(self, params: dict[str, Any], index: str = "fragrantica_perfumes", _tries: int = 0) -> dict[str, Any]:
        k = await self.algolia_key()
        wait = self._last_algolia + ALGOLIA_PACE - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        q = "&".join(f"{a}={quote(json.dumps(v) if not isinstance(v, str) else v)}" for a, v in params.items())
        r = await self.http.post(f"https://{k['app'].lower()}-dsn.algolia.net/1/indexes/*/queries",
                                 json={"requests": [{"indexName": index, "params": q}]},
                                 headers={"x-algolia-application-id": k["app"], "x-algolia-api-key": k["key"],
                                          "Origin": BASE, "Referer": BASE + "/"})
        self._last_algolia = time.monotonic()
        if r.status_code == 429 and _tries < 17:
            # The public key has a rate limit: approximately 150 queries in 10 minutes got 429 on 2026-11-08.
            # The reset time is unknown, so wait up to approximately 75 min in total.
            wait_s = min(300, 60 * (_tries + 1))
            log(f"  Algolia 429 (hourly query quota); waiting {wait_s} s")
            await asyncio.sleep(wait_s)
            return await self.algolia(params, index, _tries + 1)
        if r.status_code != 200:
            raise RuntimeError(f"Algolia HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["results"][0]

    async def search(self, query: str, limit: int = 10, numeric: list[str] | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"query": query, "hitsPerPage": str(limit), "attributesToRetrieve": ATTRS}
        if numeric:
            params["numericFilters"] = numeric
        return [hit_row(h) for h in (await self.algolia(params))["hits"]]

    async def enumerate(self, min_votes: int, max_votes: int = 200000) -> list[dict[str, Any]]:
        """Every perfume with min_votes <= votes <= max_votes.

        The public search key caps a page at 30 hits and Algolia stops paging at 1000 hits,
        so a vote range with more than 1000 perfumes is split in two first.
        """
        nf = [f"votes>={min_votes}", f"votes<={max_votes}"]
        first = await self.algolia({"query": "", "hitsPerPage": "1000", "page": "0", "attributesToRetrieve": ATTRS, "numericFilters": nf})
        n = int(first.get("nbHits", 0))
        if n > ALGOLIA_MAX and max_votes > min_votes:
            mid = (min_votes + max_votes) // 2
            return await self.enumerate(min_votes, mid) + await self.enumerate(mid + 1, max_votes)
        rows = [hit_row(h) for h in first["hits"]]
        for page in range(1, int(first.get("nbPages", 1))):
            res = await self.algolia({"query": "", "hitsPerPage": "1000", "page": str(page), "attributesToRetrieve": ATTRS,
                                      "numericFilters": nf})
            rows += [hit_row(h) for h in res["hits"]]
        if len(rows) < min(n, ALGOLIA_MAX):
            log(f"  warning: votes {min_votes}-{max_votes}: got {len(rows)} of {n} hits")
        return rows

    async def listing(self, min_votes: int, max_age_days: float = 7) -> list[dict[str, Any]]:
        """enumerate() through a cache: a cached list with a lower vote floor is filtered, not re-queried."""
        now = time.time()
        for f in sorted(CACHE.glob("list-*.json"), key=lambda q: int(q.stem.split("-")[1])):
            floor = int(f.stem.split("-")[1])
            data = json.loads(f.read_text())
            if floor <= min_votes and now - data["at"] < max_age_days * 86400:
                return [r for r in data["rows"] if (r.get("votes") or 0) >= min_votes]
        rows = await self.enumerate(min_votes)
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / f"list-{min_votes}.json").write_text(json.dumps({"at": now, "rows": rows}, ensure_ascii=False))
        return rows

    # ---------- opener (headless Chrome, every request via curl_cffi) ----------
    async def _route(self, route: Any, request: Any) -> None:
        host = urlparse(request.url).hostname or ""
        if (not host.endswith("fragrantica.com") or "/cdn-cgi/" in request.url
                or request.resource_type in ("image", "font", "media", "stylesheet")):
            await route.abort()
            return
        hdrs = {k: v for k, v in request.headers.items() if k.lower() in ("referer", "content-type", "x-requested-with", "accept")}
        try:
            r = await self.http_browser.request(request.method, request.url, headers=hdrs, data=request.post_data_buffer)
        except Exception:  # noqa: BLE001 - a failed asset must not kill the opener page
            await route.abort()
            return
        await route.fulfill(status=r.status_code, headers={k: v for k, v in r.headers.items() if k.lower() not in DROP_HEADERS},
                            body=r.content)

    async def opener(self) -> Any:
        if self._page is not None:
            return self._page
        from patchright.async_api import async_playwright  # heavy import, only when needed
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(channel="chrome", headless=True)
        ctx = await self._browser.new_context(locale="en-US")
        await ctx.route("**/*", self._route)
        page = await ctx.new_page()
        await page.goto(perfume_url(31861), wait_until="domcontentloaded", timeout=90000)
        for _ in range(60):
            if await page.evaluate("typeof window._pd", isolated_context=False) == "function":
                self._page = page
                return page
            await asyncio.sleep(0.5)
        raise RuntimeError("window._pd never appeared; Fragrantica changed its page code")

    async def open_payload(self, payload: dict[str, Any] | None) -> Any:
        if not payload:
            return None
        page = await self.opener()
        out = await page.evaluate("async (p) => JSON.stringify(await window._pd(p))", payload, isolated_context=False)
        return json.loads(out)

    # ---------- records ----------
    async def record(self, pid: int, fresh: bool = False, max_age_days: float = 30) -> dict[str, Any]:
        path = REC_DIR / f"{pid}.json"
        if path.exists() and not fresh:
            rec = json.loads(path.read_text())
            age = time.time() - datetime.fromisoformat(rec["fetched_at"]).timestamp()
            if age < max_age_days * 86400:
                return rec
        html = await self.fetch(perfume_url(pid))
        rec = parse_page(html, pid)
        status = await self.open_payload(sealed(html, "status"))
        similar = await self.open_payload(sealed(html, "similar_perfumes"))
        rec.update(votes_from_status((status or {}).get("status", {})))
        rec["similar"] = similar_rows(similar)
        rec["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        REC_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec, ensure_ascii=False))
        return rec


ATTRS = ["id", "naslov", "dizajner", "slug", "spol", "godina", "rating", "votes", "magnitude"]


def hit_row(h: dict[str, Any]) -> dict[str, Any]:
    pid = h.get("id") or h.get("objectID")
    return {"id": int(pid) if pid is not None else None, "name": h.get("naslov"), "brand": h.get("dizajner"),
            "year": h.get("godina"), "marketed_gender": h.get("spol"), "rating": h.get("rating"), "votes": h.get("votes"),
            "popularity": h.get("magnitude"), "url": f"{BASE}/perfume/{h.get('slug')}-{pid}.html"}


def sealed(html: str, var: str) -> dict[str, Any] | None:
    m = re.search(r"let\s+%s\s*=\s*(\{\"ct\".*?\});" % re.escape(var), html, re.S)
    return json.loads(m.group(1)) if m else None


def parse_page(html: str, pid: int) -> dict[str, Any]:
    rec: dict[str, Any] = {"id": pid, "url": None}
    m = re.search(r'<link rel="canonical" href="([^"]+)"', html)
    rec["url"] = m.group(1) if m else perfume_url(pid)
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    rec["title"] = text(m.group(1)) if m else None
    m = re.search(r'itemprop="brand".*?itemprop="name">\s*(.*?)\s*<', html, re.S)
    rec["brand"] = text(m.group(1)) if m else None
    d = re.search(r'itemprop="description">\s*<p>(.*?)</p>', html, re.S)
    desc = text(d.group(1)) if d else ""
    m = re.match(r"(.*?) by (.*?) is an? (.*?) fragrance for (women and men|women|men)\.", desc)
    if m:
        rec["name"], rec["family"] = m.group(1), m.group(3)
        rec["marketed_gender"] = {"women and men": "unisex", "women": "female", "men": "male"}[m.group(4)]
    else:
        title = rec.get("title")
        rec["name"] = title.split(" - ")[0] if isinstance(title, str) else None
        rec["family"] = rec["marketed_gender"] = None
    m = re.search(r"was launched in (\d{4})", desc)
    rec["year"] = int(m.group(1)) if m else None
    m = re.search(r"The noses? behind this fragrance (?:is|are) (.*?)\.", desc)
    rec["perfumers"] = [p.strip() for p in re.split(r",| and ", m.group(1)) if p.strip()] if m else []
    # main accords: bar width = relative strength (top accord = 100)
    acc: list[dict[str, Any]] = []
    i = html.find(">main accords<")
    if i >= 0:
        seg = html[i:i + 12000]
        for width, name in re.findall(r'width:\s*([\d.]+)%;"[^>]*>\s*<span class="truncate">([^<]+)</span>', seg):
            acc.append({"name": text(name), "strength": round(float(width), 1)})
    rec["accords"] = acc
    # note pyramid; the page gives each note image its own width (rem)
    notes: dict[str, list[dict[str, Any]]] = {}
    for level, body in re.findall(r'<pyramid-level-new notes="(\w+)">(.*?)</pyramid-level-new>', html, re.S):
        items = re.findall(r'style="width:\s*([\d.]+)rem;"\s*alt="([^"]*)"', body)
        if items:
            notes["notes" if level == "ingredients" else level] = [{"note": unescape(a), "size": float(w)} for w, a in items]
    rec["notes"] = notes
    return rec


def _dist(obj: Any, names: dict[str, str] | None = None) -> dict[str, int]:
    if not isinstance(obj, dict):
        return {}
    lookup = names or {}
    return {(lookup[k] if k in lookup else str(k)): int(v) for k, v in obj.items()}


def votes_from_status(st: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    rd = _dist(st.get("rating"), RATING_KEYS)
    out["rating"] = {"avg": st.get("rating_average"), "votes": st.get("people") or st.get("rating_sum"), "dist": rd}
    graw = st.get("gender")
    g: dict[str, Any] = graw if isinstance(graw, dict) else {}
    gv = {name: int(g.get(key, 0)) for key, name, _ in GENDER_KEYS}
    total = sum(gv.values())
    out["gender_votes"] = gv | {"total": total}
    out["male_share"] = round((gv["male"] + gv["more_male"]) / total, 4) if total else None
    out["female_share"] = round((gv["female"] + gv["more_female"]) / total, 4) if total else None
    out["masc_index"] = round(sum(gv[name] * w for _, name, w in GENDER_KEYS) / total, 4) if total else None
    for key, top in (("longevity", 5), ("sillage", 4), ("price_value", 5)):
        out[key] = {"avg": st.get(f"{key}_average"), "votes": st.get(f"{key}_sum"), "dist": _dist(st.get(key)), "scale": f"1-{top}"}
    out["seasons"] = {k: st.get(src) for k, src in (("winter", "winter"), ("spring", "spring"), ("summer", "summer"),
                                                     ("fall", "autumn"), ("day", "day"), ("night", "night"))}
    out["relation"] = _dist(st.get("relation"))
    return out


def similar_rows(sim: Any) -> list[dict[str, Any]]:
    rows = []
    for s in (sim or {}).get("similar_perfumes", []) if isinstance(sim, dict) else []:
        p = s.get("perfume") or {}
        rows.append({"id": p.get("id"), "name": p.get("naslov"), "brand": p.get("dizajner"), "marketed_gender": p.get("spol"),
                     "votes": s.get("votes"), "yes": s.get("vote_yes"), "no": s.get("vote_no"),
                     "url": BASE + p["perfume_url"] if p.get("perfume_url") else None})
    return rows


async def resolve(c: Client, target: str) -> int:
    if target.isdigit():
        return int(target)
    m = re.search(r"-(\d+)\.html", target)
    if m and urlparse(target).hostname:
        return int(m.group(1))
    hits = await c.search(target, limit=1)
    if not hits:
        raise SystemExit(f"no Fragrantica match for {target!r}")
    log(f"  {target!r} -> {hits[0]['brand']} {hits[0]['name']} ({hits[0]['year']}), id {hits[0]['id']}")
    return int(hits[0]["id"])


def summary(r: dict[str, Any]) -> str:
    g = r.get("gender_votes") or {}
    rt = r.get("rating") or {}
    lines = [f"{r.get('brand')} {r.get('name')} ({r.get('year')}), {r.get('family')}, marketed {r.get('marketed_gender')}",
             f"  {r.get('url')}",
             f"  rating {rt.get('avg')} / 5 from {rt.get('votes')} votes  {rt.get('dist')}",
             f"  gender votes {g}  male share {r.get('male_share')}  masc index {r.get('masc_index')}",
             f"  longevity {r['longevity']['avg']} / 5  sillage {r['sillage']['avg']} / 4  price value {r['price_value']['avg']} / 5",
             f"  perfumers: {', '.join(r.get('perfumers') or []) or '?'}",
             "  accords: " + ", ".join(f"{a['name']} {a['strength']:.0f}" for a in r.get("accords", [])),
             ]
    for level, items in (r.get("notes") or {}).items():
        lines.append(f"  {level}: " + ", ".join(i["note"] for i in items))
    if r.get("similar"):
        lines.append("  reminds voters of: " + "; ".join(f"{s['brand']} {s['name']} ({s['yes']}/{s['no']})" for s in r["similar"][:8]))
    return "\n".join(lines)


async def amain(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="fragrantica", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="name search through Fragrantica's Algolia index")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--json", action="store_true")
    g = sub.add_parser("get", help="full records (decrypted votes) by id, URL or name")
    g.add_argument("targets", nargs="+")
    g.add_argument("--json", action="store_true")
    g.add_argument("--fresh", action="store_true", help="ignore the cache")
    for name in ("list", "batch"):
        p = sub.add_parser(name, help="all perfumes over a vote floor" if name == "list" else "records for a list or an id file")
        p.add_argument("--min-votes", type=int, default=5000)
        p.add_argument("--gender", choices=["male", "female", "unisex"], help="marketed gender filter")
        p.add_argument("--limit", type=int, default=0, help="0 = all")
        p.add_argument("--sort", choices=["rating", "votes", "popularity"], default="votes")
        if name == "list":
            p.add_argument("--json", action="store_true")
        else:
            p.add_argument("--ids-file", help="one id or Fragrantica URL per line (overrides the list filters)")
            p.add_argument("--out", required=True, help="JSONL output path")
            p.add_argument("--delay", type=float, default=1.0)
            p.add_argument("--fresh", action="store_true")
    a = ap.parse_args(argv)
    c = Client(delay=getattr(a, "delay", 1.0))
    try:
        if a.cmd == "search":
            rows = await c.search(a.query, a.limit)
            for row in rows:
                print(json.dumps(row, ensure_ascii=False) if a.json else
                      f"{row['id']:>7}  {row['brand']} {row['name']} ({row['year']}, {row['marketed_gender']})  {row['rating']} from {row['votes']}")
        elif a.cmd == "get":
            for t in a.targets:
                rec = await c.record(await resolve(c, t), fresh=a.fresh)
                print(json.dumps(rec, ensure_ascii=False) if a.json else summary(rec))
        else:
            if a.cmd == "batch" and a.ids_file:
                ids = []
                for line in Path(a.ids_file).read_text().split():
                    m = re.search(r"(\d+)(?:\.html)?$", line.strip())
                    if m:
                        ids.append(int(m.group(1)))
                rows = [{"id": i} for i in ids]
            else:
                rows = await c.listing(a.min_votes)
                if a.gender:
                    rows = [r for r in rows if r["marketed_gender"] == a.gender]
                rows.sort(key=lambda r: -(r.get(a.sort) or 0))
                if a.limit:
                    rows = rows[:a.limit]
            if a.cmd == "list":
                for row in rows:
                    print(json.dumps(row, ensure_ascii=False) if a.json else
                          f"{row['id']:>7}  {row['rating']:.2f}  {row['votes']:>6}  {row['brand']} {row['name']} ({row['year']}, {row['marketed_gender']})")
                log(f"{len(rows)} perfumes")
            else:
                done = 0
                with open(a.out, "w") as fh:
                    for row in rows:
                        try:
                            rec = await c.record(int(row["id"]), fresh=a.fresh)
                        except Exception as e:  # noqa: BLE001 - record the failure, keep the batch going
                            log(f"  id {row['id']}: {e}")
                            continue
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        fh.flush()
                        done += 1
                        if done % 10 == 0 or done == len(rows):
                            log(f"  {done}/{len(rows)} records")
                log(f"wrote {done} of {len(rows)} records to {a.out}")
    finally:
        await c.close()
    return 0


def main() -> None:
    sys.exit(asyncio.run(amain(sys.argv[1:])))


if __name__ == "__main__":
    main()
