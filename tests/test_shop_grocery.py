"""Characterization tests for the grocery lanes: parsers and the circular OCR grouping. No network.

Fixtures follow the live shapes measured 2026-10-07 (Flipp flyer items, Price Chopper ad groups,
Whole Foods search, Costco typeahead and product page, EZConnect offers, Strapi locations,
Vision text boxes); values are trimmed or synthetic.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shopping"))

from shoptools import circular_ocr, grocery  # noqa: E402
from shoptools.common import LaneError  # noqa: E402


# ------------------------------------------------------------------ price tokens


@pytest.mark.parametrize("text,tall,price,formatted", [
    ("$149", False, 1.49, "$1.49"),        # superscript cents, Vision drops the size change
    ("$1099", False, 10.99, "$10.99"),
    ("2 99", False, 2.99, "$2.99"),
    ("099", False, 0.99, "$0.99"),
    ("99%", False, 0.99, "99¢"),           # Vision reads the cents sign as a percent sign
    ("99¢", False, 0.99, "99¢"),
    ("5/$5", False, 1.0, "5/$5"),
    ("2/$3", False, 1.5, "2/$3"),
    ("3/$10.00", False, 10 / 3, "3/$10"),
    ("$3.49", False, 3.49, "$3.49"),
    ("12.49", False, 12.49, "$12.49"),
    ("299", True, 2.99, "$2.99"),          # bare digits count only in a tall (price-sized) box
    ("299", False, None, None),
    ("2026", True, None, None),
    ("Chobani", False, None, None),
    ("selected varieties", False, None, None),
    ("10 lb", False, None, None),
])
def test_parse_price(text, tall, price, formatted):
    p, f = circular_ocr.parse_price(text, tall=tall)
    if price is None:
        assert p is None and f is None
    else:
        assert p == pytest.approx(price, abs=1e-3) and f == formatted


def _box(text, x, y, w, h, conf=1.0):
    return {"text": text, "x": x, "y": y, "w": w, "h": h, "conf": conf}


def test_group_boxes_stacks_name_lines_under_the_price():
    boxes = [
        _box("STORE HEADER", 0.2, 0.91, 0.63, 0.028),
        # deal 1: price, three name lines, a size line
        _box("$149", 0.219, 0.658, 0.115, 0.023),
        _box("Fresh Whole", 0.222, 0.648, 0.111, 0.009),
        _box("Bone-In Pork", 0.215, 0.638, 0.118, 0.009),
        _box("Shoulder Roast", 0.198, 0.629, 0.135, 0.009),
        _box("lb.", 0.336, 0.660, 0.02, 0.009),
        # deal 2, to the right on the same row, with a size line and a low-confidence smudge
        _box("5/$5", 0.375, 0.317, 0.097, 0.025),
        _box("Chobani", 0.406, 0.307, 0.083, 0.009),
        _box("Yogurt", 0.42, 0.295, 0.069, 0.01),
        _box("5.3 0z.", 0.448, 0.291, 0.035, 0.003),
        _box("selected varieties", 0.396, 0.285, 0.09, 0.003),
        _box("~ wy", 0.41, 0.27, 0.05, 0.005, conf=0.1),
        # a page footer far below everything: must not attach to either deal
        _box("Prices good 10/07 through 10/13", 0.3, 0.02, 0.4, 0.008),
    ]
    rows = circular_ocr.group_boxes(boxes, page=1)
    assert [r["formatted"] for r in rows] == ["$1.49", "5/$5"]
    pork, yogurt = rows
    assert pork["title"] == "Fresh Whole Bone-In Pork Shoulder Roast" and pork["unit"] == "lb" and pork["page"] == 1
    assert yogurt["title"] == "Chobani Yogurt selected varieties" and yogurt["size"] == "5.3 0z."
    assert yogurt["price"] == 1.0


def test_group_boxes_each_line_joins_one_deal_only():
    boxes = [
        _box("$2.99", 0.2, 0.60, 0.08, 0.02),
        _box("Chicken Breasts", 0.19, 0.59, 0.10, 0.009),
        _box("$3.99", 0.2, 0.56, 0.08, 0.02),       # a second price right under the first deal's line
        _box("Pork Chops", 0.2, 0.55, 0.09, 0.009),
    ]
    rows = circular_ocr.group_boxes(boxes, page=2)
    assert [(r["formatted"], r["title"]) for r in rows] == [("$2.99", "Chicken Breasts"), ("$3.99", "Pork Chops")]


def test_group_boxes_empty_and_no_prices():
    assert circular_ocr.group_boxes([], 1) == []
    assert circular_ocr.group_boxes([_box("Autumn Adventures", 0.1, 0.8, 0.3, 0.03)], 1) == []


# ------------------------------------------------------------------ Flipp, Price Chopper, matching


def test_flipp_flyer_items_drop_costco_code_slots(monkeypatch):
    class R:
        def json(self):
            return {"items": [
                {"id": 1, "name": "Pork Butt", "price": 1.49, "valid_from": "2026-10-07T00:00:00-04:00", "valid_to": "2026-10-13T23:59:59-04:00"},
                {"id": 2, "name": "CSTUG100526290210", "price": ""},
                {"id": 3, "name": "Brew Pub Pizza", "price": 3.99, "discount": 20, "brand": "Brew Pub"},
                {"id": 4, "name": "", "price": 1.0},
            ]}

    class S:
        def get(self, *a, **k):
            return R()

    monkeypatch.setattr(grocery, "session", lambda: S())
    rows = grocery.flipp_flyer_items({"id": 8172640, "merchant": "Costco ", "name": "CP Grocery", "valid_from": "2026-10-05", "valid_to": "2026-10-11"})
    assert [r["title"] for r in rows] == ["Pork Butt", "Brew Pub Pizza"]
    assert rows[0]["retailer"] == "Costco" and rows[0]["formatted"] == "$1.49" and rows[0]["valid_to"] == "2026-10-13"
    assert rows[1]["valid_from"] == "2026-10-05" and rows[1]["discount"] == 20 and rows[1]["kind"] == "ad"


def test_pricechopper_highlights_prices(monkeypatch):
    class R:
        def json(self):
            return {"data": {"AdGroups": [
                {"AdGroupId": 1, "Title": "Pork Butt", "Description": "Fresh", "Size": "", "AdPrice": "$1.49", "AdPriceOnly": "1",
                 "AdPriceCents": "49", "AdPricePrefix": "$", "AdPriceUOM": "lb.", "Department": "Meat"},
                {"AdGroupId": 2, "Title": "Coke Products", "Description": "Selected Varieties", "Size": "16.9 oz 6 pk",
                 "AdPrice": "3/$10.00", "AdPriceOnly": "10", "AdPriceCents": "00", "AdPricePrefix": "3/$", "AdPriceUOM": ""},
            ]}}

    class S:
        def get(self, *a, **k):
            return R()

    monkeypatch.setattr(grocery, "session", lambda: S())
    rows = grocery.pricechopper_highlights("75")
    assert (rows[0]["price"], rows[0]["formatted"]) == (1.49, "$1.49/lb.")
    assert rows[1]["price"] == pytest.approx(10 / 3, abs=1e-3) and rows[1]["formatted"] == "3/$10.00" and rows[1]["size"] == "16.9 oz 6 pk"


def test_matches_every_word_across_title_size_description():
    row = {"title": "Idaho Russet Potatoes", "size": "10 lb", "description": "Selected Varieties"}
    assert grocery.matches(row, "russet potatoes")
    assert grocery.matches(row, "10 lb POTATOES")
    assert not grocery.matches(row, "sweet potatoes")
    assert grocery.matches(row, None)


def test_canon_aliases():
    assert grocery.canon("PC") == "pricechopper" and grocery.canon("Cosentino's") == "cosentinos" and grocery.canon("aldi") == "aldi"


# ------------------------------------------------------------------ Whole Foods, Costco


def test_wholefoods_rows_prefer_sale_price(monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return {"results": [
                {"regularPrice": 3.19, "name": "Milk Whole, 32 FZ", "slug": "shatto-milk-whole-32-fz", "brand": "SHATTO MILK", "isLocal": True},
                {"regularPrice": 6.39, "salePrice": 4.99, "name": "Oat Milk", "slug": "malk-oat", "brand": "Malk"},
            ]}

    class S:
        def get(self, *a, **k):
            return R()

    monkeypatch.setattr(grocery, "session", lambda: S())
    rows = grocery.wholefoods_search("milk", 5)
    assert rows[0]["title"] == "SHATTO MILK Milk Whole, 32 FZ" and rows[0]["price"] == 3.19 and rows[0]["local"]
    assert rows[1]["price"] == 4.99 and rows[1]["reg_price"] == 6.39 and rows[1]["kind"] == "shelf"
    assert rows[0]["url"].endswith("/product/shatto-milk-whole-32-fz")


COSTCO_PDP = (
    'x\\"@type\\":\\"Product\\",\\"name\\":\\"Kirkland Signature Olive Oil, 3 L\\",\\"image\\":\\"https://i\\",\\"sku\\":\\"1789247\\",'
    '\\"url\\":\\"https://www.costco.com/p/-/kirkland-signature-olive-oil-3-l/4000262621\\",\\"brand\\":{\\"@type\\":\\"Brand\\"},'
    '\\"offers\\":{\\"@type\\":\\"Offer\\",\\"url\\":\\"https://www.costco.com/p/-/kirkland-signature-olive-oil-3-l/4000262621\\",'
    '\\"availability\\":\\"https://schema.org/OutOfStock\\",\\"priceCurrency\\":\\"USD\\",\\"price\\":22.49,\\"shippingDetails\\":{}}'
)


def test_parse_costco_offer_from_escaped_rsc_payload():
    o = grocery.parse_costco_offer(COSTCO_PDP)
    assert o == {"name": "Kirkland Signature Olive Oil, 3 L", "price": 22.49, "availability": "OutOfStock",
                 "url": "https://www.costco.com/p/-/kirkland-signature-olive-oil-3-l/4000262621"}
    assert grocery.parse_costco_offer("<html>no product</html>") == {}


def test_costco_row_labels_online_price():
    r = grocery.costco_row({"item_number": "1789247", "term": "Kirkland Signature Olive Oil, 3 L", "Brand_attr": "Kirkland Signature"},
                           {"price": 22.49, "availability": "OutOfStock"})
    assert r["retailer"] == "Costco.com" and r["kind"] == "online" and r["formatted"] == "$22.49"
    assert "warehouse price" in r["note"] and "availability" not in r   # the page's availability is noise
    bare = grocery.costco_row({"item_number": "1", "term": "x"}, {})
    assert bare["price"] is None and bare["formatted"] is None and bare["title"] == "x"


# ------------------------------------------------------------------ Cosentino's


COS_INDEX = '<script type="module" crossorigin src="/assets/index-YGHFdeYb.js"></script>'
COS_BUNDLE = (
    'const Wae="https://bagr.iprosystems.com/api",Vae="' + "ab" * 128 + '";'
    'const xA="https://u9051n7iej.execute-api.us-east-1.amazonaws.com/prod/ezconnect/v1",Iue="EXAMPLEKEY0000000000000000000000000000";'
    'fetch(o,{method:t,headers:{"Content-Type":"application/json","x-api-key":Iue},body:s})'
)


def test_scrape_cosentinos_keys_from_bundle():
    k = grocery.scrape_cosentinos_keys(COS_INDEX, COS_BUNDLE)
    assert k["ezconnect_key"] == "EXAMPLEKEY0000000000000000000000000000"
    assert k["strapi_token"] == "ab" * 128
    assert k["ezconnect_base"].endswith("/prod/ezconnect/v1") and k["bundle"] == "/assets/index-YGHFdeYb.js"
    with pytest.raises(LaneError):
        grocery.scrape_cosentinos_keys(COS_INDEX, "nothing here")


def test_coupon_row():
    r = grocery.coupon_row({"id": "24243", "title": "Save $3.00", "subtitle": "MUSCLE MILK®", "description": "on any ONE (1) 11oz 4pk",
                            "value": 3.0, "to_date": "2026-10-09T23:59:59", "category": "Foods"}, "200284")
    assert r["formatted"] == "Save $3.00" and r["title"] == "MUSCLE MILK®: on any ONE (1) 11oz 4pk"
    assert r["valid_to"] == "2026-10-09" and r["kind"] == "coupon" and r["store"]["id"] == "200284"


# ------------------------------------------------------------------ directory


def test_store_directory_data_file_is_sane():
    data = json.loads(grocery.DATA_FILE.read_text())
    chains = data["chains"]
    for s in data["stores"]:
        assert s["chain"] in chains, s
        assert "address" in s and "status" in s
    assert chains["cosentinos"]["default_coupon_location"] == "200284"
    closed = next(s for s in data["stores"] if s["chain"] == "costco")
    assert closed["status"] == "closed" and "2026-10-01" in closed["note"]


def test_miles_and_nearest():
    assert grocery.miles(39.0997, -94.5786, 39.0997, -94.5786) == 0.0
    d = grocery.miles(39.0997, -94.5786, 39.0355, -94.5775)   # downtown to 51st St
    assert 4.3 < d < 4.6
    stores = [{"id": "a", "lat": 39.0, "lon": -94.5}, {"id": "b", "lat": 39.1, "lon": -94.58}, {"id": "c", "lat": None, "lon": None}]
    assert grocery.nearest(stores, 39.0997, -94.5786)["id"] == "b"


def test_fmt_row_shapes():
    line = grocery.fmt_row({"retailer": "Sun Fresh", "kind": "ad", "formatted": "$1.49", "title": "Pork Shoulder", "unit": "lb",
                            "size": "2 pc", "valid_from": "2026-10-07", "valid_to": "2026-10-13", "page": 1})
    assert line.startswith("Sun Fresh") and "$1.49/lb" in line and "p1" in line and "thru 2026-10-13" in line
    assert grocery.fmt_row({"retailer": "X", "title": "y"}).split()[-2:] == ["-", "y"]


# ------------------------------------------------------------------ Instacart guest lane (instacart_guest.py)

from shoptools import instacart_guest  # noqa: E402

SF = {"host": "sameday.costco.com", "slug": "costco", "retailer": "Costco Same-Day", "chain": "costco"}
PRICED_AT = {"zip": "64105", "id": "16700663", "retailer_location": "11020", "name": "Costco Same-Day via Instacart, ZIP 64105"}


def _header(text):
    return {"content": {"__typename": "SearchContentManagementSearchItemGridHeader",
                        "viewSection": {"titleFormattedAttributesString": {"sections": [{"text": text}]}}}}


def _grid(*ids):
    return {"content": {"__typename": "SearchContentManagementSearchItemGrid", "itemIds": list(ids), "items": []}}


def _carousel(*ids):
    return {"content": {"__typename": "SearchContentManagementSearchItemCarousel", "itemIds": list(ids)}}


def _placements(*pl):
    return {"data": {"searchResultsPlacements": {"placements": [
        {"content": {"__typename": "ContentManagementCardListsSlot", "title": "Search Campaigns Slot"}}, *pl]}}}


def test_parse_placements_keeps_only_the_results_grids_in_order():
    d = _placements(
        _header('Results for "milk"'), _grid("items_11020-1", "items_11020-2"),
        {"content": {"__typename": "AdsSearchDisplayCreativePlacement", "placement": {"itemIds": ["items_11020-ad"]}}},
        _grid("items_11020-3", "items_11020-1"),
        _carousel("items_11020-carousel"),
        _header("Related items"), _grid("items_11020-9"),
    )
    assert instacart_guest.parse_placements(d) == ["items_11020-1", "items_11020-2", "items_11020-3"]


def test_parse_placements_junk_query_is_empty():
    # A junk query answers 'No results for "..."' and then a "Related items" grid full of ids.
    d = _placements(_header('No results for "zqxjkv"'), _header("Related items"), _grid("items_11020-5", "items_11020-6"))
    assert instacart_guest.parse_placements(d) == []
    assert instacart_guest.parse_placements({"data": {}}) == []


# Two items from a real `Items` response (2026-10-07), trimmed to the fields the parser reads.
ITEMS = {"data": {"items": [
    {"id": "items_11020-127637", "name": "Toblerone Swiss Milk Chocolate Bar, 3.52 oz, 6-Count", "size": "each",
     "productId": "127637", "legacyId": "127192808", "brandName": "toblerone",
     "evergreenUrl": "127637-toblerone-milk-chocolate-swiss-with-honey-almond-nougat-6-ea",
     "availability": {"available": True, "stockLevel": "inStock"},
     "price": {"id": "items_11020-127637", "viewSection": {
         "badge": {"genericSaleLabelString": "Sale", "badgeVariant": "retailerPromotion", "offerLabelString": "$3.60 off; limit 10"},
         "itemCard": {"fullPriceString": "reg. $12.56", "priceString": "$8.96", "pricePerUnitString": None,
                      "pricingUnitString": "6 ct", "plainFullPriceString": "$12.56", "priceScreenReaderString": "Current price: $8.96"},
         "itemDetails": {"fullPriceString": "$12.56", "pricePerUnitString": "$0.25 each", "priceString": "$8.96", "pricingUnitString": "6 ct"},
         "fullPriceString": "$12.56", "priceString": "$8.96", "priceValueString": "8.96"}}},
    {"id": "items_11020-16902650", "name": "Kirkland Signature Whole Milk, 1 gal", "size": "each", "productId": "16902650",
     "brandName": "kirkland signature", "evergreenUrl": "16902650-kirkland-signature-homogenized-milk-1-gal-4-qt",
     "availability": {"available": True, "stockLevel": "highlyInStock"},
     "price": {"id": "items_11020-16902650", "viewSection": {
         "badge": None,
         "itemCard": {"fullPriceString": None, "priceString": "$3.17", "pricePerUnitString": None, "pricingUnitString": None},
         "itemDetails": {"fullPriceString": None, "pricePerUnitString": None, "priceString": "$3.17"},
         "fullPriceString": None, "priceString": "$3.17", "priceValueString": "3.17"}}},
    {"id": "items_11020-999", "name": "Unpriced Thing", "size": "2 lb", "productId": "999", "evergreenUrl": "999-unpriced",
     "availability": {"available": False, "stockLevel": "outOfStock"}, "price": None},
]}}


def test_parse_items_rows():
    rows = instacart_guest.parse_items(ITEMS, SF, PRICED_AT)
    assert [r["id"] for r in rows] == ["127637", "16902650", "999"]
    sale, milk, bare = rows
    assert sale["retailer"] == "Costco Same-Day" and sale["kind"] == "online" and sale["via"] == "Instacart"
    assert sale["price"] == 8.96 and sale["formatted"] == "$8.96" and sale["reg_price"] == 12.56
    assert sale["size"] == "6 ct" and sale["unit_price"] == "$0.25 each" and sale["offer"] == "$3.60 off; limit 10"
    assert sale["url"] == "https://sameday.costco.com/store/costco/products/127637-toblerone-milk-chocolate-swiss-with-honey-almond-nougat-6-ea"
    assert sale["availability"] == "InStock" and sale["store"] is PRICED_AT and "above the shelf price" in sale["note"]
    assert milk["price"] == 3.17 and milk["reg_price"] is None and milk["size"] is None and milk["availability"] == "InStock"
    assert bare["price"] is None and bare["formatted"] is None and bare["size"] == "2 lb" and bare["availability"] == "outOfStock"
    assert instacart_guest.parse_items({"data": {"items": []}}, SF, PRICED_AT) == []


def test_fmt_row_labels_instacart_rows():
    line = grocery.fmt_row(instacart_guest.parse_items(ITEMS, SF, PRICED_AT)[0])
    assert line.startswith("Costco Same-Day") and "online" in line and "$8.96" in line and "(reg $12.56)" in line
    assert "($0.25 each)" in line and "$3.60 off" in line and line.endswith("[Instacart, above shelf]")


def test_edit_url_rewrites_only_the_variables():
    url = ("https://sameday.costco.com/graphql?operationName=Items&variables=%7B%22ids%22%3A%5B%22items_11020-1%22%5D%2C"
           "%22shopId%22%3A%2294153%22%2C%22zoneId%22%3A%22305%22%2C%22postalCode%22%3A%2264151%22%7D"
           "&extensions=%7B%22persistedQuery%22%3A%7B%22version%22%3A1%2C%22sha256Hash%22%3A%22abc%22%7D%7D")
    new = instacart_guest._edit_url(url, postalCode="64105", shopId="16700663", ids=["items_11020-2", "items_11020-3"])
    v = instacart_guest._vars(new)
    assert v == {"ids": ["items_11020-2", "items_11020-3"], "shopId": "16700663", "zoneId": "305", "postalCode": "64105"}
    assert "sha256Hash" in new and "operationName=Items" in new and new.startswith("https://sameday.costco.com/graphql?")


def test_storefronts_come_from_the_data_file():
    sf = instacart_guest.storefronts()
    assert {"costco-sameday", "pricechopper-online", "cosentinos-online", "henhouse-online", "aldi-online"} <= set(sf)
    assert sf["costco-sameday"] == {"host": "sameday.costco.com", "slug": "costco", "retailer": "Costco Same-Day", "chain": "costco"}
    assert sf["cosentinos-online"]["host"].startswith("www.")   # the bare mymarketdelivers.com has no TLS
    assert set(grocery.INSTACART_LANES) == set(sf)
    assert grocery.canon("costco-online") == "costco-sameday" and grocery.canon("pc-online") == "pricechopper-online"


def test_stale_cache_is_ignored(tmp_path, monkeypatch):
    f = tmp_path / "instacart-guest.json"
    monkeypatch.setattr(instacart_guest, "CACHE_FILE", f)
    assert instacart_guest._load_cache() == {"hosts": {}}
    f.write_text(json.dumps({"saved": 0, "hosts": {"x": {"ops": {}}}, "storage_state": {"cookies": []}}))
    assert instacart_guest._load_cache() == {"hosts": {}}
    f.write_text("not json")
    assert instacart_guest._load_cache() == {"hosts": {}}
    instacart_guest._save_cache({"hosts": {"h": {"ops": {"Items": "u"}}}})
    assert instacart_guest._load_cache()["hosts"] == {"h": {"ops": {"Items": "u"}}}
