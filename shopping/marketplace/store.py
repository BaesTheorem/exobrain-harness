"""SQLite store for the Marketplace front end: every listing seen, its price history, its pin.

The database is a local index of what Facebook showed us, so the UI filters and sorts without a
round trip and keeps facts Facebook's own feed throws away (price drops, seller volume, hidden
items). It lives in `data/market.db`, gitignored: it holds other people's listings and names.

INVARIANTS
- A distance band only gets tighter. A listing does not move, so a wider band from a later
  search never replaces a narrower one.
- Exact coordinates come only from the item page (`fbm.item`), never from a guess.
- `price_history` gets a row only when the price differs from the last recorded price.
- Listings in one `photo_group` have primary photos within PHASH_MAX bits of each other. A new
  hash joins the oldest matching group, and groups it bridges merge into that one.
- A relist group never crosses sellers. Two listings by one seller are one item when they share
  a photo group, or when their normalized titles match and are long enough to be specific.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data"
DB_PATH = DATA / "market.db"
KM_PER_MI = 1.609344

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    title TEXT, price REAL, formatted TEXT, was TEXT,
    city TEXT, state TEXT, created INTEGER, listed TEXT,
    seller TEXT, seller_id TEXT, category_id TEXT,
    delivery TEXT, sold INTEGER DEFAULT 0, pending INTEGER DEFAULT 0, gone INTEGER DEFAULT 0,
    photo TEXT, first_seen INTEGER, last_seen INTEGER,
    band_lo REAL, band_hi REAL,
    lat REAL, lon REAL, miles REAL,
    enriched_at INTEGER, enrich_error TEXT,
    description TEXT, condition TEXT, attributes TEXT, photos TEXT, location_text TEXT,
    seller_rating REAL, seller_rating_count INTEGER, seller_joined TEXT
);
CREATE INDEX IF NOT EXISTS listings_seller ON listings(seller_id);
CREATE TABLE IF NOT EXISTS price_history (id TEXT, ts INTEGER, price REAL);
CREATE INDEX IF NOT EXISTS price_history_id ON price_history(id);
CREATE TABLE IF NOT EXISTS hidden (kind TEXT, key TEXT, label TEXT, ts INTEGER, PRIMARY KEY (kind, key));
CREATE TABLE IF NOT EXISTS saved (name TEXT PRIMARY KEY, params TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS alert_seen (search TEXT, id TEXT, price REAL, ts INTEGER, PRIMARY KEY (search, id));
CREATE TABLE IF NOT EXISTS sweep_state (category TEXT, ring REAL, max_created INTEGER, ts INTEGER, PRIMARY KEY (category, ring));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
# Columns added after the first release; ALTER TABLE adds them to an existing database.
MIGRATIONS = (
    ("listings", "phash", "TEXT"),
    ("listings", "photo_group", "TEXT"),
    ("saved", "alert", "INTEGER DEFAULT 0"),
    ("listings", "updated", "INTEGER DEFAULT 0"),
    ("listings", "browse_cat", "TEXT"),
)
# Fields the grid needs. The rest (description, photo list, attributes) loads with the detail view.
HEAVY = ("description", "photos", "attributes", "enrich_error", "phash")
ITEM_URL = "https://www.facebook.com/marketplace/item/{}/"
# Category page slug -> id (fbm.CATEGORIES), repeated here so the store does not import the lane.
# "free" is a price, not a category, so it never names a listing's category.
TOP_CATEGORY_IDS = {
    "677457442746983": "apparel", "759201041254543": "classifieds", "479353692612078": "electronics",
    "529595287638583": "entertainment", "891748581240437": "family", "1583634935226685": "furniture",
    "1109541402725436": "garden", "459026188375950": "hobbies", "753380185098614": "home",
    "476291743038859": "home-improvements", "1078592699170502": "instruments", "586894672179024": "office-supplies",
    "197143151659643": "pets", "391335928190702": "sports", "199404184572737": "toys", "546583916084032": "vehicles",
}
CATEGORY_MAP_TTL = 600
PHASH_MAX = 5          # Hamming distance (of 64 bits) for "same photo"
TITLE_MIN = 12         # normalized title length below which a title match means nothing ("shelf")


def _alive(owner: str) -> bool:
    """Owners are "<pid>-<random>". A lock whose process is gone is free."""
    try:
        os.kill(int(owner.split("-", 1)[0]), 0)
    except (ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def ships(delivery: list[str] | None) -> bool:
    """Delivery types are IN_PERSON, DOOR_PICKUP, PUBLIC_MEETUP, SHIPPING_ONSITE, SHIPPING_OFFSITE..."""
    return any(d.startswith("SHIPPING") for d in delivery or [])


def norm_title(t: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def haversine_mi(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    p = math.radians
    x = (math.sin(p(b_lat - a_lat) / 2) ** 2
         + math.cos(p(a_lat)) * math.cos(p(b_lat)) * math.sin(p(b_lon - a_lon) / 2) ** 2)
    return 2 * 6371.0088 * math.asin(math.sqrt(x)) / KM_PER_MI


class Store:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        for table, col, decl in MIGRATIONS:
            cols = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        self.db.execute("CREATE INDEX IF NOT EXISTS listings_photo_group ON listings(photo_group)")
        self.db.execute("CREATE INDEX IF NOT EXISTS listings_updated ON listings(updated)")
        # Bands recorded for shippable listings before the rule above are not real.
        self.db.execute("UPDATE listings SET band_lo=NULL, band_hi=NULL, updated=? WHERE delivery LIKE '%SHIPPING%' "
                        "AND band_hi IS NOT NULL", (int(time.time()),))
        self.db.commit()
        self.lock = threading.Lock()
        self._hashes: dict[str, int] | None = None   # id -> phash, loaded on first use
        self._cat_map: tuple[float, dict[str, str]] = (0.0, {})

    # ------------------------------------------------------------ writes

    def upsert_card(self, r: dict, band: tuple[float, float] | None, browse_cat: str | None = None) -> None:
        """One search-card row. Records a price change and tightens the distance band.

        Facebook applies the radius to pickup listings only: a shippable listing comes back in a
        1 mi ring from Florida (2026-10-24). So a shippable listing gets no band, only a pin.
        """
        now = int(time.time())
        if ships(r.get("delivery")):
            band = None
        with self.lock, self.db:
            old = self.db.execute("SELECT price, band_lo, band_hi FROM listings WHERE id=?", (r["id"],)).fetchone()
            fields = {
                "title": r.get("title"), "price": r.get("price"), "formatted": r.get("formatted"),
                "was": r.get("was"), "city": r.get("city"), "state": r.get("state"),
                "created": r.get("created"), "listed": r.get("listed"), "seller": r.get("seller"),
                "seller_id": r.get("seller_id"), "category_id": r.get("category_id"),
                "delivery": json.dumps(r.get("delivery") or []), "sold": int(bool(r.get("sold"))),
                "pending": int(bool(r.get("pending"))), "photo": r.get("photo"), "last_seen": now,
                "updated": now,
            }
            if old is None:
                fields.update(id=r["id"], first_seen=now, gone=0, browse_cat=browse_cat)
                if band:
                    fields.update(band_lo=band[0], band_hi=band[1])
                cols = ",".join(fields)
                self.db.execute(f"INSERT INTO listings ({cols}) VALUES ({','.join('?' * len(fields))})",
                                list(fields.values()))
            else:
                if band and (old["band_hi"] is None or band[1] < old["band_hi"]
                             or (band[1] == old["band_hi"] and band[0] > (old["band_lo"] or 0))):
                    fields.update(band_lo=band[0], band_hi=band[1])
                sets = ",".join(f"{k}=?" for k in fields)
                self.db.execute(f"UPDATE listings SET {sets} WHERE id=?", [*fields.values(), r["id"]])
                if browse_cat:
                    self.db.execute("UPDATE listings SET browse_cat=? WHERE id=? AND browse_cat IS NULL",
                                    (browse_cat, r["id"]))
            last = self.db.execute("SELECT price FROM price_history WHERE id=? ORDER BY rowid DESC LIMIT 1",
                                   (r["id"],)).fetchone()
            if r.get("price") is not None and (last is None or last["price"] != r["price"]):
                self.db.execute("INSERT INTO price_history VALUES (?,?,?)", (r["id"], now, r["price"]))

    def save_item(self, d: dict, home: tuple[float, float]) -> None:
        """Full item-page row: exact pin, description, seller stats."""
        latlon = d.get("latlon")
        miles = haversine_mi(*home, *latlon) if latlon else None
        with self.lock, self.db:
            self.db.execute(
                """UPDATE listings SET lat=?, lon=?, miles=?, enriched_at=?, enrich_error=NULL, updated=?,
                   description=?, condition=?, attributes=?, photos=?, location_text=?,
                   seller_rating=?, seller_rating_count=?, seller_joined=?,
                   sold=?, pending=?, gone=? WHERE id=?""",
                (latlon[0] if latlon else None, latlon[1] if latlon else None, miles, int(time.time()), int(time.time()),
                 d.get("description"), d.get("condition"), json.dumps(d.get("attributes") or {}),
                 json.dumps(d.get("photos") or []), d.get("location_text"), d.get("seller_rating"),
                 d.get("seller_rating_count"), d.get("seller_joined"), int(bool(d.get("sold"))),
                 int(bool(d.get("pending"))), int(not d.get("live", True)), d["id"]))

    def mark_error(self, listing_id: str, msg: str, gone: bool = False) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE listings SET enrich_error=?, enriched_at=?, gone=MAX(gone, ?), updated=? WHERE id=?",
                            (msg[:300], int(time.time()), int(gone), int(time.time()), listing_id))

    def set_phash(self, listing_id: str, phash: str) -> str:
        """Record a photo hash and put the listing in a photo group. Returns the group id."""
        h = int(phash, 16)
        with self.lock, self.db:
            if self._hashes is None:
                self._hashes = {r["id"]: int(r["phash"], 16) for r in
                                self.db.execute("SELECT id, phash FROM listings WHERE phash IS NOT NULL")}
            near = [i for i, o in self._hashes.items() if i != listing_id and (h ^ o).bit_count() <= PHASH_MAX]
            group = listing_id
            if near:
                marks = ",".join("?" * len(near))
                rows = self.db.execute(f"SELECT photo_group, first_seen FROM listings WHERE id IN ({marks}) "
                                       "AND photo_group IS NOT NULL ORDER BY first_seen, id", near).fetchall()
                groups = list(dict.fromkeys(r["photo_group"] for r in rows))
                if groups:
                    group = groups[0]
                    if len(groups) > 1:
                        gm = ",".join("?" * (len(groups) - 1))
                        self.db.execute(f"UPDATE listings SET photo_group=?, updated=? WHERE photo_group IN ({gm})",
                                        [group, int(time.time()), *groups[1:]])
                # Siblings' relist and shared-photo counts change too, so they resync.
                self.db.execute("UPDATE listings SET updated=? WHERE photo_group=?", (int(time.time()), group))
            self.db.execute("UPDATE listings SET phash=?, photo_group=?, updated=? WHERE id=?",
                            (phash, group, int(time.time()), listing_id))
            self._hashes[listing_id] = h
            return group

    def local_states(self) -> set[str]:
        """States of pickup-only listings: the radius holds for those, so these states are local."""
        with self.lock:
            return {r[0] for r in self.db.execute(
                "SELECT state, COUNT(*) n FROM listings WHERE delivery NOT LIKE '%SHIPPING%' AND state IS NOT NULL "
                "GROUP BY state HAVING n >= 5")}

    def unpinned_shippers(self, states: set[str], limit: int = 200) -> list[str]:
        if not states:
            return []
        sm = ",".join("?" * len(states))
        with self.lock:
            return [r[0] for r in self.db.execute(
                f"SELECT id FROM listings WHERE delivery LIKE '%SHIPPING%' AND enriched_at IS NULL AND gone=0 "
                f"AND state IN ({sm}) ORDER BY created DESC LIMIT ?", [*states, limit])]

    def has(self, listing_id: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM listings WHERE id=?", (listing_id,)).fetchone() is not None

    def photo(self, listing_id: str) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT photo FROM listings WHERE id=?", (listing_id,)).fetchone()
        return row["photo"] if row else None

    def needs_hash(self, listing_id: str) -> bool:
        with self.lock:
            row = self.db.execute("SELECT phash, photo FROM listings WHERE id=?", (listing_id,)).fetchone()
        return row is not None and row["phash"] is None and bool(row["photo"])

    def set_alert(self, name: str, on: bool) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE saved SET alert=? WHERE name=?", (int(on), name))

    def alert_seen(self, search: str) -> dict[str, float | None]:
        with self.lock:
            return {r["id"]: r["price"] for r in self.db.execute("SELECT id, price FROM alert_seen WHERE search=?", (search,))}

    def mark_alert_seen(self, search: str, prices: dict[str, float | None]) -> None:
        now = int(time.time())
        with self.lock, self.db:
            self.db.executemany("INSERT OR REPLACE INTO alert_seen VALUES (?,?,?,?)",
                                [(search, i, p, now) for i, p in prices.items()])

    def sweep_mark(self, category: str, ring: float) -> int | None:
        with self.lock:
            row = self.db.execute("SELECT max_created FROM sweep_state WHERE category=? AND ring=?",
                                  (category, ring)).fetchone()
        return row["max_created"] if row else None

    def set_sweep_mark(self, category: str, ring: float, max_created: int) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO sweep_state VALUES (?,?,?,?)",
                            (category, ring, max_created, int(time.time())))

    def get_meta(self, key: str) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str | None) -> None:
        with self.lock, self.db:
            if value is None:
                self.db.execute("DELETE FROM meta WHERE key=?", (key,))
            else:
                self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    def try_lock(self, key: str, owner: str, ttl: int) -> bool:
        """A lock row shared by the server and the watcher (two processes, one database)."""
        now = int(time.time())
        with self.lock, self.db:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            if row:
                held_by, at = row["value"].rsplit("@", 1)
                if held_by != owner and now - int(at) < ttl and _alive(held_by):
                    return False
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, f"{owner}@{now}"))
            return True

    def index(self, since: int = 0) -> list[dict[str, Any]]:
        """Light rows for every listing changed after `since` (0 = all), for the grid."""
        with self.lock:
            # A full load skips gone listings; a delta includes them so the page can drop them.
            ids = [r[0] for r in self.db.execute("SELECT id FROM listings WHERE updated>=? AND (gone=0 OR ?>0)",
                                                 (since, since))]
            if not ids:
                return []
            rows = self._rows(ids)
        for r in rows:
            for k in HEAVY:
                r.pop(k, None)
        return rows

    def hide(self, kind: str, key: str, label: str = "") -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO hidden VALUES (?,?,?,?)", (kind, key, label, int(time.time())))

    def unhide(self, kind: str, key: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM hidden WHERE kind=? AND key=?", (kind, key))

    def save_search(self, name: str, params: dict, alert: bool = False) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO saved (name, params, ts, alert) VALUES (?,?,?,?)",
                            (name, json.dumps(params), int(time.time()), int(alert)))

    def delete_search(self, name: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM saved WHERE name=?", (name,))

    # ------------------------------------------------------------ reads

    def needs_item(self, listing_id: str) -> bool:
        with self.lock:
            row = self.db.execute("SELECT enriched_at FROM listings WHERE id=?", (listing_id,)).fetchone()
        return row is not None and row["enriched_at"] is None

    def hidden(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM hidden ORDER BY ts DESC")]

    def saved(self) -> list[dict]:
        with self.lock:
            return [{"name": r["name"], "params": json.loads(r["params"]), "alert": bool(r["alert"])}
                    for r in self.db.execute("SELECT * FROM saved ORDER BY name")]

    def rows(self, ids: list[str]) -> list[dict[str, Any]]:
        """Listings for the UI, in the order given, with the derived fields the cards show."""
        ids = list(ids)  # the crawler thread appends to the job's list while this reads it
        if not ids:
            return []
        with self.lock:
            return self._rows(ids)

    def _rows(self, ids: list[str]) -> list[dict[str, Any]]:
        marks = ",".join("?" * len(ids))
        found = {r["id"]: dict(r) for r in self.db.execute(f"SELECT * FROM listings WHERE id IN ({marks})", ids)}
        sellers = {r["seller_id"] for r in found.values() if r["seller_id"]}
        volume: dict[str, int] = {}
        if sellers:
            smarks = ",".join("?" * len(sellers))
            month = int(time.time()) - 30 * 86400
            volume = {r[0]: r[1] for r in self.db.execute(
                f"SELECT seller_id, COUNT(*) FROM listings WHERE seller_id IN ({smarks}) AND last_seen>? "
                "GROUP BY seller_id", [*sellers, month])}
        first = {r[0]: r[1] for r in self.db.execute(
            f"""SELECT id, price FROM price_history p WHERE id IN ({marks})
                AND rowid=(SELECT MIN(rowid) FROM price_history q WHERE q.id=p.id)""", ids)}
        hidden = {(r["kind"], r["key"]) for r in self.db.execute("SELECT kind, key FROM hidden")}
        relist = self._relists(sellers)
        cat_map = self._category_map()
        pgroups = {r["photo_group"] for r in found.values() if r["photo_group"]}
        photo_sellers: dict[str, int] = {}
        if pgroups:
            gm = ",".join("?" * len(pgroups))
            photo_sellers = {r[0]: r[1] for r in self.db.execute(
                f"SELECT photo_group, COUNT(DISTINCT seller_id) FROM listings WHERE photo_group IN ({gm}) "
                "GROUP BY photo_group", list(pgroups))}
        out = []
        for i in ids:
            r = found.get(i)
            if not r or ("listing", i) in hidden or ("seller", r["seller_id"]) in hidden:
                continue
            for k in ("delivery", "photos", "attributes"):
                r[k] = json.loads(r[k]) if r[k] else ([] if k != "attributes" else {})
            start = first.get(i)
            r["drop"] = round(start - r["price"], 2) if start and r["price"] is not None and start > r["price"] else 0
            r["seller_volume"] = volume.get(r["seller_id"], 1)
            r["url"] = ITEM_URL.format(i)
            browse = r["browse_cat"] if r["browse_cat"] != "free" else None
            r["cat"] = cat_map.get(r["category_id"] or "") or browse or "other"
            key, count, earliest = relist.get(i, (i, 1, r["created"]))
            r["relist_key"], r["relist_count"], r["relist_first"] = key, count, earliest
            r["photo_sellers"] = photo_sellers.get(r["photo_group"], 1) if r["photo_group"] else 1
            out.append(r)
        return out

    def _category_map(self) -> dict[str, str]:
        """Facebook leaf category id -> top-level category, learned from the sweeps.

        A category page also returns listings from other categories, so one sighting proves
        little. A leaf maps to the category page that returned it most often (at least 3 times
        and a majority), never to "free". A leaf that is itself a top-level id maps to that.
        """
        at, cached = self._cat_map
        if time.time() - at < CATEGORY_MAP_TTL:
            return cached
        counts: dict[str, dict[str, int]] = {}
        for leaf, cat, n in self.db.execute(
                "SELECT category_id, browse_cat, COUNT(*) FROM listings WHERE browse_cat IS NOT NULL "
                "AND browse_cat != 'free' AND category_id IS NOT NULL GROUP BY category_id, browse_cat"):
            counts.setdefault(leaf, {})[cat] = n
        out = {}
        for leaf, by in counts.items():
            cat, n = max(by.items(), key=lambda kv: kv[1])
            if n >= 3 and n * 2 > sum(by.values()):
                out[leaf] = cat
        out.update(TOP_CATEGORY_IDS)
        self._cat_map = (time.time(), out)
        return out

    def _relists(self, sellers: set[str]) -> dict[str, tuple[str, int, int | None]]:
        """id -> (group key, listings in the group, earliest creation time), per seller.

        Union-find over each seller's listings: a shared photo group or a specific enough
        normalized title joins two listings. The key is the smallest id in the group.
        """
        if not sellers:
            return {}
        sm = ",".join("?" * len(sellers))
        rows = self.db.execute(f"SELECT id, seller_id, photo_group, title, created FROM listings "
                               f"WHERE seller_id IN ({sm})", list(sellers)).fetchall()
        parent = {r["id"]: r["id"] for r in rows}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        first_by: dict[tuple, str] = {}
        for r in rows:
            keys = []
            if r["photo_group"]:
                keys.append(("p", r["seller_id"], r["photo_group"]))
            t = norm_title(r["title"])
            if len(t) >= TITLE_MIN:
                keys.append(("t", r["seller_id"], t))
            for k in keys:
                if k in first_by:
                    a, b = find(first_by[k]), find(r["id"])
                    if a != b:
                        parent[max(a, b)] = min(a, b)
                else:
                    first_by[k] = r["id"]
        groups: dict[str, list] = {}
        for r in rows:
            groups.setdefault(find(r["id"]), []).append(r)
        out = {}
        for key, members in groups.items():
            created = [m["created"] for m in members if m["created"]]
            for m in members:
                out[m["id"]] = (key, len(members), min(created) if created else None)
        return out
