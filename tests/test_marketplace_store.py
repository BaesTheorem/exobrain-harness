"""Tests for the Marketplace front end's store and ring logic. Synthetic rows, no network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shopping"))

from marketplace.crawl import rings_for  # noqa: E402
from marketplace.store import Store, haversine_mi  # noqa: E402


def _row(i: str, price: float, seller: str = "s1") -> dict:
    return {"id": i, "title": f"item {i}", "price": price, "formatted": f"${price:g}", "seller_id": seller,
            "delivery": ["IN_PERSON"], "created": 1791401524}


def test_band_only_tightens(tmp_path):
    st = Store(tmp_path / "m.db")
    st.upsert_card(_row("1", 50), (0.0, 9.94))
    st.upsert_card(_row("1", 50), (0.0, 1.24))
    st.upsert_card(_row("1", 50), (4.97, 9.94))   # a wider band later must not replace the narrow one
    r = st.rows(["1"])[0]
    assert (r["band_lo"], r["band_hi"]) == (0.0, 1.24)


def test_price_drop_from_history(tmp_path):
    st = Store(tmp_path / "m.db")
    st.upsert_card(_row("1", 80), None)
    st.upsert_card(_row("1", 80), None)            # same price: no new history row
    st.upsert_card(_row("1", 60), None)
    r = st.rows(["1"])[0]
    assert r["drop"] == 20
    assert st.db.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 2


def test_hidden_listing_and_seller_drop_out(tmp_path):
    st = Store(tmp_path / "m.db")
    for i, s in (("1", "a"), ("2", "b"), ("3", "b")):
        st.upsert_card(_row(i, 10, s), None)
    st.hide("listing", "1")
    st.hide("seller", "b")
    assert st.rows(["1", "2", "3"]) == []
    st.unhide("seller", "b")
    assert [r["id"] for r in st.rows(["1", "2", "3"])] == ["2", "3"]


def test_seller_volume_counts_listings(tmp_path):
    st = Store(tmp_path / "m.db")
    for i in range(5):
        st.upsert_card(_row(str(i), 10, "dealer"), None)
    assert st.rows(["0"])[0]["seller_volume"] == 5


def test_item_page_sets_exact_miles(tmp_path):
    st = Store(tmp_path / "m.db")
    st.upsert_card(_row("1", 10), None)
    assert st.needs_item("1")
    st.save_item({"id": "1", "latlon": (39.10, -94.58), "live": True}, (39.05, -94.58))
    r = st.rows(["1"])[0]
    assert not st.needs_item("1")
    assert abs(r["miles"] - haversine_mi(39.05, -94.58, 39.10, -94.58)) < 1e-9
    assert 3.4 < r["miles"] < 3.5


def test_rings_stop_at_the_maximum():
    assert rings_for(10) == [1, 3, 5, 10]
    assert rings_for(7) == [1, 3, 5, 7]
    assert rings_for(1) == [1]


# ---------------------------------------------------------------- v2: shipping, photos, relists, alerts

from marketplace import filters, watch  # noqa: E402


def test_shippable_listing_gets_no_band(tmp_path):
    st = Store(tmp_path / "m.db")
    st.upsert_card({**_row("1", 10), "delivery": ["IN_PERSON", "SHIPPING_ONSITE"]}, (0.0, 1.24))
    r = st.rows(["1"])[0]
    assert r["band_hi"] is None


def test_photo_groups_merge(tmp_path):
    st = Store(tmp_path / "m.db")
    for i in "123":
        st.upsert_card({**_row(i, 10, seller=f"s{i}"), "photo": "https://x/p.jpg"}, None)
    g1 = st.set_phash("1", "ffff000000000000")
    g2 = st.set_phash("2", "0000ffff00000000")          # far from 1
    assert g1 != g2
    g3 = st.set_phash("3", "ffff00000000000f")          # 4 bits from 1: joins its group
    assert g3 == g1
    rows = {r["id"]: r for r in st.rows(["1", "2", "3"])}
    assert rows["1"]["photo_sellers"] == 2 and rows["2"]["photo_sellers"] == 1


def test_relists_by_photo_or_specific_title(tmp_path):
    st = Store(tmp_path / "m.db")
    st.upsert_card({**_row("1", 50), "title": "Oak bookcase five shelves"}, None)
    st.upsert_card({**_row("2", 45), "title": "Oak Bookcase - five shelves!"}, None)
    st.upsert_card({**_row("3", 20), "title": "Shelf"}, None)
    st.upsert_card({**_row("4", 20), "title": "Shelf"}, None)            # too short to mean the same item
    st.upsert_card({**_row("5", 20, seller="other"), "title": "Oak bookcase five shelves"}, None)
    rows = {r["id"]: r for r in st.rows(["1", "2", "3", "4", "5"])}
    assert rows["1"]["relist_key"] == rows["2"]["relist_key"] == "1"
    assert rows["1"]["relist_count"] == 2
    assert rows["3"]["relist_count"] == 1 and rows["4"]["relist_count"] == 1
    assert rows["5"]["relist_count"] == 1                                # never across sellers


def test_lock_held_by_dead_process_is_free(tmp_path):
    import os
    import time
    st = Store(tmp_path / "m.db")
    st.set_meta("sweep", f"999999-dead@{int(time.time())}")       # pid 999999 is not running
    assert st.try_lock("sweep", f"{os.getpid()}-a", ttl=1800)
    assert not st.try_lock("sweep", f"{os.getpid()}-b", ttl=1800)  # a live holder keeps it


def test_filters_need_a_known_distance():
    p = {"max_mi": 10}
    assert not filters.match({"id": "1", "price": 5}, p)                         # no pin, no band
    assert filters.match({"id": "1", "price": 5, "band_lo": 0, "band_hi": 3.1}, p)
    assert not filters.match({"id": "1", "price": 5, "band_lo": 10.1, "band_hi": 25}, p)
    assert not filters.match({"id": "1", "price": 5, "miles": 12.0}, p)
    assert not filters.match({"id": "1", "miles": 1.0, "delivery": ["SHIPPING_ONSITE"]}, p)
    assert filters.match({"id": "1", "miles": 1.0, "delivery": ["SHIPPING_ONSITE"]}, {**p, "local_only": False})


def test_text_match():
    assert filters.text_match("White Book Shelf", "bookshelves")
    assert filters.text_match("Oak desk, 60in", "desk")
    assert not filters.text_match("Minerals book", "bookshelf")


class _FakeCrawler:
    def locate_now(self, listing_id):
        pass

    def drain_hashes(self):
        return 0


def test_watcher_seeds_then_alerts_new_drops_and_cheaper_relists(tmp_path, monkeypatch):
    monkeypatch.setattr(watch.time, "sleep", lambda s: None)
    monkeypatch.setattr(watch, "LOG", tmp_path / "watch.log")
    st = Store(tmp_path / "m.db")
    band = (0.0, 3.11)
    st.upsert_card({**_row("1", 50), "title": "Walnut desk with drawers"}, band)
    saved = {"name": "desks", "params": {"q": "", "max_mi": 10}}
    rows = lambda: {r["id"]: r for r in st.index(0)}  # noqa: E731
    assert watch.search_alerts(st, _FakeCrawler(), saved, rows()) == []          # first run seeds
    st.upsert_card({**_row("2", 30), "title": "Pine table"}, band)                # new
    st.upsert_card({**_row("1", 40), "title": "Walnut desk with drawers"}, band)  # drop 50 -> 40
    kinds = sorted(k for k, _, _ in watch.search_alerts(st, _FakeCrawler(), saved, rows()))
    assert kinds == ["new", "price drop"]
    st.upsert_card({**_row("3", 45), "title": "Walnut desk with drawers"}, band)  # relist, not cheaper
    assert watch.search_alerts(st, _FakeCrawler(), saved, rows()) == []
    st.upsert_card({**_row("4", 25), "title": "Walnut desk with drawers"}, band)  # relist, cheaper
    out = watch.search_alerts(st, _FakeCrawler(), saved, rows())
    assert [(k, r["id"]) for k, r, _ in out] == [("relisted lower", "4")]
    assert watch.digest({"desks": out})[1].endswith("https://www.facebook.com/marketplace/item/4/")
