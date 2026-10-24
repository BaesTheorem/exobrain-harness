"""SQLite store for the Marketplace front end: every listing seen, its price history, its pin.

The database is a local index of what Facebook showed us, so the UI filters and sorts without a
round trip and keeps facts Facebook's own feed throws away (price drops, seller volume, hidden
items). It lives in `data/market.db`, gitignored: it holds other people's listings and names.

INVARIANTS
- A distance band only gets tighter. A listing does not move, so a wider band from a later
  search never replaces a narrower one.
- Exact coordinates come only from the item page (`fbm.item`), never from a guess.
- `price_history` gets a row only when the price differs from the last recorded price.
"""

from __future__ import annotations

import json
import math
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
"""


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
        self.lock = threading.Lock()

    # ------------------------------------------------------------ writes

    def upsert_card(self, r: dict, band: tuple[float, float] | None) -> None:
        """One search-card row. Records a price change and tightens the distance band."""
        now = int(time.time())
        with self.lock, self.db:
            old = self.db.execute("SELECT price, band_lo, band_hi FROM listings WHERE id=?", (r["id"],)).fetchone()
            fields = {
                "title": r.get("title"), "price": r.get("price"), "formatted": r.get("formatted"),
                "was": r.get("was"), "city": r.get("city"), "state": r.get("state"),
                "created": r.get("created"), "listed": r.get("listed"), "seller": r.get("seller"),
                "seller_id": r.get("seller_id"), "category_id": r.get("category_id"),
                "delivery": json.dumps(r.get("delivery") or []), "sold": int(bool(r.get("sold"))),
                "pending": int(bool(r.get("pending"))), "photo": r.get("photo"), "last_seen": now,
            }
            if old is None:
                fields.update(id=r["id"], first_seen=now, gone=0)
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
                """UPDATE listings SET lat=?, lon=?, miles=?, enriched_at=?, enrich_error=NULL,
                   description=?, condition=?, attributes=?, photos=?, location_text=?,
                   seller_rating=?, seller_rating_count=?, seller_joined=?,
                   sold=?, pending=?, gone=? WHERE id=?""",
                (latlon[0] if latlon else None, latlon[1] if latlon else None, miles, int(time.time()),
                 d.get("description"), d.get("condition"), json.dumps(d.get("attributes") or {}),
                 json.dumps(d.get("photos") or []), d.get("location_text"), d.get("seller_rating"),
                 d.get("seller_rating_count"), d.get("seller_joined"), int(bool(d.get("sold"))),
                 int(bool(d.get("pending"))), int(not d.get("live", True)), d["id"]))

    def mark_error(self, listing_id: str, msg: str, gone: bool = False) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE listings SET enrich_error=?, enriched_at=?, gone=MAX(gone, ?) WHERE id=?",
                            (msg[:300], int(time.time()), int(gone), listing_id))

    def hide(self, kind: str, key: str, label: str = "") -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO hidden VALUES (?,?,?,?)", (kind, key, label, int(time.time())))

    def unhide(self, kind: str, key: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM hidden WHERE kind=? AND key=?", (kind, key))

    def save_search(self, name: str, params: dict) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO saved VALUES (?,?,?)", (name, json.dumps(params), int(time.time())))

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
            return [{"name": r["name"], "params": json.loads(r["params"])}
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
            out.append(r)
        return out
