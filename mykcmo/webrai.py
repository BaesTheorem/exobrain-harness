"""myKCMO Web Report-An-Issue client (Rock Solid MyCivic backend).

This is the write side of the myKCMO server: it files real 311 requests with
Kansas City through the same endpoint the city's public web form uses
(webrai.mycivicapps.com -> report_submit.php).

The form has an anti-spam gate. It is a *soft* gate: reCAPTCHA v3 is optional,
and when no v3 token is supplied the server falls back to a classic
distorted-text image captcha (get_captcha.php, a 140x60 JPEG keyed to the
PHP session). We take the image path: open_captcha() downloads that image,
the calling agent (MIST) reads it with vision, and submit() posts the answer.

Why this is acceptable here (documented in README): this files ONE real,
Alex-initiated request at a time, carrying his real contact info, at human
pace, with an explicit confirmation before every submission. It is a resident
automating his own civic reports, not bulk/anonymous spam. It deliberately
does NOT auto-solve at scale, farm captchas, or forge a reCAPTCHA score.

INVARIANTS:
- Every submit carries a human-read captcha answer bound to the same cookie
  jar that fetched the image; there is no unattended solve loop here.
- Contact fields are never hardcoded; they come from the caller or env.
- report_submit.php is only ever hit from submit(), never speculatively.
"""

import http.cookiejar
import json
import time
import urllib.parse
import urllib.request

WEBRAI_BASE = "https://webrai.mycivicapps.com"
CITYHASH = "1adb57d07d9ea1e1dd8160697f745c0d"  # Kansas City, MO whitelabel hash
WHITELABEL = "mycity"
MENU_ID = "10871"  # KC top-level report menu
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# KC report types (menu 10871). value = "10871_<issue_type_id>". Scraped from
# the live KC form 2026-08-23; refresh with refresh_report_types() if the city
# changes its menu.
REPORT_TYPES: dict[str, str] = {
    "311 Request Update": "10871_38647",
    "A Pothole": "10871_53842",
    "Animal Services": "10871_56927",
    "Bike Lanes": "10871_52009",
    "Bridge": "10871_11261",
    "Contract and Labor Violations": "10871_49777",
    "Discrimination Report": "10871_49776",
    "Food Safety": "10871_11107",
    "Graffiti": "10871_52751",
    "Hate/Bigotry Incident": "10871_52247",
    "Health Code Violations": "10871_11135",
    "Healthy Homes": "10871_49501",
    "Tents or Sleeping Structures": "10871_51863",
    "Illegal Dumping": "10871_23932",
    "Land Bank Issues": "10871_30180",
    "Leaf and Brush Curbside Pickup": "10871_36587",
    "Parking Meter issues": "10871_38676",
    "Parks and Recreation": "10871_11142",
    "Property Violations": "10871_11064",
    "Public Safety": "10871_11134",
    "Recycling Cart Program": "10871_52951",
    "Right-of-Way / Inspections": "10871_53357",
    "Sewer and Stormwater": "10871_11533",
    "Short Term Rental": "10871_52895",
    "Sidewalks and Curbs": "10871_11252",
    "Snow": "10871_50228",
    "Solid Waste Services": "10871_34543",
    "Street Cleaning / Sweeping": "10871_49562",
    "Street Maintenance": "10871_11240",
    "Streetlights": "10871_11140",
    "Traffic Calming or Concerns": "10871_52011",
    "Traffic Signals": "10871_11084",
    "Traffic Signs and Street Markings": "10871_11141",
    "Trash Recycling Bulky Services": "10871_11067",
    "Trash Cart Program": "10871_54473",
    "Trees City Row": "10871_11249",
    "Vehicles and Parking": "10871_11189",
    "Vision Zero Feedback": "10871_54769",
    "Water Service": "10871_11456",
    "Water, Sewer, Stormwater Issues": "10871_54573",
    "Zoning and Permits": "10871_11086",
}


def new_session() -> urllib.request.OpenerDirector:
    """An opener with its own cookie jar (isolates one report's PHP session)."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA)]
    return opener


def _get(opener, path: str) -> bytes:
    with opener.open(WEBRAI_BASE + path, timeout=30) as r:
        return r.read()


def _post_json_data(opener, path: str, payload: dict) -> dict:
    body = urllib.parse.urlencode({"json_data": json.dumps(payload)}).encode()
    req = urllib.request.Request(
        WEBRAI_BASE + path,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with opener.open(req, timeout=40) as r:
        raw = r.read().decode("utf-8", "replace").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def captcha_id() -> str:
    """Mirror the form's unique_code(): hex of unix seconds, padded to 14."""
    return format(int(time.time()), "x").ljust(14, "0")


def resolve_name(report_type: str) -> tuple[str, str]:
    """Accept a type label or a raw '10871_x' value; return (value, label)."""
    if report_type in REPORT_TYPES:
        return REPORT_TYPES[report_type], report_type
    rt = report_type.strip()
    for label, value in REPORT_TYPES.items():
        if value == rt or label.lower() == rt.lower():
            return value, label
    raise ValueError(
        f"Unknown report type {report_type!r}. Call list_report_categories()."
    )


