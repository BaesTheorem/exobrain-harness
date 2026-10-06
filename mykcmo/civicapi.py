"""Client for the MyCivic mobile API that the official myKCMO app uses.

The Kansas City 311 app (Rock Solid's MyCivic platform, Android package
com.civicapps.kansascitymo) talks to https://api.mycivicapps.com/api/v3/.
Unlike the web form in webrai.py, this API has no captcha. Every request
carries an `ApiSignature` header: an HS256 JWT over a small claim set, signed
with a static key that ships inside the APK. The key, the city id and the app
version live in a gitignored config file that `bin/mykcmo-refresh-key`
rebuilds from a fresh APK when the city rotates the key.

INVARIANTS:
- The signing key never appears in tracked source. It is read from CONFIG_PATH.
- A 403 "Signature Verification Failed" raises KeyRejected, so callers can
  tell a rotated key apart from any other failure.
- Nothing here writes to the city on import. Write endpoints are plain
  functions that callers gate behind an explicit confirmation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import uuid
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("MYCIVIC_CONFIG", HERE / "civic-config.json"))
TOKEN_URL = "https://api.mycivicapps.com/token/get_baseurl"
DEFAULT_BASE = "https://api.mycivicapps.com/api/v3/"
USER_AGENT = "okhttp/4.9.0"
API_VERSION = "6.0"


class CivicError(RuntimeError):
    """The API answered, but not with success."""


class KeyRejected(CivicError):
    """The server refused the signature: the APK key has probably rotated."""


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        raise CivicError(
            f"{path} is missing. Run mykcmo/bin/mykcmo-refresh-key to build it from the APK."
        )
    cfg = json.loads(path.read_text())
    if not cfg.get("device_uid"):
        # One stable device id per install, like the Android app's.
        cfg["device_uid"] = uuid.uuid4().hex[:16]
        path.write_text(json.dumps(cfg, indent=2) + "\n")
    return cfg


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign(cfg: dict) -> str:
    """Build the ApiSignature JWT, the same claim set as createJWTPayload."""
    header = _b64(json.dumps({"alg": "HS256"}).encode())
    claims = {
        "city_id": cfg["city_id"],
        "deviceuid": cfg["device_uid"],
        "APPTYPE": "CITY",
        "app_version": cfg["app_version"],
        "device_type": "android",
        "APIVERSION": API_VERSION,
        "nounce": secrets.token_hex(8),
    }
    payload = _b64(json.dumps(claims).encode())
    sig = hmac.new(cfg["key"].encode(), f"{header}.{payload}".encode(), hashlib.sha256)
    return f"{header}.{payload}.{_b64(sig.digest())}"


def _multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----mykcmo" + secrets.token_hex(12)
    out = bytearray()
    for name, value in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += str(value).encode() + b"\r\n"
    for name, (filename, data, ctype) in files.items():
        out += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'
        ).encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _post(url: str, cfg: dict, fields: dict, files: dict | None = None, timeout: int = 90) -> dict:
    body, ctype = _multipart({k: v for k, v in fields.items() if v is not None}, files or {})
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": ctype, "User-Agent": USER_AGENT, "ApiSignature": sign(cfg)},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    # A bad signature comes back two ways: 403 "Signature Verification Failed"
    # (get_main) or response_code 1 with "Invalid API Signature" (myissues and
    # others), where 1 is also a success code. Check the token message first.
    msg = str(data.get("response_token_message", ""))
    if "Signature" in msg:
        raise KeyRejected(msg)
    if data.get("response_code") == 403:
        raise CivicError(msg or "403")
    return data


def base_fields(cfg: dict) -> dict[str, str]:
    """Fields the Android app sends with almost every call."""
    return {
        "city_id": cfg["city_id"],
        "api_version": API_VERSION,
        "device_id": cfg["device_uid"],
        "deviceuid": cfg["device_uid"],
        "app_type": "1",
        "language": "en",
    }


def call(endpoint: str, fields: dict | None = None, files: dict | None = None, cfg: dict | None = None) -> dict:
    """POST to an api/v3 endpoint with the base fields plus `fields`."""
    cfg = cfg or load_config()
    base = cfg.get("base_url") or DEFAULT_BASE
    return _post(base + endpoint, cfg, {**base_fields(cfg), **(fields or {})}, files)


def call_json(endpoint: str, payload: dict, files: dict | None = None, cfg: dict | None = None) -> dict:
    """POST an endpoint whose body is one POST_JSON part (the app's other style)."""
    cfg = cfg or load_config()
    base = cfg.get("base_url") or DEFAULT_BASE
    body = {"city_id": cfg["city_id"], "api_version": API_VERSION, "deviceuid": cfg["device_uid"], **payload}
    return _post(base + endpoint, cfg, {"POST_JSON": json.dumps(body)}, files)


def check(cfg: dict | None = None) -> bool:
    """True when a signed get_main call succeeds. Raises KeyRejected on a bad key."""
    data = call("get_main", {"timestamp": "0"}, cfg=cfg)
    return data.get("response_status", {}).get("response_code") == 1


# ---------------------------------------------------------------------------
# Report endpoints. Field shapes come from the decompiled app; see README.md.
# ---------------------------------------------------------------------------

MENU_REPORT = "10871"  # the "Make a Report" menu
REPORTER_FIELDS = ("reporter_firstname", "reporter_lastname", "reporter_email", "reporter_phone")
_CATALOG: dict | None = None


def catalog(cfg: dict | None = None) -> dict:
    """{categories: [...], subcategories: [...]} from get_main, cached per process."""
    global _CATALOG
    if _CATALOG is None:
        data = call("get_main", {"timestamp": "0"}, cfg=cfg)
        tables = {t.get("table_name"): t.get("records", []) for t in data["response_data"]["data"]}
        _CATALOG = {
            "categories": sorted(tables.get("RAI_CATEGORY", []), key=lambda r: int(r.get("sort_order") or 0)),
            "subcategories": tables.get("RAI_SUBCATEGORY", []),
        }
    return _CATALOG


def find_category(name: str) -> dict:
    cats = catalog()["categories"]
    low = name.strip().lower()
    for c in cats:
        if low in (c["name"].lower(), c["cat_id"]):
            return c
    hits = [c for c in cats if low in c["name"].lower()]
    if len(hits) == 1:
        return hits[0]
    raise ValueError(f"Unknown report type {name!r}. Options: " + ", ".join(c["name"] for c in cats))


def subcategories(cat: dict) -> list[dict]:
    subs = [s for s in catalog()["subcategories"] if s["category_id"] == cat["cat_id"]]
    return sorted(subs, key=lambda s: int(s.get("cat_order") or 0))


def questions(cat: dict, sub: dict | None) -> list[dict]:
    """The custom form questions for a category / first subcategory, sorted."""
    raw = sub["form_data"] if sub and sub.get("form_data") and sub.get("type") else cat.get("form_data", "")
    if not raw:
        return []
    return sorted(json.loads(raw), key=lambda q: int(q.get("sort_order") or 0))


def effective_type(cat: dict, sub: dict | None) -> str:
    return (sub or {}).get("type") or cat.get("type") or "Standard"


def flag(cat: dict, sub: dict | None, key: str) -> str:
    """Subcategory value first, then category, like the app resolves it."""
    return str((sub or {}).get(key) or cat.get(key) or "")


def encode_answer(q: dict, value) -> str:
    t = int(q["type"])
    if t == 1:
        return "YES" if str(value).strip().lower() in ("yes", "y", "true", "1") else "NO"
    if t == 4:
        opts = q.get("dropdown_options") or []
        wanted = value if isinstance(value, list) else [value]
        ids = []
        for w in wanted:
            match = next((o for o in opts if str(w).lower() in (o["id"].lower(), o["value"].lower())), None)
            if not match:
                raise ValueError(f"{q['caption']!r}: {w!r} is not an option ({', '.join(o['value'] for o in opts)})")
            ids.append(match["id"])
        return ",".join(ids)
    return str(value)


def selected_subtype(sub: dict) -> dict:
    keys = ("category_id", "name", "cat_order", "type", "menu_id", "server_id", "autoresponse_text",
            "login_required", "disclaimer_phone", "disclaimer_text", "disclaimer_title", "disclaimer_url",
            "enable_disclaimer", "form_data", "contact_info_required", "thirdparty_type", "thirdparty_id")
    obj = {k: sub.get(k, "") for k in keys}
    obj.update({"Id": sub["subcat_id"], "subCat_id": sub["subcat_id"], "image": "", "share_options": "",
                "sort_order": "", "disclosure": ""})
    return obj


def check_duplicate(cat: dict, sub: dict | None, loc: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    data = call_json("check_duplicate_issue", {
        "latitude": str(loc["lat"]), "longitude": str(loc["lon"]), "address": loc.get("street", ""),
        "city": loc.get("city", "Kansas City"), "state": loc.get("state", "MO"), "zip": loc.get("zip", ""),
        "type": cat["cat_id"], "subtype": sub["subcat_id"] if sub else "", "device_id": cfg["device_uid"],
    }, cfg=cfg)
    rd = data.get("response_data") or {}
    return {"allow_duplicate": str(rd.get("allow_duplicate", "0")), "message": data.get("response_message", "")}


def photo_zip(paths: list[str]) -> tuple[bytes, list[dict]]:
    """Scale each photo to fit 1000x1000 and zip them as the app does."""
    import io
    import time
    import zipfile

    from PIL import Image, ImageOps

    buf = io.BytesIO()
    meta = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, path in enumerate(paths):
            img = ImageOps.exif_transpose(Image.open(os.path.expanduser(path))).convert("RGB")
            img.thumbnail((1000, 1000))
            out = io.BytesIO()
            img.save(out, "JPEG", quality=85)
            name = f"CAM{int(time.time() * 1000) + i}.jpeg"
            z.writestr(name, out.getvalue())
            meta.append({"filename": name, "metadata": {"creation_date": time.strftime("%Y-%m-%d %H:%M:%S")}})
    return buf.getvalue(), meta


def build_issue(cat: dict, sub: dict | None, loc: dict | None, notes: str, answers: dict[str, str],
                contact: dict | None, share: str, files_meta: list[dict], cfg: dict) -> dict:
    import time

    qs = questions(cat, sub)
    etype = effective_type(cat, sub)
    issue: dict = {
        "city_id": cfg["city_id"], "menu_id": MENU_REPORT, "timestamp": str(int(time.time() * 1000)),
        "deviceuid": cfg["device_uid"], "device_id": cfg["device_uid"],
        "type": etype, "type_id": cat["cat_id"], "name": cat["name"], "issue_cat_id": cat["server_id"],
        "subtype": sub["name"] if sub else "",
        "SELECTED_SUB_TYPE": [selected_subtype(sub)] if sub else [],
        "notes": notes, "share_options": share, "files_metadata": files_meta,
        "RAI_LAT": float(loc["lat"]) if loc else "", "RAI_LONG": float(loc["lon"]) if loc else "",
        "api_version": API_VERSION,
    }
    if contact:
        issue.update({k: contact[k] for k in ("first_name", "last_name", "email", "phone") if contact.get(k)})
    if loc:
        issue.update({
            "location": loc["street"], "address": loc["street"], "RAI_STREET": loc["street"],
            "RAI_CITY": loc.get("city", "Kansas City"), "RAI_STATE": loc.get("state", "MO"),
            "RAI_ZIP": loc.get("zip", ""),
        })
    if etype.lower() in ("form_type", "form_type_car") and qs:
        issue["form_data"] = {q["caption"]: answers.get(q["caption"], "") for q in qs}
        issue["new_form_data"] = [
            {"caption": q["caption"], "type": int(q["type"]), "sort_order": int(q.get("sort_order") or 0),
             "enterdValue": answers.get(q["caption"], "")}
            for q in qs
        ]
    return issue


def submit(issue: dict, zip_bytes: bytes | None, cfg: dict | None = None) -> dict:
    """POST report_an_issue. This files a REAL case with the city."""
    import time

    cfg = cfg or load_config()
    issue = {**issue, "offline_timestamp": int(time.time() * 1000)}
    files = {"file_zip": (f"{int(time.time() * 1000)}_images.zip", zip_bytes, "application/zip")} if zip_bytes else None
    base = cfg.get("base_url") or DEFAULT_BASE
    return _post(base + "report_an_issue", cfg, {"issue_details": json.dumps(issue)}, files)


def my_reports(start: int = 0, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    return call_json("myissues", {"device_id": cfg["device_uid"], "start": start}, cfg=cfg)


def strip_reporter(issue: dict) -> dict:
    """Drop other people's contact info, which the detail endpoints leak."""
    return {k: v for k, v in issue.items() if k not in REPORTER_FIELDS}


def report_detail(issue_id: str, cfg: dict | None = None) -> dict:
    data = call("get_issue_detail_citizen", {"issue_id": issue_id}, cfg=cfg)
    issues = (data.get("response_data") or {}).get("issues") or []
    if not issues:
        raise CivicError("No such report, or this device cannot see it.")
    return strip_reporter(issues[0])


def public_map(lat: float, lon: float, status: str = "open", types: list[str] | None = None,
               cfg: dict | None = None) -> list[dict]:
    """Public reports near a point. The server answers HTTP 500 when one call
    names too many categories, so ask in groups of 5, all at once, and merge (each call takes about 6 s)."""
    from concurrent.futures import ThreadPoolExecutor

    names = types or [c["name"] for c in catalog(cfg)["categories"]]
    groups = [names[i:i + 5] for i in range(0, len(names), 5)]

    def one(group: list[str]) -> list[dict]:
        try:
            data = call("reported_issues_map", {
                "menu_id": MENU_REPORT, "lat": str(lat), "lng": str(lon),
                "FilterOptions": json.dumps({"status": status, "issue_type": ",".join(group)}),
            }, cfg=cfg)
        except urllib.error.HTTPError:
            return []
        return (data.get("response_status") or {}).get("response_data") or []

    with ThreadPoolExecutor(max_workers=len(groups) or 1) as pool:
        rows = [r for chunk in pool.map(one, groups) for r in chunk]
    seen: set[str] = set()
    return [r for r in rows if not (str(r.get("report_id")) in seen or seen.add(str(r.get("report_id"))))]


def geocode(address: str) -> dict:
    """{street, lat, lon, city, state, zip}. US Census first, then OpenStreetMap
    Nominatim, because the Census matcher misses some KC streets."""
    import urllib.parse
    import urllib.request

    import webrai

    try:
        g = webrai.geocode(address)
        return {"street": g["address"].split(",")[0].title(), "lat": float(g["lat"]), "lon": float(g["lon"]),
                "city": (g["city"] or "Kansas City").title(), "state": g["state"] or "MO", "zip": g["zip"]}
    except ValueError:
        pass
    query = address if "," in address else f"{address}, Kansas City, MO"
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "addressdetails": 1, "limit": 1, "countrycodes": "us"})
    req = urllib.request.Request(url, headers={"User-Agent": "mykcmo-mcp/1.0 (personal 311 client)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        hits = json.loads(r.read())
    if not hits:
        raise ValueError(f"Could not geocode address: {address!r}")
    a = hits[0].get("address", {})
    street = " ".join(x for x in (a.get("house_number"), a.get("road")) if x) or address.split(",")[0]
    # The city's duplicate check matches the address text, which uses USPS
    # abbreviations ("4131 E Truman Rd"), so shorten OSM's spelled-out form.
    abbr = {"North": "N", "South": "S", "East": "E", "West": "W", "Street": "St", "Road": "Rd",
            "Avenue": "Ave", "Boulevard": "Blvd", "Drive": "Dr", "Parkway": "Pkwy", "Terrace": "Ter",
            "Place": "Pl", "Lane": "Ln", "Court": "Ct", "Trafficway": "Trfy", "Highway": "Hwy"}
    street = " ".join(abbr.get(w, w) for w in street.split())
    return {"street": street, "lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]),
            "city": a.get("city", "Kansas City"), "state": "MO", "zip": a.get("postcode", "")}


def case_number(record: dict) -> str:
    """The city's 311 case number, or "" before the report syncs to the city
    CRM. Until then display_wo holds MyCivic's own id, so never use it."""
    tp = record.get("thirdparty_params") or {}
    if isinstance(tp, str):
        try:
            tp = json.loads(tp) if tp else {}
        except ValueError:
            tp = {}
    return str(tp.get("case_number", "")) if isinstance(tp, dict) else ""


# ---------------------------------------------------------------------------
# Automatic update requests. The city's own records are the shared state: a
# filed "311 Request Update" shows in myissues for this device id, so the
# iPhone app and the Mac job see each other's requests and never ask twice.
# ---------------------------------------------------------------------------

UPDATE_CATEGORY = "311 Request Update"
STALE_DAYS = 7
_CLOSED = ("resolved", "closed", "cancel", "complete")


def _ts(record: dict) -> float:
    """Latest movement on a report: updated_on (UTC), last_action_date, added_on."""
    from datetime import datetime, timezone

    import time

    # myissues' epoch fields run hours ahead (added_on +2 h on 2026-10-05);
    # updated_on, a UTC string, is right. Nothing may be later than now.
    best = filed(record)
    raw = str(record.get("updated_on") or "")
    try:
        best = max(best, datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        pass
    best = min(best, time.time())
    raw = str(record.get("last_action_date") or "")
    try:
        best = max(best, datetime.strptime(raw, "%m/%d/%Y").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        pass
    return best


def filed(record: dict) -> float:
    """Filing time: the earlier of added_on and updated_on, never after now."""
    import time
    from datetime import datetime, timezone

    times = [float(record.get("added_on") or 0) or time.time()]
    try:
        times.append(datetime.strptime(str(record.get("updated_on") or ""), "%Y-%m-%d %H:%M:%S")
                     .replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        pass
    return min(min(times), time.time())


def is_update_request(record: dict) -> bool:
    return UPDATE_CATEGORY.lower() in str(record.get("name") or record.get("issue_type") or "").lower()


def reference(record: dict) -> str:
    cn = case_number(record)
    return f"request #{cn}" if cn else f"myKCMO app report {record.get('id')}"


def last_asked(record: dict, mine: list[dict]) -> float:
    """When an update was last requested for this report (0 if never)."""
    keys = {f"report {record.get('id')}"} | ({f"#{cn}", cn} if (cn := case_number(record)) else set())
    asks = [filed(r) for r in mine if is_update_request(r)
            and any(k and k in str(r.get("description") or "") for k in keys)]
    return max(asks, default=0.0)


def due_for_update(mine: list[dict], now: float | None = None, days: int = STALE_DAYS) -> list[dict]:
    """Open reports with no movement and no update request for `days` days."""
    import time

    now = now or time.time()
    out = []
    for r in mine:
        if is_update_request(r) or any(c in str(r.get("status", "")).lower() for c in _CLOSED):
            continue
        if now - max(_ts(r), last_asked(r, mine)) >= days * 86400:
            out.append(r)
    return out
