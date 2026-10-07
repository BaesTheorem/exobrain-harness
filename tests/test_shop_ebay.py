"""Characterization tests for the eBay lane: row shapes, filters, sold stats. No network.

Fixtures follow eBay's Browse API item_summary shape and the Apify actor's documented
output; values are synthetic.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shopping"))

from shoptools import ebay, lanes  # noqa: E402
from shoptools.common import LaneError  # noqa: E402


def test_summary_row_legacy_id_shipping_and_auction():
    r = ebay.summary_row({
        "itemId": "v1|306671421088|0", "title": "Trek 7.2 FX", "price": {"value": "180.00", "currency": "USD"},
        "condition": "Pre-Owned", "buyingOptions": ["FIXED_PRICE", "BEST_OFFER"],
        "shippingOptions": [{"shippingCost": {"value": "45.00"}}, {"shippingCost": {"value": "30.00"}}],
        "seller": {"username": "example_seller", "feedbackPercentage": "99.5", "feedbackScore": 120},
        "itemLocation": {"city": "Lenexa", "stateOrProvince": "KS", "postalCode": "662**"},
    })
    assert r["id"] == "306671421088" and r["url"] == "https://www.ebay.com/itm/306671421088"
    assert (r["price"], r["shipping"], r["total"]) == (180.0, 30.0, 210.0)
    assert r["location"] == "Lenexa, KS, 662**"

    a = ebay.summary_row({"itemId": "v1|1|0", "legacyItemId": "999", "title": "x", "buyingOptions": ["AUCTION"],
                          "currentBidPrice": {"value": "12.50"}, "bidCount": 3, "itemEndDate": "2026-10-09T18:00:00.000Z"})
    assert (a["id"], a["price"], a["shipping"], a["total"]) == ("999", 12.5, None, None)
    assert a["ends"] == "2026-10-09 18:00"


def test_filters(monkeypatch):
    monkeypatch.setattr(ebay, "home_zip", lambda: "00000")
    f = ebay._filters(None, 200, ["used", "refurbished"], "AUCTION", 25)
    assert "price:[..200]" in f and "priceCurrency:USD" in f
    assert "conditionIds:{3000|4000|5000|6000|2000|2010|2020|2030|2500}" in f
    assert "buyingOptions:{AUCTION}" in f
    assert "pickupPostalCode:00000" in f and "pickupRadius:25" in f
    assert ebay._filters(None, None, None, None, None) == "deliveryCountry:US"


def test_search_rejects_unknown_condition():
    with pytest.raises(LaneError):
        ebay.search("bike", condition=["mint"])


def test_sold_row_and_comps():
    rows = [ebay.sold_row(d) for d in [
        {"itemId": "1", "soldPrice": "100", "shippingType": "free", "totalPrice": "100", "endedAt": "2026-09-01T05:00:00.000Z"},
        {"itemId": "2", "soldPrice": "200", "shippingPrice": "20", "totalPrice": "220", "endedAt": "2026-09-20T05:00:00.000Z"},
        {"itemId": "3", "soldPrice": "1,300", "isBestOfferAccepted": True, "endedAt": "2026-09-10T05:00:00.000Z"},
    ]]
    assert rows[0]["shipping"] == 0.0 and rows[2]["price"] == 1300.0 and rows[2]["best_offer"]
    c = ebay.comps(rows)
    assert c["price"]["median"] == 200.0 and c["price"]["n"] == 3
    assert c["price_no_best_offer"]["median"] == 150.0
    assert c["total"]["n"] == 2 and c["best_offer_rows"] == 1
    assert (c["from"], c["to"]) == ("2026-09-01", "2026-09-20")
    assert ebay.comps([])["price"] == {}


def test_sold_without_token_names_the_manual_url(monkeypatch):
    monkeypatch.setattr(ebay, "env", lambda name: "")
    with pytest.raises(LaneError, match="LH_Sold=1"):
        ebay.sold("trek 7.2 fx")


def test_parse_target_ebay_urls():
    assert lanes.parse_target("https://www.ebay.com/itm/306671421088?hash=x") == ("ebay", "306671421088")
    assert lanes.parse_target("https://www.ebay.com/itm/Trek-7-2-FX/306671421088") == ("ebay", "306671421088")
    assert lanes.parse_target("ebay:306671421088") == ("ebay", "306671421088")
