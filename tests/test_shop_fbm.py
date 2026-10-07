"""Characterization tests for the Facebook Marketplace lane: parsing only, nothing touches the network.

Fixtures are synthetic. Real pages carry sellers' names, so no capture is checked in.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shopping"))

from shoptools import fbm  # noqa: E402
from shoptools.common import LaneError  # noqa: E402


def _listing(i: str, title: str, amount: str, city: str = "Kansas City", ts: int = 1791401524, **extra) -> dict:
    d = {
        "__typename": "GroupCommerceProductItem", "id": i, "creation_time": ts,
        "listing_price": {"formatted_amount": f"${int(float(amount)):,}", "amount": amount},
        "location": {"reverse_geocode": {"city": city, "state": "MO"}},
        "is_sold": False, "is_pending": False, "marketplace_listing_title": title,
        "marketplace_listing_seller": {"__typename": "User", "name": "Seller Example", "id": "1"},
        "delivery_types": ["IN_PERSON"], "primary_listing_photo": {"image": {"uri": "https://x/p.jpg"}},
        "custom_sub_titles_with_rendering_flags": [{"subtitle": "75K miles"}],
    }
    d.update(extra)
    return d


def _page(payload: dict) -> str:
    """An HTML shell with the tokens and one data blob, the way Facebook ships them."""
    return (
        '<html><script>["LSD",[],{"token":"lsd-tok"}]</script>'
        '<script>"DTSGInitialData",[],{"token":"dtsg-tok"}</script>'
        '<script>jazoest=21943</script>'
        '<script type="application/json" data-sjs>not json</script>'
        f'<script type="application/json" data-sjs>{json.dumps(payload)}</script></html>'
    )


def test_tokens_and_missing_tokens():
    assert fbm.tokens(_page({})) == {"fb_dtsg": "dtsg-tok", "lsd": "lsd-tok", "jazoest": "21943"}
    with pytest.raises(LaneError):
        fbm.tokens("<html>logged out shell</html>")


def test_blobs_skip_invalid_json():
    assert fbm.blobs(_page({"a": 1})) == [{"a": 1}]


def test_listing_row_shape():
    r = fbm.listing_row(_listing("111", "1983 Honda Shadow", "1650.00", strikethrough_price={"formatted_amount": "$1,800"}))
    assert r["retailer"] == "FB Marketplace"
    assert r["url"] == "https://www.facebook.com/marketplace/item/111/"
    assert (r["price"], r["formatted"], r["was"]) == (1650.0, "$1,650", "$1,800")
    assert (r["city"], r["state"], r["listed"]) == ("Kansas City", "MO", "2026-10-07")
    assert r["subtitles"] == ["75K miles"] and r["delivery"] == ["IN_PERSON"]


def test_embedded_search_skips_units_without_a_listing():
    feed = {"edges": [
        {"node": {"__typename": "MarketplaceFeedAdObject"}},
        {"node": {"listing": _listing("1", "Bike", "60.00")}},
        {"node": {"listing": _listing("2", "Trek", "120.00")}},
    ], "page_info": {"has_next_page": True, "end_cursor": "c2"}}
    rows, info = fbm.embedded_search(_page({"require": [[{"__bbox": {"result": {"data": {"marketplace_search": {"feed_units": feed}}}}}]]}))
    assert [r["id"] for r in rows] == ["1", "2"]
    assert info["end_cursor"] == "c2"


def test_item_target_merges_split_nodes():
    stub = {"id": "9", "listing_photos": [{"image": {"uri": "https://x/1.jpg"}}, {"image": {"uri": "https://x/2.jpg"}}]}
    full = _listing("9", "NordicTrack Elliptical", "80.00",
                    redacted_description={"text": "Grey with orange accents.\nFront drive."},
                    attribute_data=[{"attribute_name": "Condition", "value": "used_good", "label": "Used - Good"}],
                    location_text={"text": "Kansas City, MO"}, location={"latitude": 39.1, "longitude": -94.57},
                    is_shipping_offered=False)
    html = _page({"require": [[{"marketplace_product_details_page": {"target": stub}},
                               {"marketplace_product_details_page": {"target": full}}]]})
    r = fbm.item_row(fbm.item_target(html))
    assert r["title"] == "NordicTrack Elliptical" and r["price"] == 80.0
    assert r["condition"] == "Used - Good" and r["attributes"] == {}
    assert r["description"].startswith("Grey") and len(r["photos"]) == 2
    assert r["latlon"] == (39.1, -94.57) and r["ships"] is False


def test_params_prices_in_cents_and_open_upper_bound():
    p = fbm._params("bike", 39.0, -94.5, 40, 50, None, 7, ["used_good"])
    b = p["browse_request_params"]
    assert (b["filter_price_lower_bound"], b["filter_price_upper_bound"]) == (5000, 214748364700)
    assert (b["filter_radius_km"], b["commerce_search_and_rp_ctime_days"]) == (40, 7)
    assert b["commerce_search_and_rp_condition"] == ["used_good"]
    assert p["bqf"]["query"] == "bike"


def test_parse_url_and_doc_id_override(monkeypatch, tmp_path):
    assert fbm.parse_url("https://www.facebook.com/marketplace/item/123456789012345/?ref=x") == "123456789012345"
    assert fbm.parse_url("https://www.target.com/p/-/A-1") is None
    monkeypatch.setenv("FBM_DOC_ID", "42")
    assert fbm.doc_id() == "42"
    monkeypatch.delenv("FBM_DOC_ID")
    f = tmp_path / "id.txt"
    f.write_text("77\n")
    monkeypatch.setattr(fbm, "DOC_ID_FILE", f)
    assert fbm.doc_id() == "77"


def test_load_cookies_netscape_and_httponly(tmp_path):
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n"
                 ".facebook.com\tTRUE\t/\tTRUE\t0\tc_user\t100\n"
                 "#HttpOnly_.facebook.com\tTRUE\t/\tTRUE\t0\txs\tsecret\n"
                 ".other.com\tTRUE\t/\tTRUE\t0\tc_user\tnope\n")
    assert fbm.load_cookies(f) == {"c_user": "100", "xs": "secret"}
    (tmp_path / "empty.txt").write_text("# nothing\n")
    with pytest.raises(LaneError):
        fbm.load_cookies(tmp_path / "empty.txt")
    with pytest.raises(LaneError):
        fbm.load_cookies(tmp_path / "missing.txt")
