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