def fetch_subtypes(report_type: str) -> dict:
    """Load a type's subtypes + template rules from load_report_sub_type.php."""
    value, label = resolve_name(report_type)
    opener = new_session()
    payload = {
        "city_id": CITYHASH,
        "city_latitude": "",
        "city_longitude": "",
        "city_map_kml": "",
        "report_type_id": value,
        "current_template": "",
    }
    d = _post_json_data(opener, "/load_report_sub_type.php", payload)
    subs = []
    select = d.get("select") or {}
    # select maps subtype label -> {id, report_type, ...}. The dict key IS the
    # human name. A subtype whose report_type is "form_type" adds optional
    # follow-up questions (e.g. "number of potholes") we don't collect; the
    # base report still files without them.
    if isinstance(select, dict):
        for name, entry in select.items():
            if isinstance(entry, dict):
                sid = entry.get("id", "")
                extra = entry.get("report_type", "") == "form_type"
            else:
                sid, extra = str(entry), False
            subs.append(
                {"id": str(sid), "name": name, "has_extra_questions": extra}
            )
    return {
        "report_type": value,
        "label": label,
        "template": d.get("template", ""),
        "location_required": d.get("location_required", "") == "yes",
        "description_required": d.get("description_required", "") == "yes",
        "login_required": d.get("login_required", "") == "yes",
        "attachment_required": d.get("attachment_required", "") == "yes",
        "disclaimer": (d.get("disclaimer_text") or "").strip(),
        "subtypes": subs,
    }


def geocode(address: str) -> dict:
    """US Census geocoder -> {address, lat, lon, city, state, zip}. Free, no key.
    Appends ', Kansas City, MO' when the address has no comma."""
    query = address if "," in address else f"{address}, Kansas City, MO"
    params = urllib.parse.urlencode(
        {
            "address": query,
            "benchmark": "Public_AR_Current",
            "format": "json",
        }
    )
    url = (
        "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?"
        + params
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    matches = data.get("result", {}).get("addressMatches", [])
    if not matches:
        raise ValueError(f"Could not geocode address: {address!r}")
    m = matches[0]
    coords = m["coordinates"]
    comp = m.get("addressComponents", {})
    return {
        "address": m.get("matchedAddress", query),
        "lat": str(coords["y"]),
        "lon": str(coords["x"]),
        "city": comp.get("city", "Kansas City"),
        "state": comp.get("state", "MO"),
        "zip": comp.get("zip", ""),
    }


def open_captcha(opener, out_path: str) -> str:
    """Download a fresh image captcha into out_path (JPEG) on this session.
    Returns the unique_captcha_id the answer must be submitted under."""
    cid = captcha_id()
    img = _get(opener, f"/get_captcha.php?rand={cid}&pre={cid}")
    with open(out_path, "wb") as f:
        f.write(img)
    return cid


def build_payload(
    *,
    report_type: str,
    sub_type: str,
    description: str,
    location: dict | None,
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    template: str,
    location_required: bool,
    description_required: bool,
    captcha_answer: str,
    unique_captcha_id: str,
    share_options: str = "private",
) -> dict:
    """Assemble the report_submit.php json_data payload, mirroring the web
    form's field set. Empty strings for every optional field the form sends."""
    loc = location or {}
    lat = loc.get("lat", "") if location_required else ""
    lon = loc.get("lon", "") if location_required else ""
    return {
        "cityhash_id": CITYHASH,
        "whitelabel": WHITELABEL,
        "str_report_type": report_type,
        "template": template,
        "sub_type": sub_type,
        "comment": description,
        "additional_notes": description,
        "description_required": "yes" if description_required else "no",
        "location_required": "yes" if location_required else "no",
        "address": loc.get("address", ""),
        "latitude": lat,
        "longitude": lon,
        "city": loc.get("city", ""),
        "state": loc.get("state", ""),
        "zip": loc.get("zip", ""),
        "cross_street": "",
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "share_options": share_options,
        "uploaded_photo": "",
        "report_image_delete": "",
        "magic_key": "",
        "rai_contact_mandatory": "",
        "prevent_duplicate_issue": "",
        "enable_duplicate_issues": "",
        "permit_type": "",
        "inspection_code": "",
        # captcha: no reCAPTCHA v3 token; image-captcha answer instead.
        "captcha": "",
        "custom_captcha": captcha_answer,
        "unique_captcha_id": unique_captcha_id,
        "show_captcha": "1",
    }


def submit(opener, payload: dict) -> dict:
    """POST the report. Returns a normalized result dict:
    {ok, work_order_id, message, captcha_failed, error}."""
    d = _post_json_data(opener, "/report_submit.php", payload)
    err = (d.get("error") or "").strip()
    wo = (d.get("wo_id") or "").strip() if isinstance(d.get("wo_id"), str) else d.get("wo_id")
    captcha_failed = bool(err and "security code" in err.lower()) or bool(
        (d.get("custom_captcha") or "").strip()
    )
    return {
        "ok": bool(wo) and not err,
        "work_order_id": wo or "",
        "message": (d.get("autoResponseText") or "").strip(),
        "captcha_failed": captcha_failed,
        "error": err,
        "raw": d,
    }
